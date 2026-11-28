"""Assemble glyphs into joined words.

A word is laid out glyph by glyph along the baseline. Between each pair that
is allowed to join (see Style.can_join), the first glyph's exit hairline
(`lead_out`) and the second glyph's entry hairline (`lead_in`) are cut away
and replaced by a single connector curve. Joins never cross word boundaries:
each word is assembled on its own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from . import geometry as g
from .glyph import Glyph, Style

TANGENT_PROBE = 0.06  # arc length (x-heights) used to measure direction at a cut


@dataclass
class PlacedGlyph:
    glyph: Glyph
    main: np.ndarray  # main stroke, already transformed into word space
    deferred: list[np.ndarray]
    x: float
    flourish: float = 0.0  # word-final only: extend the finishing hairline by this much


@dataclass
class Word:
    paths: list[np.ndarray] = field(default_factory=list)  # pen-down paths in drawing order
    joins: list[tuple[int, int]] = field(default_factory=list)  # glyph index pairs that were joined
    width: float = 0.0
    glyph_x: list[float] = field(default_factory=list)
    # labelled pieces for debugging/editing: (points, kind, glyph index)
    # kind is "glyph", "conn" or "deferred"
    pieces: list[tuple[np.ndarray, str, int]] = field(default_factory=list)


def cut_start(p: np.ndarray, s: float) -> np.ndarray:
    """Drop the first `s` of arc length."""
    if s <= 0:
        return p
    a = g.arc_lengths(p)
    if s >= a[-1]:
        return p[-1:]
    i = int(np.searchsorted(a, s))
    return np.vstack([g.point_at(p, s), p[i:]])


def cut_end(p: np.ndarray, s: float) -> np.ndarray:
    """Drop the last `s` of arc length."""
    if s <= 0:
        return p
    a = g.arc_lengths(p)
    keep = a[-1] - s
    if keep <= 0:
        return p[:1]
    i = int(np.searchsorted(a, keep))
    return np.vstack([p[:i], g.point_at(p, keep)])


ARRIVALS = ("auto", "glyph", "slant", "chord", "horizontal", "retrace")


def connector(prev: np.ndarray, nxt: np.ndarray, tension: float, slant: float = 0.0,
              arrive: str | np.ndarray = "auto") -> np.ndarray:
    """Curve from the end of `prev` to the start of `nxt`.

    It leaves along prev's direction of travel (smooth join). How it arrives:
      auto        nxt's own direction when compatible; a looped approach into
                  a downward ascender; otherwise a hairline rising along the
                  slant that meets the letter in a sharp point
      glyph       always nxt's own starting direction (smooth)
      slant       rising along the writing slant (sharp point)
      chord       straight in along the chord
      retrace     up along the letter's first stroke, turning back down it
      horizontal  level, from the left (over-the-top joins)
    """
    p0, p1 = prev[-1], nxt[0]
    chord = p1 - p0
    dist = np.linalg.norm(chord)
    if dist < 1e-6:
        return np.vstack([p0, p1])
    t0 = g.end_tangent(prev, min(TANGENT_PROBE, 0.5 * g.length(prev))) if len(prev) > 1 else g.unit(chord)
    t1 = g.start_tangent(nxt, min(TANGENT_PROBE, 0.5 * g.length(nxt))) if len(nxt) > 1 else g.unit(chord)
    c = chord / dist
    n = max(8, int(dist / 0.02))
    if np.dot(t0, c) < -0.2:
        t0 = g.unit(c)
    if not isinstance(arrive, str):
        return g.hermite(p0, t0, p1, g.unit(arrive), tension=tension, n=n)
    if arrive == "glyph":
        return g.hermite(p0, t0, p1, t1, tension=tension, n=n)
    if arrive == "slant":
        return g.hermite(p0, t0, p1, g.unit(np.array([slant, 1.0])), tension=tension, n=n)
    if arrive == "retrace":
        # come up along the letter's first stroke and turn back down it
        # (pointed tops of t, i, u): the hairline lies on the stem
        return g.hermite(p0, t0, p1, -t1, tension=tension, n=n)
    if arrive == "chord":
        return g.hermite(p0, t0, p1, c, tension=tension, n=n)
    if arrive == "horizontal":
        return g.hermite(p0, t0, p1, np.array([1.0, 0.0]), tension=tension, n=n)
    # auto
    if p1[1] > 1.4 and t1[1] < 0:
        # ascender drawn downward (l, h, b, k): the hairline climbs, curls over
        # the top and arrives heading down the stem -> a looped ascender
        return g.hermite(p0, t0, p1, t1, tension=tension, n=n, h1=0.45)
    if np.dot(t1, c) < 0.25:
        # cusp (oval letters): sweep low and rise along the writing slant, so
        # the hairline sits under the letter's own curve
        t1 = g.unit(np.array([slant, 1.0]))
        if np.dot(t1, c) < 0.2:
            t1 = g.unit(c + np.array([0.0, 0.3]))
        tension = max(tension, 0.55)
    return g.hermite(p0, t0, p1, t1, tension=tension, n=n)


def pair_params(style: Style, a: Glyph, b: Glyph) -> dict:
    """Join settings for the pair a->b: defaults, overridden by the style's
    optimised per-pair table (pairs.json)."""
    p = {"join": style.can_join(a, b), "dx": 0.0, "lead_out": a.lead_out, "lead_in": b.lead_in,
         "tension": style.tension, "arrive": "auto", "over": None}
    o = style.pairs.get(a.key + b.key)
    if o:
        p.update({k: v for k, v in o.items() if k in p})
        if not style.can_join(a, b):
            p["join"] = False  # rules (spaces, punctuation, no_join lists) always win
    return p


def entry_stroke(stroke: np.ndarray, gl: Glyph, prev: Glyph, prm: dict, slant: float = 0.0):
    """The next glyph's main stroke as drawn when joined into.
    Returns (stroke, arrive) where arrive may be forced by the entry form."""
    over = prm["over"]
    if over is None:
        over = prev.exit == "high" and not gl.hook_retrace
    if over:
        mode = over if over in ("corner", "bottom") else "top"
        v = top_start_variant(stroke, mode, slant)
        if v is not None:
            # level over the top; a rising hairline into the corner; a smooth
            # under-curve into the bottom
            auto = {"top": "horizontal", "corner": "slant", "bottom": "glyph"}[mode]
            return v, (prm["arrive"] if prm["arrive"] != "auto" else auto)
    lead_in = prm["lead_in"]
    cut = cut_start(stroke, lead_in)
    if gl.hook_retrace and lead_in > 0:
        # arrive at the top, flick out along the hook and back (c, some a/d/q)
        hook = cut_end(stroke, g.length(stroke) - lead_in)
        cut = np.vstack([hook[::-1], hook[1:], cut[1:]])
    return cut, prm["arrive"]


def top_start_variant(p: np.ndarray, mode: str = "top", slant: float = 0.0) -> np.ndarray | None:
    """Redraw a letter that opens with a closed loop started low on its right
    (o, a, d, g, q in many scripts) so the pen starts higher on the loop:

      mode "top"     at the loop's highest point (after high exits: the
                     connector runs in level along the top, as in "bo")
      mode "corner"  at the loop's top-right corner, where a stem meets it
                     (the hairline sweeps under the oval and rises to it)

    The ink is the same: round the loop from there, close it, and carry on.
    Returns None if the stroke does not open with a closed loop.
    """
    a = g.arc_lengths(p)
    total = a[-1]
    if total == 0 or p[0, 1] > 0.6:
        return None
    # the loop closes when the pen comes back to the start after going round
    near = np.flatnonzero((a > max(1.2, 0.2 * total)) & (np.linalg.norm(p - p[0], axis=1) < 0.1))
    if not len(near):
        return None
    c = int(near[0])
    loop = p[: c + 1]
    if mode == "bottom":
        # enter tangentially at the bottom of the oval, heading right: bottom ->
        # up the right side to the start -> round the whole loop -> back along
        # the bottom-right quarter to the start -> carry on (stem / exit)
        lower = np.flatnonzero(loop[:, 1] < 0.45 * loop[:, 1].max())
        if not len(lower):
            return None
        b = int(lower[np.argmin(loop[lower, 1])])
        if b == 0 or b >= c:
            return None
        return np.vstack([loop[b:], loop[1 : b + 1], loop[b:][1:], p[c + 1 :]])
    if mode == "corner":
        upper = np.flatnonzero(loop[:, 1] > 0.55 * loop[:, 1].max())
        x = loop[upper, 0] - slant * loop[upper, 1]
        t = int(upper[np.argmax(x)])
    else:
        t = int(np.argmax(loop[:, 1]))
    if t == 0 or loop[t, 1] < 0.6:
        return None
    rest = p[c + 1 :]
    # if what follows the loop climbs back up to the start point anyway (the
    # stem of an a/d), it redraws the right side itself; otherwise close it
    if len(rest) and np.min(np.linalg.norm(rest[: max(2, len(rest) // 2)] - loop[t], axis=1)) < 0.12:
        return np.vstack([loop[t:], rest])
    return np.vstack([loop[t:], loop[1 : t + 1], loop[:t][::-1], rest])


def _rot(v: np.ndarray, deg: float) -> np.ndarray:
    a = np.radians(deg)
    c, s = np.cos(a), np.sin(a)
    return np.array([c * v[0] - s * v[1], s * v[0] + c * v[1]])


def extend_flourish(stroke: np.ndarray, length: float) -> np.ndarray:
    """Carry a word-final hairline on a little further, curling gently upward
    (a finishing stroke). Only when the stroke already ends rising to the
    right; anything else is left as it is."""
    if len(stroke) < 3 or g.length(stroke) < 0.2:
        return stroke
    t = g.end_tangent(stroke, min(TANGENT_PROBE, 0.5 * g.length(stroke)))
    p0 = stroke[-1]
    # a hairline leaving the body of the letter, not the top of a stem (d, t)
    if not (t[0] > 0.25 and t[1] > 0.1 and p0[1] < 1.0):
        return stroke
    p1 = p0 + length * _rot(t, 15)
    tail = g.hermite(p0, t, p1, _rot(t, 40), tension=0.45, n=max(8, int(length / 0.02)))
    return np.vstack([stroke, tail[1:]])


# Dots and accents keep clear of the word's ink: a flourish that would curl
# up into its own i-dot is shortened, and a mark that lands on a neighbour's
# loop (the grave of cafè under a leaning f) is nudged off it.
MARK_CLEAR = 0.12  # nearest a dot or accent may come to the word's other ink
FLOURISH_MARK_CLEAR = 0.35  # nearest a word-final flourish may come to its own mark
MARK_NUDGE = ((0.0, 1.0), (0.6, 0.8), (-0.6, 0.8), (1.0, 0.0), (-1.0, 0.0))  # tried in this order
MARK_NUDGE_STEPS = 15  # of 0.04 x-heights each


def _sample(p: np.ndarray) -> np.ndarray:
    return g.resample(p, 0.02) if len(p) > 1 else p


def _gap2(a: np.ndarray, b: np.ndarray) -> float:
    """Squared distance between the closest points of two point sets."""
    d = a[:, None, :] - b[None, :, :]
    return float(np.min(d[..., 0] * d[..., 0] + d[..., 1] * d[..., 1]))


def mark_strokes(gl: Glyph) -> list[bool]:
    """For each deferred stroke: is it a free-standing mark above the letter
    (an i-dot or accent), rather than a stroke drawn across it (t-bar, x, ø)?"""
    main = _sample(gl.main.points)
    return [float(s.points[:, 1].min()) > 0.75 and _gap2(_sample(s.points), main) > 0.03 * 0.03
            for s in gl.deferred]


def flourish_clear_of_marks(stroke: np.ndarray, pg: PlacedGlyph) -> np.ndarray:
    """The word-final flourish, shortened (or dropped) where it would reach
    towards the letter's own dot or accent. Never closer than the plain tail."""
    marks = [d for d, m in zip(pg.deferred, mark_strokes(pg.glyph)) if m]
    if not marks:
        return extend_flourish(stroke, pg.flourish)
    ink = np.vstack([_sample(d) for d in marks])
    want = min(FLOURISH_MARK_CLEAR * FLOURISH_MARK_CLEAR, _gap2(_sample(stroke), ink))
    for f in (1.0, 0.7, 0.4):
        s = extend_flourish(stroke, pg.flourish * f)
        if _gap2(_sample(s), ink) >= want:
            return s
    return stroke


