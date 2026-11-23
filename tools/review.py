"""Review joins in order of how much they matter: how often the pair occurs in
English (tools/corpus.txt) times how weak its join scores.

    python tools/review.py spencerian                  # ranked list
    python tools/review.py spencerian -o review.png    # sheet of example words
    python tools/review.py spencerian --pairs "ft th" -o some.png
"""

from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cursive.glyph import Style  # noqa: E402
from cursive.join import pair_params  # noqa: E402
from cursive.layout import place_word  # noqa: E402
from cursive.pairs import evaluate  # noqa: E402
from cursive.variation import Variation  # noqa: E402

CORPUS = Path(__file__).with_name("corpus.txt")


def corpus_pairs() -> tuple[Counter, dict[str, str]]:
    """Pair counts within words, and an example word for each pair."""
    counts: Counter = Counter()
    example: dict[str, str] = {}
    for w in re.findall(r"[A-Za-z]+", CORPUS.read_text()):
        for a, b in zip(w, w[1:]):
            counts[a + b] += 1
            # prefer short example words
            if a + b not in example or len(w) < len(example[a + b]):
                example[a + b] = w
    return counts, example


def ranked(style: Style):
    counts, example = corpus_pairs()
    total = sum(counts.values())
    rows = []
    for pr, n in counts.items():
        if pr[0] not in style.glyphs or pr[1] not in style.glyphs:
            continue
        a, b = style.glyphs[pr[0]][0], style.glyphs[pr[1]][0]
        prm = pair_params(style, a, b)
        r = evaluate(style, a, b, prm)
        rows.append((pr, n / total, r.score, prm["join"], example[pr], r.parts))
    rows.sort(key=lambda r: -r[1] * r[2])
    return rows


def sheet(style: Style, items: list[tuple[str, str]], path: str, cols: int = 4):
    """Example words, one per pair, drawn at a readable size."""
    var = Variation(style.variation, 0, 0.0)
    scale, cw, ch = 34, 520, 300
    rows = (len(items) + cols - 1) // cols
    img = Image.new("RGB", (cols * cw, rows * ch), "white")
    d = ImageDraw.Draw(img)
    for k, (pr, word) in enumerate(items):
        w, _ = place_word(word, style, var)
        cx, cy = (k % cols) * cw, (k // cols) * ch
        d.rectangle([cx, cy, cx + cw, cy + ch], outline=(225, 225, 225))
        pts = np.vstack(w.paths)
        # slant removed, so a long word still fits its cell
        x0 = float(pts[:, 0].min())
        sc = min(scale, (cw - 30) / max(1e-6, float(pts[:, 0].max()) - x0))
        by = cy + 0.62 * ch
        d.line([(cx, by), (cx + cw, by)], fill=(250, 225, 225))
        for p, kind, gi in w.pieces:
            if len(p) < 2:
                continue
            col = (220, 40, 40) if kind == "conn" else (30, 30, 80)
            d.line([(cx + 15 + (x - x0) * sc, by - y * sc) for x, y in p], fill=col, width=2, joint="curve")
        d.text((cx + 8, cy + 6), f"{pr}  ({word})", fill=(90, 90, 90))
    img.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("style")
    ap.add_argument("-n", type=int, default=40)
    ap.add_argument("--pairs")
    ap.add_argument("-o", "--out")
    args = ap.parse_args()
    style = Style.load(args.style)
    rows = ranked(style)
    if args.pairs:
        _, example = corpus_pairs()
        items = [(p, example.get(p, p)) for p in args.pairs.split()]
    else:
        items = [(r[0], r[4]) for r in rows[: args.n]]
        for pr, f, s, j, w, parts in rows[: args.n]:
            top = ", ".join(f"{k}:{v:.1f}" for k, v in sorted(parts.items(), key=lambda kv: -kv[1])[:3] if v > 0.05)
            print(f"{pr}  freq {100 * f:5.2f}%  score {s:4.2f}  {'join' if j else 'lift'}  {w:<14} {top}")
    if args.out:
        sheet(style, items, args.out)
        print(args.out)


if __name__ == "__main__":
    main()
