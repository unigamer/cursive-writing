"""Raster previews (PNG) of strokes, for checking glyphs and joins by eye."""

from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw


def draw_paths(paths, size_px=(1600, 400), margin=20, scale=None, width=2,
               colors=None, show_ends=False, guides=None, img=None, offset=(0, 0)):
    """Draw polylines (lists of (N,2) arrays, y up). Returns PIL image.

    `guides` is a list of y values drawn as faint horizontal lines.
    """
    paths = [np.asarray(p, float) for p in paths if len(p)]
    if img is None:
        img = Image.new("RGB", size_px, "white")
    d = ImageDraw.Draw(img)
    if not paths:
        return img
    allp = np.vstack(paths)
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    if scale is None:
        span = np.maximum(hi - lo, 1e-6)
        scale = min((size_px[0] - 2 * margin) / span[0], (size_px[1] - 2 * margin) / span[1])
        ox, oy = margin - lo[0] * scale, margin + hi[1] * scale
    else:
        ox, oy = offset

    def tr(p):
        return [(ox + x * scale, oy - y * scale) for x, y in p]

    if guides:
        for y in guides:
            yy = oy - y * scale
            d.line([(0, yy), (img.width, yy)], fill=(225, 230, 240), width=1)
    for i, p in enumerate(paths):
        c = colors[i % len(colors)] if colors else (20, 20, 40)
        if len(p) == 1:
            x, y = tr(p)[0]
            d.ellipse([x - 2, y - 2, x + 2, y + 2], fill=c)
            continue
        d.line(tr(p), fill=c, width=width, joint="curve")
        if show_ends:
            (x0, y0), (x1, y1) = tr(p[:1])[0], tr(p[-1:])[0]
            d.ellipse([x0 - 4, y0 - 4, x0 + 4, y0 + 4], outline=(0, 160, 0), width=2)
            d.ellipse([x1 - 4, y1 - 4, x1 + 4, y1 + 4], outline=(200, 0, 0), width=2)
    return img
