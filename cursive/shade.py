"""Faux pointed-pen shading for plotters.

A pointed nib makes downstrokes thick and upstrokes hairline. A plotter pen
has a fixed width, so the swell is imitated with extra passes beside each
downstroke, tapered to nothing at both ends.

The passes are woven into the stroke itself: at the end of a downstroke the
pen runs back up the first offset, down the second, and so on (always an even
number), arriving back where it left off and carrying on. No pen lifts are
added.
"""

from __future__ import annotations

import numpy as np

from . import geometry as g


def _weights(p: np.ndarray, slant: float) -> np.ndarray:
    """0..1 per point: how much this part of the line is a downstroke (page mm, y down)."""
    d = np.gradient(p, axis=0)
    n = np.linalg.norm(d, axis=1, keepdims=True)
    d = d / np.maximum(n, 1e-9)
    down = g.unit(np.array([-slant, 1.0]))  # y down on the page; slanted script leans right
    w = np.clip(d @ down, 0, 1) ** 2
    k = np.ones(9) / 9  # smooth so the swell grows and fades gradually
    return np.convolve(np.pad(w, 4, mode="edge"), k, mode="valid")


def _runs(on: np.ndarray):
    idx = np.flatnonzero(np.diff(np.concatenate([[0], on.astype(int), [0]])))
    return list(zip(idx[::2], idx[1::2]))


def shade_path(p: np.ndarray, slant: float, pen_mm: float, max_mm: float,
               min_len_mm: float = 1.0, step_mm: float = 0.15) -> np.ndarray:
    """Return `p` with shading passes woven in at every downstroke."""
    if len(p) < 5 or max_mm <= 0:
        return p
    p = g.resample(p, step_mm)
    w = _weights(p, slant)
    spacing = pen_mm * 0.8
    out = []
    pos = 0
    for a, b in _runs(w > 0.25):
        seg, ws = p[a:b], w[a:b]
        if g.length(seg) < min_len_mm:
            continue
        # how many passes this run deserves (even, so we end where we started)
        swell = max_mm * float(ws.max())
        passes = int(np.ceil(swell / spacing))
        passes += passes % 2
        if passes == 0:
            continue
        t = np.linspace(0, np.pi, len(seg))
        taper = np.sin(t) ** 0.7 * ws / max(ws.max(), 1e-9)
        tang = np.gradient(seg, axis=0)
        tang /= np.maximum(np.linalg.norm(tang, axis=1, keepdims=True), 1e-9)
        normal = np.column_stack([tang[:, 1], -tang[:, 0]])  # left of travel
        out.append(p[pos:b])
        for k in range(1, passes + 1):
            off = min(k * spacing, swell) * taper
            q = seg + normal * off[:, None]
            out.append(q[::-1] if k % 2 else q)
        pos = b
    out.append(p[pos:])
    return np.vstack([o for o in out if len(o)])


def shade_paths(paths: list[np.ndarray], slant: float, pen_mm: float, max_mm: float) -> list[np.ndarray]:
    return [shade_path(p, slant, pen_mm, max_mm) for p in paths]
