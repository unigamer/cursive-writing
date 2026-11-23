"""Quality-check sheets.

    python tools/sheets.py word copperplate "minimum" -o word.png
    python tools/sheets.py bigrams copperplate -o bigrams.png [--chars abc...]
    python tools/sheets.py glyphs copperplate -o glyphs.png

In `word` mode each glyph's own ink is drawn in alternating blue/green and
connector curves in red, so bad joins stand out.
"""

from __future__ import annotations

import argparse
import string
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cursive import geometry as g  # noqa: E402
from cursive.glyph import Style  # noqa: E402
from cursive.join import cut_end, cut_start  # noqa: E402
from cursive.layout import place_word  # noqa: E402
from cursive.variation import Variation  # noqa: E402


def debug_word(style: Style, text: str):
    """[(polyline, kind)] for one word with no variation: kinds are
    'glyph0'/'glyph1' (alternating letters), 'conn' and 'deferred'."""
    word, _ = place_word(text, style, Variation(style.variation, 0, 0.0))
    return [(p, f"glyph{i % 2}" if kind == "glyph" else kind) for p, kind, i in word.pieces]


COLORS = {"glyph0": (30, 60, 170), "glyph1": (20, 140, 80), "conn": (220, 30, 30),
          "deferred": (150, 150, 150)}


def draw_items(d: ImageDraw.ImageDraw, items, scale, ox, oy, width=2):
    for p, kind in items:
        pix = [(ox + px * scale, oy - py * scale) for px, py in p]
        if len(pix) > 1:
            d.line(pix, fill=COLORS[kind], width=width, joint="curve")


def word_sheet(style, texts, path, scale=90):
    rows = []
    for t in texts:
        items = debug_word(style, t)
        allp = np.vstack([p for p, _ in items])
        rows.append((items, allp.min(axis=0), allp.max(axis=0)))
    W = int(max(hi[0] - lo[0] for _, lo, hi in rows) * scale + 60)
    H = int(sum((hi[1] - lo[1]) * scale + 40 for _, lo, hi in rows))
    img = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(img)
    y = 20
    for items, lo, hi in rows:
        oy = y + hi[1] * scale
        ox = 30 - lo[0] * scale
        d.line([(0, oy), (W, oy)], fill=(240, 220, 220))
        d.line([(0, oy - scale), (W, oy - scale)], fill=(215, 230, 240))
        draw_items(d, items, scale, ox, oy)
        y += (hi[1] - lo[1]) * scale + 40
    img.save(path)


def bigram_sheet(style, chars, path, cell=150):
    n = len(chars)
    img = Image.new("RGB", ((n + 1) * cell, (n + 1) * cell), "white")
    d = ImageDraw.Draw(img)
    scale = cell / 5.0
    for i, a in enumerate(chars):
        d.text((cell // 2, (i + 1) * cell + cell // 2), a, fill=(0, 0, 0))
        d.text(((i + 1) * cell + cell // 2, cell // 2), a, fill=(0, 0, 0))
        for j, b in enumerate(chars):
            cx, cy = (j + 1) * cell, (i + 1) * cell
            d.rectangle([cx, cy, cx + cell, cy + cell], outline=(235, 235, 235))
            items = debug_word(style, a + b)
            if not items:
                continue
            allp = np.vstack([p for p, _ in items])
            ox = cx + cell / 2 - (allp[:, 0].min() + allp[:, 0].max()) / 2 * scale
            oy = cy + cell * 0.62
            draw_items(d, items, scale, ox, oy, width=1)
    img.save(path)


def glyph_sheet(style, path, chars=None, cols=10, cell=200):
    """Every glyph (or just `chars`) scaled to fit its cell. Main stroke blue,
    lead-in/out red, start point green, deferred strokes grey."""
    chars = [c for c in (chars or style.glyphs) if c in style.glyphs]
    rows = (len(chars) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell, rows * cell), "white")
    d = ImageDraw.Draw(img)
    allp = np.vstack([s.points for c in chars for s in style.glyphs[c][0].strokes])
    lo, hi = allp.min(axis=0), allp.max(axis=0)
    xspan = max(np.ptp(np.vstack([s.points for s in style.glyphs[c][0].strokes])[:, 0]) for c in chars)
    scale = 0.86 * cell / max(hi[1] - lo[1], xspan)
    for k, ch in enumerate(chars):
        gl = style.glyphs[ch][0]
        cx, cy = (k % cols) * cell, (k // cols) * cell
        gp = np.vstack([s.points for s in gl.strokes])
        ox = cx + cell / 2 - (gp[:, 0].min() + gp[:, 0].max()) / 2 * scale
        oy = cy + 0.07 * cell + hi[1] * scale
        d.rectangle([cx, cy, cx + cell, cy + cell], outline=(235, 235, 235))
        d.line([(cx, oy), (cx + cell, oy)], fill=(245, 215, 215))
        d.line([(cx, oy - scale), (cx + cell, oy - scale)], fill=(215, 228, 245))
        d.text((cx + 4, cy + 4), f"{ch} {gl.entry}/{gl.exit}", fill=(140, 140, 140))
        p = gl.main.points
        L = g.length(p)
        lead = cut_end(p, L - gl.lead_in) if gl.lead_in else p[:1]
        tail = cut_start(p, L - gl.lead_out) if gl.lead_out else p[-1:]
        items = [(p, "glyph0"), (lead, "conn"), (tail, "conn")]
        items += [(s.points, "deferred") for s in gl.deferred]
        draw_items(d, items, scale, ox, oy)
        sx, sy = ox + p[0, 0] * scale, oy - p[0, 1] * scale
        d.ellipse([sx - 3, sy - 3, sx + 3, sy + 3], fill=(0, 170, 0))
    img.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=["word", "bigrams", "glyphs"])
    ap.add_argument("style")
    ap.add_argument("text", nargs="*")
    ap.add_argument("--chars", default=string.ascii_lowercase)
    ap.add_argument("--all", action="store_true", help="glyphs mode: every glyph in the style")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()
    style = Style.load(args.style)
    if args.mode == "word":
        word_sheet(style, [w for t in args.text for w in t.split()], args.out)
    elif args.mode == "bigrams":
        bigram_sheet(style, args.chars, args.out)
    else:
        glyph_sheet(style, args.out, None if args.all else args.chars)
    print(args.out)


if __name__ == "__main__":
    main()
