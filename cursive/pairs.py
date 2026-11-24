"""Score and optimise the join of every letter pair.

Every pair a->b is joined in isolation with a candidate parameter set
(exit/entry cut points, connector tension and arrival, extra spacing, or no
join at all), scored for how it looks, and the best parameters are kept in
styles/<style>/pairs.json, which the join engine reads.

The score is a sum of penalties in x-height units; lower is better. A good
join is short and smooth, does not cross or run along either letter, does not
dive below the baseline or loop, and keeps the letters apart.
"""

from __future__ import annotations

import itertools
import string
from dataclasses import dataclass, replace

import numpy as np

from . import geometry as g
from .glyph import Glyph, Style
from .join import connector, cut_end, entry_stroke, pair_params, top_start_variant
from .spacing import unjoined_dx

NO_JOIN_LOWER = 6.0  # cost of lifting the pen between two lowercase letters
NO_JOIN_CAPITAL = 1.6
GRID_ABOVE = 0.8  # pairs still scoring worse than this get a joint grid search  # after a capital, standing alone is often traditional


# ------------------------------------------------------------- geometry bits


def _segments_cross(P: np.ndarray, Q: np.ndarray) -> int:
    """Number of proper crossings between polylines P and Q."""
    if len(P) < 2 or len(Q) < 2:
        return 0
    a, b = P[:-1, None, :], P[1:, None, :]
    c, d = Q[None, :-1, :], Q[None, 1:, :]

    def orient(p, q, r):
        return np.sign((q[..., 0] - p[..., 0]) * (r[..., 1] - p[..., 1])
                       - (q[..., 1] - p[..., 1]) * (r[..., 0] - p[..., 0]))

    o1, o2 = orient(a, b, c), orient(a, b, d)
    o3, o4 = orient(c, d, a), orient(c, d, b)
    return int(np.sum((o1 * o2 < 0) & (o3 * o4 < 0)))


def _trim(p: np.ndarray, start: float = 0.0, end: float = 0.0) -> np.ndarray:
    """Drop `start` arc length from the start and `end` from the end."""
    a = g.arc_lengths(p)
    if len(p) < 2 or a[-1] <= start + end:
        return p[:0]
    keep = (a >= start) & (a <= a[-1] - end)
    return p[keep]


def _near(P: np.ndarray, conn: np.ndarray, other: np.ndarray, pad: float = 0.5) -> np.ndarray:
    """Points of P inside the box around the connector, or near the other letter."""
    if not len(P):
        return P
    lo = conn.min(axis=0) - pad
    hi = conn.max(axis=0) + pad
    box = np.all((P >= lo) & (P <= hi), axis=1)
    olo, ohi = other.min(axis=0) - 0.2, other.max(axis=0) + 0.2
    box |= np.all((P >= olo) & (P <= ohi), axis=1)
    return P[box]


def _min_dist(P: np.ndarray, Q: np.ndarray) -> float:
    if not len(P) or not len(Q):
        return np.inf
    return float(np.min(np.linalg.norm(P[:, None, :] - Q[None, :, :], axis=2)))


def _turning(p: np.ndarray) -> tuple[float, float]:
    """(total absolute turning in radians, max curvature 1/x-height)."""
    q = g.resample(p, 0.02)
    if len(q) < 3:
        return 0.0, 0.0
    d = np.diff(q, axis=0)
    ang = np.arctan2(d[:, 1], d[:, 0])
    da = np.abs((np.diff(ang) + np.pi) % (2 * np.pi) - np.pi)
    return float(da.sum()), float(da.max() / 0.02)


# ------------------------------------------------------------------- scoring


@dataclass
class JoinResult:
    score: float
    parts: dict
    prev: np.ndarray  # first glyph as drawn
    conn: np.ndarray
    nxt: np.ndarray  # second glyph as drawn


_LOW_LOOP: dict[int, bool] = {}


def _opens_with_low_loop(b: Glyph) -> bool:
    """Does the letter start low on a closed oval (o, a, d, g, q in many hands)?"""
    k = id(b)
    if k not in _LOW_LOOP:
        # e also opens with a small loop, but is meant to be entered low
        _LOW_LOOP[k] = b.char in "adgoq" and top_start_variant(b.main.points) is not None
    return _LOW_LOOP[k]


