"""Render the sample images used in README.md into docs/images/.

    python tools/readme_images.py

Each image is cropped to its ink, so the README can lay them out in tables.
Re-run after glyph, join or style changes to keep the README current.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cursive.cli import make_page  # noqa: E402
from cursive.glyph import Style  # noqa: E402

sys.path.insert(0, str(ROOT / "tools"))
from sheets import COLORS, debug_word  # noqa: E402

OUT = ROOT / "docs" / "images"
INK = (25, 25, 60)
STYLES = ["copperplate", "spencerian", "modern", "formal"]


def render(text, style, path, size=5.0, width=1000.0, dpi=150, pen=0.35, pad=4.0, **kw):
    """Write `text` with the CLI's own layout and save a PNG cropped to the ink."""
    st = Style.load(style)
    _, mm = make_page(text, st, size=size, page=(width, 1000), margin=pad, pen=pen, **kw)
    pts = np.vstack([p for paths in mm for p in paths])
    lo, hi = pts.min(axis=0) - pad, pts.max(axis=0) + pad
    k = dpi / 25.4
    img = Image.new("RGB", (int((hi[0] - lo[0]) * k), int((hi[1] - lo[1]) * k)), "white")
    d = ImageDraw.Draw(img)
    w = max(1, round(pen * k))
    for paths in mm:
        for p in paths:
            q = [tuple(v) for v in (np.asarray(p) - lo) * k]
            if len(q) > 1:
                d.line(q, fill=INK, width=w, joint="curve")
    img.save(path, optimize=True)
    print(path.relative_to(ROOT), img.size)


def joins(style, text, path, scale=70, pad=20):
    """One word, no variation: letters alternate blue/green, connectors red."""
    items = debug_word(Style.load(style), text)
    pts = np.vstack([p for p, _ in items])
    lo, hi = pts.min(axis=0), pts.max(axis=0)
    img = Image.new("RGB", (int((hi[0] - lo[0]) * scale + 2 * pad), int((hi[1] - lo[1]) * scale + 2 * pad)), "white")
    d = ImageDraw.Draw(img)
    for p, kind in items:
        q = [(pad + (x - lo[0]) * scale, pad + (hi[1] - y) * scale) for x, y in p]
        if len(q) > 1:
            d.line(q, fill=COLORS[kind], width=3, joint="curve")
    img.save(path, optimize=True)
    print(path.relative_to(ROOT), img.size)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    card = "Dear Margaret,\nThank you for the lovely flowers.\nWarmest wishes, Oliver"
    render(card, "copperplate", OUT / "hero.png", size=6, seed=3, shade=0.5)
    for s in STYLES:
        render(card, s, OUT / f"style-{s}.png", seed=3)
    for v in (0, 1, 2):
        render("minimum minimum", "copperplate", OUT / f"variation-{v}.png", size=7, variation=v, seed=1)
    for seed in (1, 2, 3):
        render("Hello there, Lucy", "spencerian", OUT / f"seed-{seed}.png", seed=seed)
    for shade in (0, 0.6):
        render("Many happy returns", "copperplate", OUT / f"shade-{shade}.png", size=8, seed=2, shade=shade)
    for size in (4, 8):
        render("A tiny note", "modern", OUT / f"size-{size}.png", size=size, seed=1)
    joins("copperplate", "handwriting", OUT / "joins.png")


if __name__ == "__main__":
    main()
