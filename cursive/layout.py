"""Lay out text as lines of joined words. All units are x-heights, y up."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from . import geometry as g
from .glyph import Style
from .join import PlacedGlyph, Word, assemble_word
from .variation import Variation


@dataclass
class Line:
    paths: list[np.ndarray]
    width: float
    baseline: float  # y of this line's baseline


# Neighbouring words are kept apart by their actual ink, so flourishes, long
# t-bars and capital swashes never close up the gap. Two tiers:
#  - the style's `word_clear` (about one letter gap: closer than that and two
#    words read as one), bought with a limited push so spacing stays even;
#  - WORD_TOUCH, never broken: a swash that would cross the previous word is
#    pushed clear however far that takes (up to WORD_TOUCH_MAX).
WORD_PUSH_MAX = 1.2  # most a word is moved right to keep `word_clear`
WORD_TOUCH = 0.3  # hard minimum distance (x-heights) between ink of neighbouring words
WORD_TOUCH_MAX = 4.0  # most a word is moved right to keep WORD_TOUCH


def clearance_push(A: np.ndarray, B: np.ndarray, clear: float, limit: float) -> float:
    """How far to move point set B right so no point comes within `clear` of A."""
    A = A[A[:, 0] > B[:, 0].min() - clear - limit]

    def closest(d):
        a = A[A[:, 0] > B[:, 0].min() + d - clear]
        b = B[B[:, 0] + d < A[:, 0].max() + clear] if len(A) else B[:0]
        if not len(a) or not len(b):
            return np.inf
        return float(np.min(np.linalg.norm(a[:, None, :] - (b + [d, 0])[None, :, :], axis=2)))

    d = 0.0
    while closest(d) < clear and d < limit:
        d += 0.1
    return min(d, limit)


def word_push(style: Style, prev, ink: np.ndarray, lo: float) -> float:
    """Extra space (beyond word_space) before a word so its ink keeps clear of
    the previous word's. `prev` is the previous word's (word, (lo, hi), ink, push)
    entry; `ink`, `lo` are the new word's resampled ink and body left edge."""
    _, (plo, phi), pink, _ = prev
    A = pink - np.array([plo, 0.0])
    B = ink + np.array([(phi - plo) + style.word_space - lo, 0.0])
    push = clearance_push(A, B, style.word_clear, WORD_PUSH_MAX)
    if push >= WORD_PUSH_MAX:
        push += clearance_push(A, B + np.array([push, 0.0]), WORD_TOUCH, WORD_TOUCH_MAX - push)
    return push


def body_extent(paths, slant: float) -> tuple[float, float]:
    """Left/right edge of a word's ink within the x-height band, slant removed.

    Word gaps are judged here, not at the tips of descender loops, capital
    flourishes or t-bars.
    """
    pts = np.vstack(paths)
    band = pts[(pts[:, 1] > -0.05) & (pts[:, 1] < 1.05)]
    if len(band) == 0:
        band = pts
    x = band[:, 0] - slant * band[:, 1]
    return float(x.min()), float(x.max())


def place_word(text: str, style: Style, var: Variation, overrides: dict | None = None) -> tuple[Word, float]:
    """Return the joined word and its advance width (cursor movement).

    `overrides` maps a character to a Glyph to use instead of the style's own
    (the editor's live preview).
    """
    placed = []
    x = 0.0
    # positions ignore trailing/leading punctuation: "word," still ends in 'd'
    letters = [i for i, c in enumerate(text) if c.isalpha()]
    first, last = (letters[0], letters[-1]) if letters else (-1, -1)
    for i, ch in enumerate(text):
        pos = "isol" if first == last == i else "init" if i == first else "fina" if i == last else "medi"
        options = [overrides[ch]] if overrides and ch in overrides else style.options(ch, pos)
        if not options:
            x += style.word_space * 0.5
            continue
        gl = var.choose(options)
        m, off, dadv = var.glyph_transform()
        warp = var.loop_warp(gl.main.points, style.glyph_slant) if ch.islower() else None
        o = np.array([x, 0.0]) + off

        def tf(p, m=m, o=o):
            return p @ m.T + o

        if placed:  # per-pair spacing adjustment from the optimised pair table
            pair = style.pairs.get(placed[-1].glyph.char + gl.char)
            if pair and pair.get("dx"):
                x += float(pair["dx"])
                shifted = np.array([x, 0.0]) + off
                tf = lambda p, m=m, o=shifted: p @ m.T + o  # noqa: E731
        shape = warp or (lambda p: p)
        placed.append(PlacedGlyph(
            glyph=gl,
            main=tf(shape(gl.main.points)),
            deferred=[tf(shape(s.points)) for s in gl.deferred],
            x=x,
            flourish=var.flourish() if i == last == len(text) - 1 and ch.islower() else 0.0,
        ))
        x += gl.advance * m[0, 0] + style.tracking + dadv
    return assemble_word(placed, style), x


def layout(text: str, style: Style, width: float | None = None, seed: int | None = 0,
           amount: float = 1.0, align: str = "left") -> list[Line]:
    """Break text into lines no wider than `width` (x-heights, None = no wrap).

    Explicit newlines start new lines; blank lines leave a gap.
    """
    var = Variation(style.variation, seed, amount)
    lines: list[Line] = []
    y = 0.0
    for para in text.split("\n"):
        words = para.split()
        cur: list[tuple[Word, tuple[float, float], np.ndarray, float]] = []  # word, body extent, ink, push
        cur_w = 0.0

        def flush():
            nonlocal cur, cur_w, y
            paths = []
            x = 0.0
            for k, (word, (lo, hi), _, push) in enumerate(cur):
                if k:
                    x += push
                shift = x - lo
                paths.extend(p + np.array([shift, y]) for p in word.paths)
                x += (hi - lo) + style.word_space
            lines.append(Line(paths, max(x - style.word_space, 0.0), y))
            y -= style.line_height
            cur, cur_w = [], 0.0

        for wtext in words:
            word, _ = place_word(wtext, style, var)
            if not word.paths:
                continue
            lo, hi = body_extent(word.paths, style.glyph_slant)
            ink = np.vstack([g.resample(p, 0.03) if len(p) > 1 else p for p in word.paths])
            push = word_push(style, cur[-1], ink, lo) if cur else 0.0
            add = (hi - lo) if not cur else style.word_space + push + (hi - lo)
            if width is not None and cur and cur_w + add > width:
                flush()
                push = 0.0
                add = hi - lo
            cur.append((word, (lo, hi), ink, push))
            cur_w += add
        flush()

    # alignment, slant, then smooth per-line wobble (never breaks joins)
    shear = np.tan(np.radians(style.slant))
    for ln in lines:
        dx = 0.0
        if width is not None and align == "center":
            dx = (width - ln.width) / 2
        elif width is not None and align == "right":
            dx = width - ln.width
        field = var.line_field()
        out = []
        for p in ln.paths:
            q = p + np.array([dx, 0.0])
            if shear:
                q = q + np.column_stack([(q[:, 1] - ln.baseline) * shear, np.zeros(len(q))])
            q = g.resample(q, 0.02) if len(q) > 1 else q
            out.append(field(q))
        # keep flourishes (descender loops, capital swashes) inside the left margin
        minx = min((float(p[:, 0].min()) for p in out), default=0.0)
        if width is not None and minx < 0:
            out = [p + np.array([-minx, 0.0]) for p in out]
        ln.paths = out
    return lines
