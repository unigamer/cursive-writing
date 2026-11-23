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
    o = style.pairs.get(a.char + b.char)
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


def assemble_word(placed: list[PlacedGlyph], style: Style) -> Word:
    """Join placed glyphs (already positioned) into pen paths."""
    w = Word()
    if not placed:
        return w
    params = [pair_params(style, a.glyph, b.glyph) for a, b in zip(placed, placed[1:])]
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
        elif i == len(placed) - 1 and pg.flourish > 0:
            stroke = extend_flourish(stroke, pg.flourish)
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
    # deferred strokes (dots, crossbars) after the word, left to right
    for i, pg in enumerate(placed):
        w.paths.extend(pg.deferred)
        w.pieces.extend((d, "deferred", i) for d in pg.deferred)
    allp = np.vstack(w.paths)
    w.width = float(allp[:, 0].max()) if len(allp) else 0.0
    return w
