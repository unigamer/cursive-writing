"""Optimise and inspect the join of every letter pair in a style.

    python tools/pairs.py optimise spencerian            # writes styles/spencerian/pairs.json
    python tools/pairs.py sheet spencerian -o worst.png  # worst joins, before | after
    python tools/pairs.py sheet spencerian --pairs "Ho ab oa" -o some.png
    python tools/pairs.py stats spencerian

Sheets show each pair twice: left with default join settings, right with the
optimised ones (the score is printed above each). Connectors are red.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import replace
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cursive.glyph import STYLES_DIR, Style  # noqa: E402
from cursive.join import pair_params  # noqa: E402
from cursive.pairs import all_pairs, evaluate, optimise_style, own_letters  # noqa: E402


def draw_pair(d, res, ox, oy, scale, label):
    def pts(p):
        return [(ox + x * scale, oy - y * scale) for x, y in p]
    for p, col in ((res.prev, (40, 60, 160)), (res.nxt, (20, 130, 80)), (res.conn, (220, 40, 40))):
        if len(p) > 1:
            d.line(pts(p), fill=col, width=2, joint="curve")
    d.text((ox - 10, oy - 3.3 * scale), label, fill=(90, 90, 90))


def sheet(style: Style, pairs: list[str], path: str, cols: int = 6, cell=(300, 210)):
    base = replace(style, pairs={})
    rows = (len(pairs) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell[0] * 2, rows * cell[1]), "white")
    d = ImageDraw.Draw(img)
    scale = 38
    for k, pr in enumerate(pairs):
        a, b = style.glyphs[pr[0]][0], style.glyphs[pr[1]][0]
        r0 = evaluate(style, a, b, pair_params(base, a, b))
        r1 = evaluate(style, a, b, pair_params(style, a, b))
        cx, cy = (k % cols) * cell[0] * 2, (k // cols) * cell[1]
        d.rectangle([cx, cy, cx + 2 * cell[0], cy + cell[1]], outline=(225, 225, 225))
        for j, (r, tag) in enumerate(((r0, "default"), (r1, "optimised"))):
            ox = cx + j * cell[0] + 0.3 * cell[0]
            oy = cy + 0.66 * cell[1]
            d.line([(cx + j * cell[0], oy), (cx + (j + 1) * cell[0], oy)], fill=(245, 220, 220))
            top = ", ".join(f"{k}:{v:.1f}" for k, v in sorted(r.parts.items(), key=lambda kv: -kv[1])[:2] if v > 0.05)
            draw_pair(d, r, ox, oy, scale, f"{pr}  {tag} {r.score:.2f}  {top}")
    img.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["optimise", "kern", "sheet", "stats"])
    ap.add_argument("style")
    ap.add_argument("-o", "--out")
    ap.add_argument("--pairs", help="space-separated pairs (default: all / worst)")
    ap.add_argument("--worst", type=int, default=48, help="sheet: show the N worst (by default score)")
    ap.add_argument("--by", choices=["default", "optimised"], default="default")
    ap.add_argument("-j", "--jobs", type=int, default=os.cpu_count() or 1,
                    help="optimise: worker processes (default: one per CPU)")
    ap.add_argument("--capitals", action="store_true",
                    help="optimise: only the pairs that start with a capital")
    args = ap.parse_args()
    style = Style.load(args.style)
    sdir = STYLES_DIR / args.style

    if args.cmd == "optimise":
        pairs = [tuple(p) for p in args.pairs.split()] if args.pairs else all_pairs(style)
        if args.capitals:
            pairs = [p for p in pairs if p[0].isupper()]
        t0 = time.time()

        def progress(k, n, pr, before, after):
            if k % 50 == 0 or k == n:
                print(f"  {k}/{n}  ({time.time() - t0:.0f}s)", flush=True)

        out = optimise_style(replace(style, pairs={}), pairs, progress=progress, workers=args.jobs)
        # hand-tuned pairs ("manual": true in pairs.json) are never overwritten
        f = sdir / "pairs.json"
        old = json.loads(f.read_text()).get("pairs", {}) if f.exists() else {}
        # a full run starts afresh, except for hand-tuned entries; a partial run
        # does the same for its own pairs (an old override may no longer be needed)
        redone = None if not (args.pairs or args.capitals) else {x + y for x, y in pairs}
        old = {k: v for k, v in old.items() if v.get("manual") or (redone is not None and k not in redone)}
        old.update({k: v for k, v in out["pairs"].items() if not old.get(k, {}).get("manual")})
        f.write_text(json.dumps({"note": "per-pair join settings found by tools/pairs.py optimise",
                                 "pairs": dict(sorted(old.items()))}, indent=1))
        rep = out["report"]
        before = np.array([r[1] for r in rep])
        after = np.array([r[2] for r in rep])
        print(f"wrote {f}: {len(out['pairs'])} overrides for {len(rep)} pairs")
        print(f"mean score {before.mean():.2f} -> {after.mean():.2f};  pairs > 2.0: {(before > 2).sum()} -> {(after > 2).sum()}")
        lifts = [r[0] for r in rep if not r[3]["join"] and r[0][0].islower()]
        print("lowercase pairs now left unjoined:", " ".join(lifts) or "none")
        return

    if args.cmd == "kern":
        # proper spacing for every pair that is drawn without a join
        import string

        from cursive.spacing import unjoined_dx

        f = sdir / "pairs.json"
        data = json.loads(f.read_text()) if f.exists() else {"pairs": {}}
        table = data["pairs"]
        lower, upper = own_letters(style)
        letters = lower + upper
        # composed letters (é) share their base letter's entries
        others = [c for c, v in style.glyphs.items() if not c.isalpha() and not v[0].base]
        firsts = letters + others
        seconds = letters + others
        n = 0
        for x in firsts:
            for y in seconds:
                a, b = style.glyphs[x][0], style.glyphs[y][0]
                if pair_params(style, a, b)["join"] or table.get(x + y, {}).get("manual"):
                    continue
                if x in others and y in others and not (x.isdigit() and y.isdigit()):
                    continue  # symbol next to symbol: rare, default spacing will do
                entry = table.setdefault(x + y, {})
                entry["join"] = False
                entry["dx"] = unjoined_dx(style, a, b)
                n += 1
        data["pairs"] = dict(sorted(table.items()))
        f.write_text(json.dumps(data, indent=1))
        print(f"kerned {n} unjoined pairs in {f}")
        return

    base = replace(style, pairs={})
    names = args.pairs.split() if args.pairs else ["".join(p) for p in all_pairs(style)]
    scored = []
    for pr in names:
        a, b = style.glyphs[pr[0]][0], style.glyphs[pr[1]][0]
        s0 = evaluate(style, a, b, pair_params(base, a, b)).score
        s1 = evaluate(style, a, b, pair_params(style, a, b)).score
        scored.append((pr, s0, s1))
    if args.cmd == "stats":
        s0 = np.array([s[1] for s in scored])
        s1 = np.array([s[2] for s in scored])
        print(f"{len(scored)} pairs: mean {s0.mean():.2f} -> {s1.mean():.2f}; >2.0: {(s0 > 2).sum()} -> {(s1 > 2).sum()}; >1.0: {(s0 > 1).sum()} -> {(s1 > 1).sum()}")
        worst = sorted(scored, key=lambda s: -s[2])[:25]
        print("worst now:", " ".join(f"{p}:{s:.1f}" for p, _, s in worst))
        return
    if not args.pairs:
        key = 1 if args.by == "default" else 2
        names = [s[0] for s in sorted(scored, key=lambda s: -s[key])[: args.worst]]
    sheet(style, names, args.out)
    print(args.out)


if __name__ == "__main__":
    main()
