"""Add accented letters to a style, composed from its own base letters.

    python tools/compose_glyphs.py copperplate [--sheet accents.png]
    python tools/compose_glyphs.py copperplate --remark "éÉ"   # re-trace these marks

1. Accent marks are traced from the style's source font into
   styles/<style>/marks.json: the accented glyph is rendered, the plain base
   glyph is subtracted, and what is left is traced like any glyph. Existing
   marks are kept (edit marks.json by hand to move one) unless named with
   --remark. The slash of ø/Ø is drawn straight through the body instead.
2. Every variant and positional form of each base letter (e, e.alt1, e.fina…)
   gets an accented copy: é, é.alt1, é.fina… (cursive/compose.py). Composed
   files are regenerated on every run (except ones hand-edited in the glyph
   editor), so re-run after editing a base letter; tests/test_compose.py
   fails while any is stale.

Then re-run tools/build_web.py.
"""

from __future__ import annotations

import argparse
import json
import sys
import unicodedata
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cursive.compose import ACCENTED, SLASHED, anchor, base_of, compose, slash_mark  # noqa: E402
from cursive.glyph import STYLES_DIR, glyph_name  # noqa: E402

FONTS = Path(__file__).resolve().parents[1] / "fonts"
MIN_MARK_PX = 150  # smaller left-overs of the subtraction are rendering noise
HUG_PX = 0.12 * 220  # ...as are pieces that never get further than this from the letter (XH_PX = 220)


def _place(src: np.ndarray, shape, dr: int, dc: int) -> np.ndarray:
    out = np.zeros(shape, bool)
    H, W = src.shape
    r0, c0, rr0, cc0 = max(dr, 0), max(dc, 0), max(-dr, 0), max(-dc, 0)
    h, w = min(H - rr0, shape[0] - r0), min(W - cc0, shape[1] - c0)
    if h > 0 and w > 0:
        out[r0:r0 + h, c0:c0 + w] = src[rr0:rr0 + h, cc0:cc0 + w]
    return out


def trace_marks(face, ch: str, xh: float, slant: float) -> tuple[list[dict], float]:
    """Marks of accented `ch` in the font's frame, and the anchor of the
    font's own base letter in that frame."""
    from scipy import ndimage

    from cursive.extract import XH_PX, extract_glyph, extract_image, render

    base = base_of(ch)
    plain = "ı" if base == "i" else base  # accented i's are built on the dotless i
    ia, ra, ca, adv, _ = render(face, ch, xh)
    ib, rb, cb, _, _ = render(face, plain, xh)
    plain_ink = _place(ib, ia.shape, ra - rb, ca - cb)
    left = ia & ~ndimage.binary_dilation(plain_ink, iterations=3)  # margin for anti-aliasing differences
    lab, n = ndimage.label(left)
    keep = np.zeros_like(left)
    # how far each pixel is from the letter: a real mark reaches well away from
    # it, while left-overs of a letter drawn slightly differently hug it
    away = ndimage.distance_transform_edt(~plain_ink)
    for k in range(1, n + 1):
        part = lab == k
        if part.sum() >= MIN_MARK_PX and away[part].max() > HUG_PX:
            keep |= part
    # grow the marks back over that margin (not into the letter itself), so an
    # accent that runs alongside the letter, like a cedilla, stays in one piece
    keep = ndimage.binary_dilation(keep, iterations=4, mask=ia & ~plain_ink)
    if not keep.any():
        raise ValueError(f"no accent found for {ch!r}")
    marks = unicodedata.normalize("NFD", ch)[1:]
    dotted, ring = "\u0308" in marks, "\u030a" in marks
    strokes = []
    parts, n = ndimage.label(keep)
    for k in range(1, n + 1):
        part = parts == k
        rows, cols = np.nonzero(part)
        xy = np.column_stack([(cols - ca) / XH_PX, (ra - rows) / XH_PX])
        traced = extract_image(part, ra, ca, adv, ch, slant)["strokes"]
        if dotted or any(t["kind"] == "line" for t in traced):
            strokes += [{"points": t["points"], "kind": t["kind"]} for t in traced]
        elif ring:  # too small to trace: draw the ring as a circle
            c, r = xy.mean(axis=0), 0.5 * np.ptp(xy, axis=0).mean()
            t = np.linspace(0, 2 * np.pi, 25)
            strokes.append({"points": np.round(c + r * np.column_stack([np.cos(t), np.sin(t)]), 4).tolist(),
                            "kind": "line"})
        else:  # a short dash (an acute or grave too small to trace): a line along its long axis
            c = xy.mean(axis=0)
            axis = np.linalg.svd(xy - c, full_matrices=False)[2][0]
            t = (xy - c) @ axis
            ends = c + np.outer([t.min(), t.max()], axis)
            if ends[0, 0] > ends[1, 0]:
                ends = ends[::-1]
            strokes.append({"points": np.round(ends, 4).tolist(), "kind": "line"})
    # only a diaeresis is made of dots; elsewhere a dot is a scrap of a line
    # mark cut off where it crosses the letter (a cedilla under a C's tail)
    if not dotted and any(s["kind"] == "line" for s in strokes):
        strokes = [s for s in strokes if s["kind"] == "line"]
    fbase = extract_glyph(face, plain, xh, slant)
    return strokes, anchor(fbase["strokes"][0]["points"], slant, ch.isupper())