def nudge_mark(mark: np.ndarray, ink: np.ndarray) -> np.ndarray:
    """Move a dot or accent the least distance that takes it MARK_CLEAR from
    `ink`; if nothing in reach does, as far from it as reach allows."""
    q = _sample(mark)
    clear2 = MARK_CLEAR * MARK_CLEAR
    best, best_d = mark, _gap2(q, ink)
    if best_d >= clear2:
        return mark
    for k in range(1, MARK_NUDGE_STEPS + 1):
        for dx, dy in MARK_NUDGE:
            off = np.array([dx * 0.04 * k, dy * 0.04 * k])
            d = _gap2(q + off, ink)
            if d >= clear2:
                return mark + off
            if d > best_d:
                best, best_d = mark + off, d
    return best


# A letter's exit hairline is drawn long enough to reach the next letter, and
# when it joins it is cut away (lead_out) for the connector. At the end of a
# word nothing replaces it, so it is cut short instead: a finishing flick.
FINAL_RISE = 0.3  # x-heights a word-final tail climbs from the bottom of its turn


def trim_final_tail(stroke: np.ndarray, lead_out: float) -> np.ndarray:
    """End the unjoined exit hairline once it has risen FINAL_RISE from its
    lowest point (counted from the baseline when the low point is below it,
    as in g, y, z). Tails that never climb that far are left whole."""
    if lead_out <= 0 or len(stroke) < 3:
        return stroke
    s = g.arc_lengths(stroke)
    start = int(np.searchsorted(s, s[-1] - lead_out))
    if start >= len(stroke) - 1:
        return stroke
    j = start + int(np.argmin(stroke[start:, 1]))
    target = max(float(stroke[j, 1]), 0.0) + FINAL_RISE
    for k in range(j + 1, len(stroke)):
        if stroke[k, 1] >= target:
            a, b = stroke[k - 1], stroke[k]
            t = (target - a[1]) / (b[1] - a[1])
            return np.vstack([stroke[:k], a + t * (b - a)])
    return stroke


