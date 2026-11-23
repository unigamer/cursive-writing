"""Extract draft single-line glyphs from an outline script font.

    python tools/extract_glyphs.py fonts/PinyonScript-Regular.ttf styles/copperplate \
        --chars abc... [--sheet out.png] [--force]

Existing glyph files are left alone unless --force is given, so hand-tuned
glyphs are never overwritten by accident.
"""

from __future__ import annotations

import argparse
import json
import string
import sys
from pathlib import Path

import freetype
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cursive.extract import extract_glyph, font_slant, font_xheight_units  # noqa: E402
from cursive.glyph import glyph_filename  # noqa: E402

DEFAULT_CHARS = string.ascii_lowercase + string.ascii_uppercase + string.digits + ".,;:!?'-&"


def contact_sheet(glyphs, path, cols=13, cell=180):
    from PIL import Image, ImageDraw

    rows = (len(glyphs) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell, rows * cell), "white")
    d = ImageDraw.Draw(sheet)
    scale = cell / 4.2
    for i, gl in enumerate(glyphs):
        cx, cy = (i % cols) * cell, (i // cols) * cell
        ox, oy = cx + cell * 0.25, cy + cell * 0.62
        d.rectangle([cx, cy, cx + cell - 1, cy + cell - 1], outline=(235, 235, 235))
        d.text((cx + 4, cy + 4), gl["char"], fill=(150, 150, 150))
        for k, st in enumerate(gl["strokes"]):
            p = np.asarray(st["points"])
            pix = [(ox + x * scale, oy - y * scale) for x, y in p]
            n = len(pix)
            for i in range(n - 1):
                t = i / max(n - 2, 1)
                c = (int(40 + 200 * t), int(170 * (1 - t)), 60) if k == 0 else (90, 140, 220)
                d.line([pix[i], pix[i + 1]], fill=c, width=2)
            if k == 0:
                for key, sign in (("lead_in", 1), ("lead_out", -1)):
                    L = gl.get(key, 0)
                    if L:
                        from cursive.geometry import point_at, length
                        q = point_at(p, L if sign > 0 else length(p) - L)
                        x, y = ox + q[0] * scale, oy - q[1] * scale
                        d.rectangle([x - 3, y - 3, x + 3, y + 3], outline=(0, 0, 0))
        d.line([(cx, oy), (cx + cell, oy)], fill=(230, 200, 200))
        d.line([(cx, oy - scale), (cx + cell, oy - scale)], fill=(200, 220, 230))
    sheet.save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("font")
    ap.add_argument("style_dir")
    ap.add_argument("--chars", default=DEFAULT_CHARS)
    ap.add_argument("--variants", default="",
                    help="font glyph names to extract as variants, e.g. 'e.fina b.init g.alt g.ss01=alt2'")
    ap.add_argument("--sheet")
    ap.add_argument("--force", action="store_true", help="re-extract existing glyphs")
    ap.add_argument("--overwrite-edited", action="store_true",
                    help="with --force, also replace glyphs hand-edited in the editor")
    ap.add_argument("--cols", type=int, default=13)
    ap.add_argument("--cell", type=int, default=180)
    args = ap.parse_args()

    face = freetype.Face(args.font)
    xh = font_xheight_units(face)
    slant = font_slant(face, xh)
    print(f"x-height {xh:.0f} units, slant dx/dy {slant:.3f}")
    meta_file = Path(args.style_dir) / "style.json"
    meta = json.loads(meta_file.read_text()) if meta_file.exists() else {"name": Path(args.style_dir).name}
    meta["glyph_slant"] = round(slant, 4)
    meta.setdefault("source_font", Path(args.font).name)
    Path(args.style_dir).mkdir(parents=True, exist_ok=True)
    meta_file.write_text(json.dumps(meta, indent=2) + "\n")
    hints_file = Path(args.style_dir) / "extract_hints.json"
    hints = json.loads(hints_file.read_text()) if hints_file.exists() else {}
    out = Path(args.style_dir) / "glyphs"
    out.mkdir(parents=True, exist_ok=True)
    done = []
    jobs = [(ch, None, glyph_filename(ch), ch) for ch in args.chars]
    # variants: font glyph names such as "e.fina", "b.init", "g.alt", "g.ss01=alt2"
    alt_count: dict[str, int] = {}
    for tok in args.variants.split():
        gname, _, form = tok.partition("=")
        ch = gname.split(".")[0]
        if len(ch) != 1:
            print(f"skip variant {tok!r}: can't tell which character it is")
            continue
        suffix = gname.split(".", 1)[1] if "." in gname else ""
        if not form:
            if "fina" in suffix:
                form = "fina"
            elif "init" in suffix:
                form = "init"
            else:
                alt_count[ch] = alt_count.get(ch, 0) + 1
                form = f"alt{alt_count[ch]}"
        stem = f"{glyph_filename(ch)[:-5]}.{form}"
        jobs.append((ch, gname, stem + ".json", stem))
    for ch, gname, fname, hint_key in jobs:
        f = out / fname
        if f.exists():
            old = json.loads(f.read_text())
            # hand-edited glyphs (saved from the editor) survive --force
            if not args.force or (old.get("edited") and not args.overwrite_edited):
                done.append(old)
                continue
        try:
            gl = extract_glyph(face, ch, xh, slant, hints.get(hint_key), gname)
        except KeyError as e:
            print(f"skip {gname}: {e}")
            continue
        if gl is None:
            print(f"skip {fname}: empty")
            continue
        gl["source"] = Path(args.font).name + (f" [{gname}]" if gname else "")
        f.write_text(json.dumps(gl, indent=1))
        done.append(gl)
        print(f"{fname}: {len(gl['strokes'])} strokes, entry={gl['entry']} exit={gl['exit']}")
    if args.sheet:
        contact_sheet(done, args.sheet, cols=args.cols, cell=args.cell)
        print("sheet:", args.sheet)


if __name__ == "__main__":
    main()
