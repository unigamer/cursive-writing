"""Accented letters composed from a style's own base letters.

An accented letter is its base glyph (with all its hand edits, alternates and
positional forms) plus accent marks, drawn after the word like an i-dot. It
carries `"base"` so it joins, kerns and pairs exactly like the base letter.

Marks live in `styles/<style>/marks.json`, traced from the style's source
font by `tools/compose_glyphs.py` (or synthesised, for the slash of ø).
Each is stored in the frame of the base letter's main glyph, with that
glyph's anchor (the horizontal centre of its body); composing onto another
variant of the base moves the mark by the difference in anchors.

This module is used by the tools and the tests only: composed glyphs are
written out as ordinary glyph files, so the engines never compose anything.
"""

from __future__ import annotations

import unicodedata

import numpy as np

# Western European letters (Latin-1, plus Ÿ), composed from a base letter
ACCENTED = ("àáâãäåçèéêëìíîïñòóôõöøùúûüýÿ"
            "ÀÁÂÃÄÅÇÈÉÊËÌÍÎÏÑÒÓÔÕÖØÙÚÛÜÝŸ")
# letters whose mark is a slash through the body rather than an accent
SLASHED = {"ø": "o", "Ø": "O"}
# whole new letters and symbols, traced from the font like any other glyph
STANDALONE = "æœßÆŒ‘’“”–—€…«»¡¿"


def base_of(ch: str) -> str:
    return SLASHED.get(ch) or unicodedata.normalize("NFD", ch)[0]


def anchor(points, slant: float, upper: bool) -> float:
    """Horizontal centre of a glyph's body (slant removed, so at y=0)."""
    p = np.asarray(points, float)
    top = 3.0 if upper else 1.0
    m = (p[:, 1] > 0.05) & (p[:, 1] < top)
    if not m.any():
        m = np.ones(len(p), bool)
    x = p[m, 0] - slant * p[m, 1]
    return float(0.5 * (x.min() + x.max()))


def slash_mark(base_glyph: dict, slant: float, upper: bool) -> list[dict]:
    """A straight slash through the body, bottom-left to top-right (ø, Ø),
    leaning a little more than the letters do, as the fonts draw it."""
    from .glyph import Glyph
    from .spacing import body_points

    gl = Glyph.from_dict(base_glyph)
    # a lowercase o without its joining hairlines; a capital whole (some cut
    # most of their bowl as an exit stroke they rarely use)
    p = gl.main.points if upper else body_points(gl)
    top = float(p[:, 1].max()) if upper else 1.0
    x = p[:, 0] - slant * p[:, 1]
    # centred on the bowl at half height, where side loops and swashes don't reach
    row = np.abs(p[:, 1] - 0.5 * top) < 0.1 * top
    xs = x[row] if row.sum() >= 2 else x
    mid = 0.5 * float(xs.min() + xs.max())
    half = 0.25 * top
    (x0, y0), (x1, y1) = (mid - half, -0.12 * top), (mid + half, 1.08 * top)
    pts = [[x0 + slant * y0, y0], [x1 + slant * y1, y1]]
    return [{"points": np.round(pts, 4).tolist(), "kind": "line"}]


def compose(ch: str, base_glyph: dict, mark: dict, slant: float) -> dict:
    """The glyph for accented `ch`: `base_glyph` (a glyph file's dict) plus
    the marks of `mark` (a marks.json entry), moved onto this variant."""
    upper = ch.isupper()
    shift = anchor(base_glyph["strokes"][0]["points"], slant, upper) - mark["anchor"]
    strokes = [dict(s) for s in base_glyph["strokes"]]
    if mark["base"] == "i":
        strokes = strokes[:1]  # the accent replaces the dot (a spiral or a short dash, by style)
    for s in mark["strokes"]:
        pts = np.asarray(s["points"], float) + np.array([shift, 0.0])
        strokes.append({"points": np.round(pts, 4).tolist(), "deferred": True, "kind": s.get("kind", "line")})
    out = {k: v for k, v in base_glyph.items() if k not in ("strokes", "edited", "source", "char", "base")}
    out = {"char": ch, "base": mark["base"], **out, "strokes": strokes,
           "source": f"composed: {mark['base']} + marks.json"}
    return out
