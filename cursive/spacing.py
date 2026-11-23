"""Even letter spacing.

Fonts space letters for their own overlapping hairlines. Once those hairlines
are replaced by connectors, the visible rhythm depends on the gap between one
letter's body and the next. Here each glyph's body edges are measured (slant
removed, within the x-height band, ignoring the lead-in / lead-out that the
join engine cuts away), and glyphs are re-spaced so every pair gets the same
gap. Edges are averaged over several heights so round letters sit a little
closer than straight ones, as they do optically.
"""

from __future__ import annotations

import numpy as np

from . import geometry as g
from .join import cut_end, cut_start

HEIGHTS = np.linspace(0.15, 0.85, 8)


def body_points(gl) -> np.ndarray:
    """Main-stroke points without the joinable lead-in / lead-out."""
    p = gl.main.points
    if gl.lead_in and not gl.hook_retrace:  # a hook is redrawn when joined, so it counts
        p = cut_start(p, gl.lead_in)
    if gl.lead_out:
        p = cut_end(p, gl.lead_out)
    return g.resample(p, 0.01) if len(p) > 1 else p


def edges(gl, slant: float) -> tuple[float, float] | None:
    """(left, right) body edges, slant removed, averaged over HEIGHTS."""
    p = body_points(gl)
    if len(p) < 2:
        return None
    x = p[:, 0] - slant * p[:, 1]
    lefts, rights = [], []
    for h in HEIGHTS:
        m = np.abs(p[:, 1] - h) < 0.06
        if m.any():
            lefts.append(x[m].min())
            rights.append(x[m].max())
    if not lefts:
        return None
    # half optical (mean over heights), half extreme, so round letters tuck in
    # a little without colliding
    return (0.5 * float(np.mean(lefts)) + 0.5 * float(np.min(lefts)),
            0.5 * float(np.mean(rights)) + 0.5 * float(np.max(rights)))


def pair_gaps(style, chars: str) -> dict[str, float]:
    """Gap between body edges for every joinable pair, with current advances."""
    out = {}
    for a in chars:
        for b in chars:
            ga, gb = style.glyphs[a][0], style.glyphs[b][0]
            ea, eb = edges(ga, style.glyph_slant), edges(gb, style.glyph_slant)
            if ea and eb:
                out[a + b] = ga.advance + eb[0] - ea[1]
    return out


def apply_even_spacing(style, gap: float, chars: str | None = None) -> None:
    """Shift every glyph so its body starts at x=0 and set its advance so each
    pair has `gap` between bodies. Modifies the style's glyphs in place."""
    for ch, variants in list(style.glyphs.items()) + list(style.forms.items()):
        if chars and (ch if isinstance(ch, str) else ch[0]) not in chars:
            continue
        for gl in variants:
            e = edges(gl, style.glyph_slant)
            if e is None:
                continue
            left, right = e
            for s in gl.strokes:
                s.points = s.points - np.array([left, 0.0])
            gl.advance = (right - left) + gap


def ink_edges(paths, slant: float, side: str) -> float | None:
    """Left or right edge of all ink within the x-height band (slant removed),
    half averaged over heights and half extreme, as in `edges`."""
    pts = np.vstack([g.resample(p, 0.01) if len(p) > 1 else p for p in paths])
    x = pts[:, 0] - slant * pts[:, 1]
    vals = []
    for h in HEIGHTS:
        m = np.abs(pts[:, 1] - h) < 0.06
        if m.any():
            vals.append(x[m].max() if side == "right" else x[m].min())
    if not vals:
        return None
    ext = max(vals) if side == "right" else min(vals)
    return 0.5 * float(np.mean(vals)) + 0.5 * ext


def unjoined_dx(style, a, b, gap: float | None = None, clear: float = 0.2) -> float:
    """Spacing adjustment for a pair drawn WITHOUT a join, so it is kerned like
    normal letters: the body gap matches the style's letter gap, and no part of
    either letter (flourishes included) comes closer than `clear`."""
    gap = style.letter_gap if gap is None else gap
    A = [s.points for s in a.strokes]
    B = [s.points for s in b.strokes]
    ra = ink_edges(A, style.glyph_slant, "right")
    lb = ink_edges(B, style.glyph_slant, "left")
    base = a.advance + style.tracking
    dx = 0.0 if ra is None or lb is None else gap + ra - lb - base
    Ap = np.vstack([g.resample(p, 0.03) if len(p) > 1 else p for p in A])
    Bp = np.vstack([g.resample(p, 0.03) if len(p) > 1 else p for p in B])
    # only the facing sides can touch
    Ap = Ap[Ap[:, 0] > Ap[:, 0].max() - 4.0]
    Bp = Bp[Bp[:, 0] < Bp[:, 0].min() + 4.0]

    def closest(d):
        off = np.array([base + d, 0.0])
        Bs = Bp + off
        a = Ap[Ap[:, 0] > Bs[:, 0].min() - clear]
        if not len(a):
            return np.inf
        b = Bs[Bs[:, 0] < a[:, 0].max() + clear]
        if not len(b):
            return np.inf
        return float(np.min(np.linalg.norm(a[:, None, :] - b[None, :, :], axis=2)))

    if closest(dx) < clear:  # push apart: coarse steps, then refine back
        while closest(dx) < clear and dx < 4:
            dx += 0.2
        for _ in range(10):
            if closest(dx - 0.02) >= clear:
                dx -= 0.02
            else:
                break
    return round(float(dx), 3)
