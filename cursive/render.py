"""SVG output for pen plotters (Inkscape compatible)."""

from __future__ import annotations

from html import escape

import numpy as np

from . import geometry as g
from .layout import Line

PAGES_MM = {
    "a3": (297, 420), "a4": (210, 297), "a5": (148, 210), "a6": (105, 148),
    "letter": (215.9, 279.4), "dl": (220, 110), "c5": (229, 162),
}


def page_size(spec: str) -> tuple[float, float]:
    """'a4', 'a4-landscape' or 'WxH' in mm."""
    s = spec.lower()
    land = s.endswith("-landscape")
    s = s.removesuffix("-landscape")
    if s in PAGES_MM:
        w, h = PAGES_MM[s]
    else:
        w, h = (float(v) for v in s.split("x"))
    return (h, w) if land else (w, h)


def lines_to_mm(lines: list[Line], xh_mm: float, origin_mm: tuple[float, float]) -> list[list[np.ndarray]]:
    """Convert x-height units (y up) into page millimetres (y down)."""
    ox, oy = origin_mm
    out = []
    for ln in lines:
        paths = []
        for p in ln.paths:
            q = np.column_stack([ox + p[:, 0] * xh_mm, oy - p[:, 1] * xh_mm])
            paths.append(q)
        out.append(paths)
    return out


def path_d(p: np.ndarray, eps_mm: float = 0.02) -> str:
    q = g.rdp(p, eps_mm) if len(p) > 2 else p
    if len(q) == 1:
        q = np.vstack([q, q + [0.05, 0]])
    pts = " ".join(f"{x:.3f},{y:.3f}" for x, y in q)
    return f"M {pts.split(' ', 1)[0]} L {pts.split(' ', 1)[1]}" if len(q) > 1 else f"M {pts}"


def to_svg(mm_lines: list[list[np.ndarray]], page_mm: tuple[float, float],
           stroke_mm: float = 0.35, title: str = "cursive") -> str:
    w, h = page_mm
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" '
        f'width="{w}mm" height="{h}mm" viewBox="0 0 {w} {h}">',
        f"<title>{escape(title, quote=False)}</title>",
        '<g inkscape:groupmode="layer" inkscape:label="1 cursive" '
        f'fill="none" stroke="black" stroke-width="{stroke_mm}" '
        'stroke-linecap="round" stroke-linejoin="round">',
    ]
    for i, paths in enumerate(mm_lines):
        out.append(f'<g id="line{i + 1}">')
        for p in paths:
            out.append(f'<path d="{path_d(p)}"/>')
        out.append("</g>")
    out += ["</g>", "</svg>"]
    return "\n".join(out)


def stats(mm_lines) -> dict:
    """Pen-down length, pen-up travel and path count, for a quick sanity check."""
    down = up = 0.0
    n = 0
    last = None
    for paths in mm_lines:
        for p in paths:
            down += g.length(p)
            if last is not None:
                up += float(np.linalg.norm(p[0] - last))
            last = p[-1]
            n += 1
    return {"paths": n, "pen_down_mm": round(down, 1), "pen_up_mm": round(up, 1)}
