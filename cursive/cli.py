"""Command line: text -> plotter-ready joined cursive SVG.

    python -m cursive.cli "Dear Alice," --style copperplate --size 7 \
        --page a5 --margin 15 --seed 3 -o card.svg --png card.png
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from .glyph import STYLES_DIR, Style
from .layout import layout
from .render import lines_to_mm, page_size, stats, to_svg


def main(argv=None):
    styles = sorted(p.name for p in STYLES_DIR.iterdir() if (p / "glyphs").is_dir()) if STYLES_DIR.exists() else []
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("text", help="text to write; use '-' to read stdin")
    ap.add_argument("--style", default=styles[0] if styles else None, help=f"one of {styles} or a path")
    ap.add_argument("--size", type=float, default=6.0, help="x-height in mm (default 6)")
    ap.add_argument("--page", default="a4", help="a4, a5, a4-landscape, letter, or WxH in mm")
    ap.add_argument("--margin", type=float, default=20.0, help="page margin in mm")
    ap.add_argument("--align", choices=["left", "center", "right"], default="left")
    ap.add_argument("--seed", type=int, default=0, help="random seed for variation")
    ap.add_argument("--variation", type=float, default=1.0, help="variation multiplier (0 = none)")
    ap.add_argument("--pen", type=float, default=0.35, help="preview stroke width in mm")
    ap.add_argument("--shade", type=float, default=0.0,
                    help="faux pointed-pen shading: max extra width of downstrokes in mm (e.g. 0.6)")
    ap.add_argument("-o", "--out", default="out.svg")
    ap.add_argument("--png", help="also write a PNG preview")
    args = ap.parse_args(argv)

    text = sys.stdin.read() if args.text == "-" else args.text.replace("\\n", "\n")
    style = Style.load(args.style)
    pw, ph = page_size(args.page)
    lines, mm = make_page(text, style, size=args.size, page=(pw, ph), margin=args.margin, align=args.align,
                          seed=args.seed, variation=args.variation, pen=args.pen, shade=args.shade)
    Path(args.out).write_text(to_svg(mm, (pw, ph), args.pen, title=text[:60]))
    s = stats(mm)
    bottom = max((float(p[:, 1].max()) for paths in mm for p in paths), default=0)
    if style.counter_width:
        from .legibility import min_size_for

        need = min_size_for(style.counter_width, args.pen + args.shade)
        if args.size < need:
            print(f"warning: at {args.size}mm with a {args.pen}mm pen"
                  + (f" and {args.shade}mm shading" if args.shade else "")
                  + f", loops and letter eyes will fill in; use --size {need:.1f} or more",
                  file=sys.stderr)
    if bottom > ph - args.margin:
        print(f"warning: text runs past the bottom margin ({bottom:.0f}mm of {ph}mm)", file=sys.stderr)
    print(f"{args.out}: {len(lines)} lines, {s['paths']} pen strokes, "
          f"{s['pen_down_mm'] / 1000:.2f} m drawn")
    if args.png:
        save_png(mm, (pw, ph), args.png)


def make_page(text, style, size=6.0, page=(210, 297), margin=20.0, align="left", seed=0,
              variation=1.0, pen=0.35, shade=0.0):
    """Lay out `text` on a page; returns (lines, paths in page mm per line).
    The web page (web/cursive/index.js) does the same, step for step."""
    pw, ph = page
    width_xh = (pw - 2 * margin) / size
    lines = layout(text, style, width=width_xh, seed=seed, amount=variation, align=align)
    # put the tallest ink of the first line exactly on the top margin
    first_top = max((float(p[:, 1].max()) for p in lines[0].paths), default=2.0) if lines else 2.0
    top = margin + first_top * size
    mm = lines_to_mm(lines, size, (margin, top))
    if shade > 0:
        from .shade import shade_paths
        # shading passes are woven into each stroke, so they add no pen lifts
        mm = [shade_paths(paths, style.glyph_slant, pen, shade) for paths in mm]
    return lines, mm


def save_png(mm_lines, page_mm, path, dpi=150, pen_mm=0.35):
    from PIL import Image, ImageDraw

    k = dpi / 25.4
    img = Image.new("RGB", (int(page_mm[0] * k), int(page_mm[1] * k)), "white")
    d = ImageDraw.Draw(img)
    wpx = max(1, int(round(pen_mm * k)))
    for paths in mm_lines:
        for p in paths:
            pts = [tuple(v) for v in (np.asarray(p) * k)]
            if len(pts) > 1:
                d.line(pts, fill=(25, 25, 60), width=wpx, joint="curve")
    img.save(path)


if __name__ == "__main__":
    main()
