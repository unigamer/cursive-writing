"""Will the drawing still read once it is plotted with a real pen?

Plotted lines have width. A counter (the enclosed white of an e, o, a loop
or ascender loop) whose width is close to the pen width fills in with ink and
the letter turns into a blob. This module finds every counter in a word, as
drawn with a hairline, and measures how wide it is, so we can say at what
x-height (for a given pen) the writing stays legible.

All geometry is in x-height units. A counter of width W (x-heights) drawn
at x-height S mm with a pen P mm wide keeps W*S - P mm of white.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage

EYE_MIN = 0.15  # x-heights
RES = 160  # raster pixels per x-height
MIN_COUNTER = 0.06  # counters narrower than this (x-heights) are slivers
# left by retraced strokes, not letter shapes: they are meant to close up


@dataclass
class Counter:
    centre: np.ndarray  # x-height units, word space
    width: float  # widest inscribed circle diameter, centreline to centreline
    area: float  # x-heights squared
    glyph: int  # index of the nearest glyph in the word (-1 if unknown)

    @property
    def elongation(self) -> float:
        """area / width^2: about 0.8 for a round eye, large for a long sliver."""
        return self.area / max(self.width, 1e-6) ** 2

    @property
    def is_eye(self) -> bool:
        """A letter's counter (e eye, o, a, ascender loop): the reader needs to
        see white in it. Anything narrower is a sliver (a t or i drawn up and
        back down its stem) or a knot where strokes cross (the foot of an s):
        those close into a thicker stroke or a dot, which still reads."""
        return self.width >= EYE_MIN

    def white_mm(self, size_mm: float, pen_mm: float) -> float:
        """White left inside the counter when drawn at this size and pen."""
        return self.width * size_mm - pen_mm


def counters(paths: list[np.ndarray], pieces=None, res: int = RES) -> list[Counter]:
    """All enclosed white regions of a drawing (hairline rendering)."""
    pts = np.vstack(paths)
    lo = pts.min(axis=0) - 0.2
    hi = pts.max(axis=0) + 0.2
    w, h = (np.ceil((hi - lo) * res)).astype(int) + 1
    img = Image.new("L", (int(w), int(h)), 0)
    d = ImageDraw.Draw(img)
    lw = 2  # hairline, px

    def px(p):
        return [((x - lo[0]) * res, (hi[1] - y) * res) for x, y in p]

    for p in paths:
        if len(p) > 1:
            d.line(px(p), fill=255, width=lw, joint="curve")
    ink = np.asarray(img) > 0
    lab, n = ndimage.label(~ink)
    if n == 0:
        return []
    border = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]])))
    dist = ndimage.distance_transform_edt(~ink)
    out = []
    centres_g = None
    if pieces:
        centres_g = [(np.mean(pp, axis=0), gi) for pp, kind, gi in pieces if kind == "glyph" and len(pp)]
    objs = ndimage.find_objects(lab)
    for k in range(1, n + 1):
        if k in border or objs[k - 1] is None:
            continue
        sl = objs[k - 1]
        m = lab[sl] == k
        area_px = int(m.sum())
        dmax = float(dist[sl][m].max())
        width = (2 * dmax + lw) / res
        if width < MIN_COUNTER:
            continue
        ys, xs = np.nonzero(m)
        cx = (xs.mean() + sl[1].start) / res + lo[0]
        cy = hi[1] - (ys.mean() + sl[0].start) / res
        c = np.array([cx, cy])
        gi = -1
        if centres_g:
            # the glyph whose ink is nearest the counter's centre
            best = np.inf
            for pp, kind, idx in pieces:
                if kind != "glyph" or len(pp) == 0:
                    continue
                dd = float(np.min(np.linalg.norm(pp - c, axis=1)))
                if dd < best:
                    best, gi = dd, idx
        out.append(Counter(c, width, area_px / res**2, gi))
    return out


WHITE_FRAC = 0.5  # a counter must keep at least this fraction of a pen width of white
KEEP = 0.95  # ... in this fraction of counters


def narrow_width(widths: np.ndarray, keep: float = KEEP) -> float:
    return float(np.quantile(widths, 1 - keep)) if len(widths) else 0.0


def min_size_for(width: float, pen_mm: float, white_frac: float = WHITE_FRAC) -> float:
    """Smallest x-height (mm) at which a counter `width` x-heights wide keeps
    `white_frac` of a pen width of white."""
    return float((1 + white_frac) * pen_mm / width) if width > 0 else 0.0


def min_size(widths: np.ndarray, pen_mm: float, white_frac: float = WHITE_FRAC, keep: float = KEEP) -> float:
    """Smallest x-height (mm) at which `keep` of the counters still show white
    at least `white_frac` of the pen width."""
    return min_size_for(narrow_width(widths, keep), pen_mm, white_frac)