def _bar_only(pg: PlacedGlyph) -> bool:
    """A t whose only deferred stroke is its crossbar."""
    return pg.glyph.key == "t" and len(pg.deferred) == 1 and len(pg.deferred[0]) > 1


def deferred_strokes(placed: list[PlacedGlyph], joins: list[tuple[int, int]]) -> list[tuple[int, np.ndarray]]:
    """Strokes drawn after the word, left to right, as (glyph index, points).

    Joined t's (tt, ttt) share one crossbar, as a scribe crosses them: the
    first bar is stretched to end where the last one ends. One pen lift
    instead of two, and it reads as a doubled t at a glance."""
    out = []
    joined = set(joins)
    i = 0
    while i < len(placed):
        k = i
        while _bar_only(placed[k]) and k + 1 < len(placed) and _bar_only(placed[k + 1]) and (k, k + 1) in joined:
            k += 1
        if k > i:
            bar = placed[i].deferred[0]
            a = g.arc_lengths(bar)
            t = a / a[-1]
            shift = placed[k].deferred[0][-1] - bar[-1]
            out.append((i, bar + t[:, None] * shift))
            i = k + 1
            continue
        out.extend((i, d) for d in placed[i].deferred)
        i += 1
    return out


def assemble_word(placed: list[PlacedGlyph], style: Style) -> Word:
    """Join placed glyphs (already positioned) into pen paths."""
    w = Word()
    if not placed:
        return w
    params = [pair_params(style, a.glyph, b.glyph) for a, b in zip(placed, placed[1:])]
    # the word's last letter, ignoring trailing punctuation ("hair," ends in r)
    last_letter = max((i for i, pg in enumerate(placed) if pg.glyph.key.isalpha()), default=-1)
    current: np.ndarray | None = None
    for i, pg in enumerate(placed):
        stroke = pg.main
        prm_in = params[i - 1] if i > 0 else None
        prm_out = params[i] if i < len(placed) - 1 else None
        joined_in = prm_in is not None and prm_in["join"]
        joins_out = prm_out is not None and prm_out["join"]
        arrive = "auto"
        if joined_in:
            stroke, arrive = entry_stroke(stroke, pg.glyph, placed[i - 1].glyph, prm_in, style.glyph_slant)
        if joins_out:
            stroke = cut_end(stroke, prm_out["lead_out"])
        elif i == len(placed) - 1 and pg.glyph.final_trim > 0:
            stroke = cut_end(stroke, pg.glyph.final_trim)  # tidy word-final tail
        elif i == last_letter:
            stroke = trim_final_tail(stroke, pg.glyph.lead_out)
            if pg.flourish > 0:
                stroke = flourish_clear_of_marks(stroke, pg)
        if joined_in and current is not None:
            bridge = connector(current, stroke, prm_in["tension"], style.glyph_slant, arrive)
            current = np.vstack([current, bridge[1:-1], stroke])
            w.joins.append((i - 1, i))
            w.pieces.append((bridge, "conn", i))
        else:
            if current is not None:
                w.paths.append(current)
            current = stroke
        w.pieces.append((stroke, "glyph", i))
        w.glyph_x.append(pg.x)
    if current is not None:
        w.paths.append(current)
    # deferred strokes (dots, crossbars) after the word, left to right;
    # dots and accents kept clear of everything else drawn
    later = deferred_strokes(placed, w.joins)
    is_mark = [any(d is s and m for s, m in zip(placed[i].deferred, mark_strokes(placed[i].glyph)))
               for i, d in later]
    if any(is_mark):
        ink = np.vstack([_sample(p) for p in w.paths] + [_sample(d) for (_, d), m in zip(later, is_mark) if not m])
        later = [(i, nudge_mark(d, ink) if m else d) for (i, d), m in zip(later, is_mark)]
    for i, d in later:
        w.paths.append(d)
        w.pieces.append((d, "deferred", i))
    allp = np.vstack(w.paths)
    w.width = float(allp[:, 0].max()) if len(allp) else 0.0
    return w