def base_files(gdir: Path, base: str) -> list[Path]:
    """The base letter's glyph file and every variant / form of it."""
    name = glyph_name(base)
    return sorted(f for f in gdir.glob(f"{name}*.json") if f.stem == name or f.stem.startswith(name + "."))


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("style")
    ap.add_argument("--chars", default=ACCENTED, help="accented letters to add (default: all)")
    ap.add_argument("--remark", default="", help="re-trace the marks of these letters from the font")
    ap.add_argument("--sheet", help="draw the composed letters to this PNG")
    args = ap.parse_args()

    sdir = STYLES_DIR / args.style
    meta = json.loads((sdir / "style.json").read_text())
    slant = float(meta.get("glyph_slant", 0.0))
    gdir = sdir / "glyphs"
    mfile = sdir / "marks.json"
    marks = json.loads(mfile.read_text())["marks"] if mfile.exists() else {}

    todo = [c for c in args.chars if c not in marks or c in args.remark]
    if todo:
        import freetype

        from cursive.extract import font_xheight_units

        face = freetype.Face(str(FONTS / meta["source_font"].split(" ")[0]))
        xh = font_xheight_units(face)
        for ch in todo:
            base = base_of(ch)
            main = json.loads((gdir / f"{glyph_name(base)}.json").read_text())
            if ch in SLASHED:
                strokes, anc = slash_mark(main, slant, ch.isupper()), anchor(main["strokes"][0]["points"], slant,
                                                                              ch.isupper())
                src = "drawn: a slash through the body"
            else:
                strokes, anc = trace_marks(face, ch, xh, slant)
                src = f"{face.family_name.decode()} [U+{ord(ch):04X}]"
            marks[ch] = {"base": base, "anchor": round(anc, 4), "source": src, "strokes": strokes}
            print(f"mark {ch}: {len(strokes)} stroke(s) from {src}")
        mfile.write_text(json.dumps({
            "note": "accent marks for composed letters (tools/compose_glyphs.py); points in the base letter's frame",
            "marks": dict(sorted(marks.items())),
        }, indent=1, ensure_ascii=False) + "\n")

    written = []
    for ch in args.chars:
        mark = marks[ch]
        for f in base_files(gdir, mark["base"]):
            suffix = f.stem[len(glyph_name(mark["base"])):]  # "", ".alt1", ".fina"…
            out = gdir / f"{glyph_name(ch)}{suffix}.json"
            if out.exists() and json.loads(out.read_text()).get("edited"):
                print(f"keep {out.name}: hand-edited in the glyph editor")
                continue
            gl = compose(ch, json.loads(f.read_text()), mark, slant)
            out.write_text(json.dumps(gl, indent=1, ensure_ascii=False))
            written.append((gl, len(mark["strokes"])))
    print(f"wrote {len(written)} composed glyph files in {gdir}")
    if args.sheet:
        draw_sheet(written, args.sheet)
        print("sheet:", args.sheet)


def draw_sheet(items: list[tuple[dict, int]], path: str, cols: int = 12, cell: int = 200):
    """Each (glyph, number of marks) scaled to its cell: base in ink, marks in red."""
    from PIL import Image, ImageDraw

    rows = (len(items) + cols - 1) // cols
    img = Image.new("RGB", (cols * cell, rows * cell), "white")
    d = ImageDraw.Draw(img)
    for i, (gl, n_marks) in enumerate(items):
        cx, cy = (i % cols) * cell, (i // cols) * cell
        pts = np.vstack([np.asarray(s["points"]) for s in gl["strokes"]])
        lo, hi = pts.min(axis=0), pts.max(axis=0)
        sc = 0.8 * cell / max(hi[0] - lo[0], hi[1] - lo[1], 1.0)
        ox = cx + (cell - (hi[0] - lo[0]) * sc) / 2 - lo[0] * sc
        oy = cy + (cell + (hi[1] - lo[1]) * sc) / 2 + lo[1] * sc
        d.line([(cx, oy), (cx + cell, oy)], fill=(240, 220, 220))
        d.line([(cx, oy - sc), (cx + cell, oy - sc)], fill=(220, 230, 240))
        first_mark = len(gl["strokes"]) - n_marks
        for k, s in enumerate(gl["strokes"]):
            p = [(ox + x * sc, oy - y * sc) for x, y in s["points"]]
            if len(p) > 1:
                d.line(p, fill=(220, 40, 40) if k >= first_mark else (30, 30, 60), width=2)
        d.rectangle([cx, cy, cx + cell - 1, cy + cell - 1], outline=(225, 225, 225))
        d.text((cx + 4, cy + 4), gl["char"], fill=(120, 120, 120))
    img.save(path)


if __name__ == "__main__":
    main()
