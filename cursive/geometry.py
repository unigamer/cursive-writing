"""Polyline geometry helpers. A polyline is an (N, 2) float array, y up."""

from __future__ import annotations

import numpy as np


def as_array(points) -> np.ndarray:
    return np.asarray(points, dtype=float).reshape(-1, 2)


def arc_lengths(p: np.ndarray) -> np.ndarray:
    if len(p) < 2:
        return np.zeros(len(p))
    seg = np.linalg.norm(np.diff(p, axis=0), axis=1)
    return np.concatenate([[0.0], np.cumsum(seg)])


def length(p: np.ndarray) -> float:
    return float(arc_lengths(p)[-1]) if len(p) > 1 else 0.0


def resample(p: np.ndarray, step: float) -> np.ndarray:
    """Resample a polyline at (roughly) uniform arc-length spacing."""
    p = as_array(p)
    if len(p) < 2:
        return p.copy()
    s = arc_lengths(p)
    total = s[-1]
    if total == 0:
        return p[:1].copy()
    n = max(2, int(np.ceil(total / step)) + 1)
    t = np.linspace(0, total, n)
    return np.column_stack([np.interp(t, s, p[:, 0]), np.interp(t, s, p[:, 1])])


def smooth(p: np.ndarray, iterations: int = 2, keep_ends: bool = True) -> np.ndarray:
    """Laplacian smoothing that keeps endpoints fixed."""
    p = as_array(p).copy()
    if len(p) < 3:
        return p
    for _ in range(iterations):
        q = p.copy()
        q[1:-1] = 0.25 * p[:-2] + 0.5 * p[1:-1] + 0.25 * p[2:]
        if not keep_ends:
            q[0], q[-1] = p[0], p[-1]
        p = q
    return p


def rdp(p: np.ndarray, eps: float) -> np.ndarray:
    """Ramer-Douglas-Peucker simplification."""
    p = as_array(p)
    if len(p) < 3:
        return p.copy()
    keep = np.zeros(len(p), dtype=bool)
    keep[0] = keep[-1] = True
    stack = [(0, len(p) - 1)]
    while stack:
        i, j = stack.pop()
        if j <= i + 1:
            continue
        a, b = p[i], p[j]
        ab = b - a
        n = np.linalg.norm(ab)
        seg = p[i + 1 : j]
        if n == 0:
            d = np.linalg.norm(seg - a, axis=1)
        else:
            w = seg - a
            d = np.abs(ab[0] * w[:, 1] - ab[1] * w[:, 0]) / n
        k = int(np.argmax(d))
        if d[k] > eps:
            m = i + 1 + k
            keep[m] = True
            stack.append((i, m))
            stack.append((m, j))
    return p[keep]


def catmull_rom(p: np.ndarray, samples_per_seg: int = 8) -> np.ndarray:
    """Dense smooth curve through the given points (centripetal-ish, uniform)."""
    p = as_array(p)
    if len(p) < 3:
        return p.copy()
    ext = np.vstack([2 * p[0] - p[1], p, 2 * p[-1] - p[-2]])
    out = [p[:1]]
    t = np.linspace(0, 1, samples_per_seg + 1)[1:, None]
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        t2, t3 = t * t, t * t * t
        seg = 0.5 * (
            (2 * p1)
            + (-p0 + p2) * t
            + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2
            + (-p0 + 3 * p1 - 3 * p2 + p3) * t3
        )
        out.append(seg)
    return np.vstack(out)


def unit(v) -> np.ndarray:
    v = np.asarray(v, dtype=float)
    n = np.linalg.norm(v)
    return v / n if n > 1e-12 else np.zeros_like(v)


def start_tangent(p: np.ndarray, dist: float) -> np.ndarray:
    """Direction of travel at the start, measured over `dist` of arc length."""
    return unit(point_at(p, dist) - p[0])


def end_tangent(p: np.ndarray, dist: float) -> np.ndarray:
    """Direction of travel at the end, measured over `dist` of arc length."""
    return unit(p[-1] - point_at(p, length(p) - dist))


def point_at(p: np.ndarray, s: float) -> np.ndarray:
    p = as_array(p)
    a = arc_lengths(p)
    s = float(np.clip(s, 0, a[-1] if len(a) else 0))
    return np.array([np.interp(s, a, p[:, 0]), np.interp(s, a, p[:, 1])])


def cubic_bezier(p0, p1, p2, p3, n: int = 32) -> np.ndarray:
    t = np.linspace(0, 1, n)[:, None]
    mt = 1 - t
    return mt**3 * p0 + 3 * mt**2 * t * p1 + 3 * mt * t**2 * p2 + t**3 * p3


def hermite(p0, t0, p1, t1, tension: float = 0.45, n: int = 32, h1: float | None = None) -> np.ndarray:
    """Cubic curve from p0 leaving along unit t0 to p1 arriving along unit t1.

    Handle lengths scale with the chord so the curve stays well-behaved;
    `h1` overrides the arrival handle length.
    """
    p0, p1 = np.asarray(p0, float), np.asarray(p1, float)
    chord = np.linalg.norm(p1 - p0)
    h = tension * chord
    return cubic_bezier(p0, p0 + unit(t0) * h, p1 - unit(t1) * (h if h1 is None else h1), p1, n)


def turn_angle(d_in, d_out) -> float:
    """Unsigned angle (radians) between two directions."""
    a, b = unit(d_in), unit(d_out)
    return float(np.arccos(np.clip(np.dot(a, b), -1, 1)))