def _downstroke_start(b: Glyph) -> float:
    """Penalty weight for cutting into a letter that opens with a downstroke
    from the top (no entry hairline of its own): 0 if it opens otherwise,
    2 for an ascender top (h, k, l, b), 1 for an x-height stem (i, r, u)."""
    p = b.main.points
    if b.lead_in > 0 or len(p) < 2 or p[0, 1] < 0.8 or g.start_tangent(p, 0.06)[1] > -0.3:
        return 0.0
    return 2.0 if p[0, 1] > 1.3 else 1.0


def evaluate(style: Style, a: Glyph, b: Glyph, prm: dict) -> JoinResult:
    """Join a->b with parameters `prm` and score it."""
    A = a.main.points
    B = b.main.points + np.array([a.advance + style.tracking + prm["dx"], 0.0])
    parts: dict[str, float] = {}
    if not prm["join"]:
        # capitals stand alone unless the style traditionally joins them
        cost = NO_JOIN_CAPITAL if a.char.isupper() and a.char not in style.join_capitals else NO_JOIN_LOWER
        parts["no_join"] = cost
        # still penalise collisions between the two letters
        if _segments_cross(A, B) or _min_dist(g.resample(A, 0.03), g.resample(B, 0.03)) < 0.05:
            parts["collide"] = 3.0
        # spacing should match proper kerning for an unjoined pair
        parts["kern"] = 1.5 * abs(prm["dx"] - unjoined_dx(style, a, b))
        return JoinResult(sum(parts.values()), parts, A, A[:0], B)

    prev = cut_end(A, prm["lead_out"])
    nxt, arrive = entry_stroke(B, b, a, prm, style.glyph_slant)
    if len(prev) < 2 or len(nxt) < 2:
        return JoinResult(99.0, {"degenerate": 99.0}, prev, A[:0], nxt)
    conn = connector(prev, nxt, prm["tension"], style.glyph_slant, arrive)
    conn = g.resample(conn, 0.01)

    # bodies, minus a little near the joints so touching there is not a "crossing";
    # only ink near the join matters (big capitals would be slow otherwise)
    # a "retrace" arrival deliberately lies along the next letter's stem, so
    # ignore a longer stretch there rather than counting wobbles as crossings
    lay = 0.35 if arrive == "retrace" else 0.07
    A_b = _near(_trim(g.resample(prev, 0.015), end=0.07), conn, B)
    B_b = _near(_trim(g.resample(nxt, 0.015), start=lay), conn, A)
    C_in = _trim(conn, 0.05, 0.05 if lay < 0.1 else 0.3)

    loop_ok = nxt[0, 1] > 1.4  # climbing into a looped ascender (l, h, b, k)
    cross_b = _segments_cross(C_in, B_b)
    if loop_ok:
        cross_b = max(0, cross_b - 1)  # a loop crosses its own stem once by design
    crossings = _segments_cross(C_in, A_b) + cross_b
    parts["cross"] = 2.5 * crossings

    # running on top of a letter (some hugging under an oval is natural, so mild)
    if len(C_in):
        dA = np.min(np.linalg.norm(C_in[:, None, :] - A_b[None, ::2, :], axis=2), axis=1) if len(A_b) else np.full(len(C_in), 9.0)
        dB = np.min(np.linalg.norm(C_in[:, None, :] - B_b[None, ::2, :], axis=2), axis=1) if len(B_b) else np.full(len(C_in), 9.0)
        parts["hug"] = 1.2 * float(np.mean(np.minimum(dA, dB) < 0.03))

    # the letters themselves must not collide
    if _segments_cross(A_b[::2], B_b[::2]):
        parts["collide"] = 3.0
    else:
        dmin = _min_dist(A_b[::3], B_b[::3])
        if dmin < 0.08:
            parts["collide"] = 3.0 * (0.08 - dmin) / 0.08

    turn, kmax = _turning(conn)
    parts["turn"] = 0.8 * max(0.0, turn - (2 * np.pi if loop_ok else 2.4))
    parts["kink"] = 0.6 if kmax > 25 else 0.0

    L, chord = g.length(conn), float(np.linalg.norm(conn[-1] - conn[0]))
    if chord > 1e-6 and not loop_ok:
        parts["long"] = 1.0 * max(0.0, L / chord - 1.6)
    # long horizontal reach is ugly; a long climb into a tall letter is natural
    reach = abs((conn[-1, 0] - style.glyph_slant * conn[-1, 1]) - (conn[0, 0] - style.glyph_slant * conn[0, 1]))
    parts["far"] = 0.6 * max(0.0, reach - 1.2)

    lo = float(conn[:, 1].min())
    hi = float(conn[:, 1].max())
    # below the baseline is only a fault if the connector sinks there itself;
    # rising from a tail that already ends low (capital H, L, Q, U) is natural
    floor = min(-0.05, float(conn[0, 1]) - 0.12)
    parts["dip"] = 3.0 * max(0.0, floor - lo)
    body_end = float(cut_end(A, a.lead_out)[-1, 1])
    if body_end > 0.2:
        # after b, o, v, w the pen is already up in the body of the letter:
        # the join should stay up there, not swoop down to the baseline and back
        parts["low_road"] = 1.5 * max(0.0, 0.8 * body_end - lo)
    if conn[-1, 1] < 0.45 and _opens_with_low_loop(b):
        # sliding in along the baseline under an o/a/d/g/q reads as a tail on
        # the letter; the hairline should rise to the top of the oval instead
        parts["under"] = 0.8
    top_ok = max(conn[0, 1], conn[-1, 1]) + (0.6 if loop_ok else 0.25)
    parts["overshoot"] = 2.0 * max(0.0, hi - top_ok)

    # smooth departure; a sharp arrival is only natural at the top of a letter
    t_prev = g.end_tangent(prev, 0.06)
    t_c0 = g.start_tangent(conn, 0.06)
    parts["depart"] = 1.0 * g.turn_angle(t_prev, t_c0) ** 2
    t_c1 = g.end_tangent(conn, 0.06)
    t_next = g.start_tangent(nxt, 0.06)
    arr = g.turn_angle(t_c1, t_next)
    if arr > np.radians(100) and nxt[0, 1] < 0.6:
        parts["arrive"] = 1.5

    # the pen should travel forwards along the writing direction
    x = conn[:, 0] - style.glyph_slant * conn[:, 1]
    back = float(np.max(np.maximum.accumulate(x) - x))
    parts["backwards"] = 2.0 * max(0.0, back - 0.08)

    parts["dx"] = 1.5 * abs(prm["dx"])
    # cutting the top off a letter that starts with a downstroke shortens the
    # letter itself (an h turns into an n): the connector should climb to the top
    parts["chop"] = _downstroke_start(b) * max(0.0, prm["lead_in"] - b.lead_in)
    return JoinResult(sum(parts.values()), parts, prev, conn, nxt)


