"""How small can each style be plotted with a given pen before letters fill in?

    python tools/legibility.py                       # all styles, table of minimum sizes
    python tools/legibility.py spencerian --letters  # narrowest counters per letter
    python tools/legibility.py spencerian --size 3 --pen 0.5 -o fill.png
                                                     # sample with filled counters in red

Counters (the white inside e, o, a, loops) are measured on words from
tools/corpus.txt drawn as hairlines. A counter of width W x-heights, drawn at
x-height S mm with a pen P mm wide (plus any shading), keeps W*S - P mm of
white. The minimum size is where 95% of counters keep at least half a pen
width of white.
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cursive.glyph import STYLES_DIR, Style  # noqa: E402
from cursive.layout import place_word  # noqa: E402
import json  # noqa: E402

from cursive.legibility import counters, min_size, narrow_width  # noqa: E402
from cursive.variation import Variation  # noqa: E402

CORPUS = Path(__file__).with_name("corpus.txt")
PENS = (0.3, 0.5, 0.7)


def words(limit: int | None = None) -> list[str]:
    ws = list(dict.fromkeys(re.findall(r"[A-Za-z']+", CORPUS.read_text())))
    return ws[:limit] if limit else ws


def measure(style: Style, ws: list[str]):
    var = Variation(style.variation, 0, 0.0)
    out = []  # (word, Word, counters)
    for w in ws:
        word, _ = place_word(w, style, var)
        if word.paths:
            out.append((w, word, counters(word.paths, word.pieces)))
    return out


def sheet(style, measured, size, pen, shade, path, n_words=40):
    """Draw sample words at true pen width; counters that fill in are red."""
    scale = 12  # px per mm
    rows = []
    for w, word, cs in measured[:n_words]:
        rows.append((word, cs))
    lw = max(1, round(pen * scale))
    W, H = 1800, 0
    lines, x, line = [], 0, []
    for word, cs in rows:
        pts = np.vstack(word.paths)
        wpx = (pts[:, 0].max() - pts[:, 0].min()) * size * scale + 40
        if x + wpx > W - 40 and line:
            lines.append(line)
            line, x = [], 0
        line.append((word, cs, x))
        x += wpx
    lines.append(line)
    lh = 4.5 * size * scale
    img = Image.new("RGB", (W, int(lh * len(lines) + 40)), "white")
    d = ImageDraw.Draw(img)
    for r, line in enumerate(lines):
        by = 20 + (r + 0.65) * lh
        for word, cs, x0 in line:
            minx = np.vstack(word.paths)[:, 0].min()

            def px(p):
                return [(20 + x0 + (q[0] - minx) * size * scale, by - q[1] * size * scale) for q in p]

            for p in word.paths:
                if len(p) > 1:
                    d.line(px(p), fill=(20, 20, 60), width=lw + round(shade * scale * 0.5), joint="curve")
            for c in cs:
                if c.is_eye and c.white_mm(size, pen + shade) < 0.5 * pen:
                    (cx, cy), = px([c.centre])
                    rr = max(4, c.width * size * scale)
                    d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=(230, 30, 30), width=2)
    img.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("style", nargs="?")
    ap.add_argument("--letters", action="store_true", help="narrowest counters per letter")
    ap.add_argument("--size", type=float, default=4.0, help="x-height in mm (sheet)")
    ap.add_argument("--pen", type=float, default=0.5, help="pen width in mm")
    ap.add_argument("--shade", type=float, default=0.0, help="extra downstroke width from --shade, mm")
    ap.add_argument("--words", type=int, default=None, help="use only the first N corpus words")
    ap.add_argument("--save", action="store_true", help="store the counter width in style.json (the CLI warns from it)")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()
    names = [args.style] if args.style else sorted(p.name for p in STYLES_DIR.iterdir() if (p / "style.json").exists())
    ws = words(args.words)
    print(f"{len(ws)} words; minimum x-height (mm) so 95% of counters keep half a pen width of white")
    print(f"{'style':<13}" + "".join(f"pen {p:.1f}  " for p in PENS) + " counters  median width")
    for name in names:
        style = Style.load(name)
        m = measure(style, ws)
        widths = np.array([c.width for _, _, cs in m for c in cs if c.is_eye])
        sizes = "".join(f"{min_size(widths, p + args.shade):7.1f}   " for p in PENS)
        print(f"{name:<13}{sizes}{len(widths):8d}   {np.median(widths):.2f} xh")
        if args.save:
            f = STYLES_DIR / name / "style.json"
            meta = json.loads(f.read_text())
            meta["counter_width"] = round(narrow_width(widths), 3)
            f.write_text(json.dumps(meta, indent=2) + "\n")
        if args.letters:
            per = defaultdict(list)
            for w, word, cs in m:
                for c in cs:
                    if c.is_eye and 0 <= c.glyph < len(w.replace("'", "")) + 1:
                        ch = [ch for ch in w if ch in style.glyphs or ch.isalpha()][c.glyph] \
                            if c.glyph < len(w) else "?"
                        per[ch].append(c.width)
            worst = sorted(per.items(), key=lambda kv: np.quantile(kv[1], 0.1))
            print("  narrowest counters (10th percentile width, x-heights):")
            print("  " + "  ".join(f"{k}:{np.quantile(v, 0.1):.2f}" for k, v in worst[:20]))
        if args.out:
            sheet(style, m, args.size, args.pen, args.shade, args.out)
            print(args.out)


if __name__ == "__main__":
    main()