# -------------------------------------------------------------- optimisation


def _descends(gl: Glyph) -> bool:
    return float(gl.main.points[:, 1].min()) < -0.6


def _first_peak(b: Glyph) -> float:
    """Arc length to the top of a letter's opening upstroke (a short entry stub
    rising into a stem, as in i, n, u). Cutting there lets a join that arrives
    high (after b, o, v, w) go straight across to the top of the stem instead
    of diving to the stub. 0 if the letter does not open by rising to x-height."""
    p = b.main.points
    if len(p) < 3 or p[0, 1] > 0.7:
        return 0.0
    i = 0
    while i < len(p) - 1 and p[i + 1, 1] >= p[i, 1] - 1e-3:
        i += 1
    if p[i, 1] < 0.75:
        return 0.0
    return round(max(0.0, float(g.arc_lengths(p)[i]) - 0.02), 3)


def _candidates(style: Style, a: Glyph, b: Glyph, base: dict) -> dict[str, list]:
    La, Lb = g.length(a.main.points), g.length(b.main.points)
    # cuts relative to the glyph's own, plus a fixed grid (a glyph whose
    # default cut is 0 may still need its exit trimmed, e.g. copperplate l->u)
    lo = sorted({round(v, 3) for v in (base["lead_out"], 0.0, base["lead_out"] * 0.5,
                                         base["lead_out"] + 0.15, base["lead_out"] + 0.35,
                                         0.15, 0.3, 0.45, 0.6)
                 if 0 <= v <= 0.6 * La})
    li = sorted({round(v, 3) for v in (base["lead_in"], 0.0, base["lead_in"] * 0.5,
                                         base["lead_in"] + 0.15, 0.15, 0.3, _first_peak(b))
                 if 0 <= v <= 0.6 * Lb})
    return {
        "lead_out": lo,
        "lead_in": li,
        "tension": [0.3, 0.45, 0.6],
        "arrive": ["auto", "glyph", "slant", "chord", "retrace"],
        # capitals, and two descender loops side by side (fj, gj, jj), may
        # need more room
        "dx": [-0.15, 0.0, 0.15, 0.3, 0.45, 0.6]
        + ([0.8, 1.2] if a.char.isupper() or (_descends(a) and _descends(b)) else []),
        "over": [None, True, "corner", "bottom", False],
    }


def optimise_pair(style: Style, a: Glyph, b: Glyph, passes: int = 2) -> tuple[dict, JoinResult, JoinResult]:
    """Coordinate-descent search over join parameters for a->b.

    Returns (best params, best result, default result)."""
    base = pair_params(replace(style, pairs={}), a, b)
    default = evaluate(style, a, b, base)
    if not base["join"]:
        return base, default, default
    cands = _candidates(style, a, b, base)
    best, best_r = dict(base), default
    # coordinate descent from a few different starting points, to avoid getting
    # stuck (e.g. an exit cut that only looks bad until the entry form changes)
    starts = [dict(base), {**base, "over": True}, {**base, "over": "corner"},
              {**base, "over": "bottom"}, {**base, "arrive": "glyph"}]
    peak = _first_peak(b)
    if peak in cands["lead_in"]:
        starts.append({**base, "lead_in": peak, "arrive": "chord"})
    for start in starts:
        cur = start
        cur_r = evaluate(style, a, b, cur) if start is not base else default
        for _ in range(passes):
            improved = False
            for key, values in cands.items():
                for v in values:
                    if cur.get(key) == v:
                        continue
                    trial = {**cur, key: v}
                    r = evaluate(style, a, b, trial)
                    if r.score < cur_r.score - 1e-6:
                        cur, cur_r, improved = trial, r, True
            if not improved:
                break
        if cur_r.score < best_r.score:
            best, best_r = cur, cur_r
        if best_r.score < 0.3:  # already excellent
            break
    if best_r.score > GRID_ABOVE:
        # coordinate descent moves one setting at a time and can stall where
        # two must change together (exit cut + arrival); try them jointly
        # (with or without cutting the entry up to its first peak)
        # (capitals are skipped: they rarely join, and their big glyphs are slow)
        entries = sorted({best["lead_in"], peak} if peak in cands["lead_in"] and not a.char.isupper()
                         else {best["lead_in"]})
        for li, lo, arr, ov, dx in itertools.product(entries, cands["lead_out"], cands["arrive"], cands["over"], cands["dx"]):
            trial = {**best, "lead_in": li, "lead_out": lo, "arrive": arr, "over": ov, "dx": dx}
            r = evaluate(style, a, b, trial)
            if r.score < best_r.score - 1e-6:
                best, best_r = trial, r
    nj = {**best, "join": False, "dx": unjoined_dx(style, a, b)}
    r = evaluate(style, a, b, nj)
    if r.score < best_r.score:
        best, best_r = nj, r
    return best, best_r, default


def all_pairs(style: Style) -> list[tuple[str, str]]:
    lower = [c for c in string.ascii_lowercase if c in style.glyphs]
    upper = [c for c in string.ascii_uppercase if c in style.glyphs]
    return [(x, y) for x in lower + upper for y in lower]


def optimise_style(style: Style, pairs=None, min_gain: float = 0.15, progress=None) -> dict:
    """Optimise every pair; return the table to store in pairs.json."""
    table = {}
    report = []
    pairs = pairs or all_pairs(style)
    for k, (x, y) in enumerate(pairs):
        a, b = style.glyphs[x][0], style.glyphs[y][0]
        best, r, d = optimise_pair(style, a, b)
        defaults = pair_params(replace(style, pairs={}), a, b)
        report.append((x + y, d.score, r.score, best))
        if d.score - r.score > min_gain:
            keep = {key: best[key] for key in ("join", "dx", "lead_out", "lead_in", "tension", "arrive", "over")
                    if best[key] != defaults[key]}
            keep["score"] = round(r.score, 3)
            keep["was"] = round(d.score, 3)
            table[x + y] = keep
        if progress:
            progress(k + 1, len(pairs), x + y, d.score, r.score)
    return {"pairs": table, "report": report}
