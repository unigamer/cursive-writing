"""Visual regression snapshots: a fixed set of cards per style, checked into
tests/snapshots/, so any change to glyphs, pairs or the engine that moves ink
shows up as a failing check, with pictures of what moved.

    python tools/snapshots.py                  # list changed cards; exit 1 if any
    python tools/snapshots.py --diff diffs/    # also draw before | after | overlay PNGs
    python tools/snapshots.py --update         # write the current output as the snapshots
    python tools/snapshots.py --update --only copperplate-card

Cards are compared as geometry, not bytes: the same number of pen strokes, and
every stroke within TOLERANCE mm of the stored one
(same start, same end, and no ink further than that from the other's). Small floating-point
differences between machines or numpy versions therefore don't fail the check;
a moved join, a changed glyph or an extra pen lift does.

Changes are for review, not failures. In CI (.github/workflows/ci.yml) changed
cards are listed in the job summary and their PNGs uploaded as an artifact; on
a pull request the PNGs are also pushed to the `snapshot-diffs` branch and
posted in a comment (`--report`) that later runs update in place. Merging to
main accepts the changes: CI runs --update there and commits the result, so
--update is rarely needed by hand.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cursive import geometry as g  # noqa: E402
from cursive.cli import make_page  # noqa: E402
from cursive.glyph import Style  # noqa: E402
from cursive.render import page_size, to_svg  # noqa: E402

SNAP_DIR = ROOT / "tests" / "snapshots"
TOLERANCE = 0.05  # mm: the most any stroke may move before the card counts as changed
STYLES = ["copperplate", "spencerian", "modern", "formal", "signature", "flowing", "roundhand"]

# Three cards per style:
#  card   - ordinary use: variation, shading, mixed text
#  plain  - variation 0: every lowercase pair family and the capitals, so a
#           glyph or join change shows up without random jitter in the way
#  center - centred place cards: short lines of different lengths with big
#           swash capitals and long exit strokes, which are what pushed
#           centred text off centre when alignment used the advance width
CARD = ("Dear Margaret,\nThank you for the lovely flowers; the little old-fashioned garden\n"
        "looks wonderful. Café at 10? Œuvres, naïve & “quoted” — 42%!\n"
        "Warmest wishes from your next-door neighbour, Oliver")
PLAIN = ("abcdefghijklmnopqrstuvwxyz zyxwvutsrqponmlkjihgfedcba\n"
         "minimum running bookkeeper attitude coffee squeeze jinx\n"
         "Alpha Bravo Charlie Delta Echo Foxtrot Golf Hotel India\n"
         "Juliet Kilo Lima Mike November Oscar Papa Quebec Romeo\n"
         "Sierra Tango Uniform Victor Whiskey Xray Yankee Zulu 0123456789")
CENTER = "Alistaur Gaul\nChristopher Quill\nwith love\nYours, Zara\nl"


def cases() -> dict[str, tuple[str, str, dict]]:
    out = {}
    for i, s in enumerate(STYLES):
        out[f"{s}-card"] = (s, CARD, dict(size=5, page="240x440", margin=15, seed=3 + i, shade=0.5))
        out[f"{s}-plain"] = (s, PLAIN, dict(size=5, page="420x440", margin=15, seed=0, variation=0.0))
        out[f"{s}-center"] = (s, CENTER, dict(size=5, page="230x240", margin=12, seed=3 + i,
                                              align="center", valign="middle"))
    return out


def fits(svg: str) -> bool:
    """Whether all ink is on the page (a snapshot card must be fully visible)."""
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    w, h = float(m.group(1)), float(m.group(2))
    pts = np.vstack(parse(svg))
    return bool((pts >= 0).all() and (pts[:, 0] <= w).all() and (pts[:, 1] <= h).all())


def render(style_name: str, text: str, o: dict) -> str:
    """The SVG the CLI would write for these settings."""
    o = dict(size=6.0, page="a4", margin=20.0, align="left", valign="top", seed=0, variation=1.0, pen=0.35,
             shade=0.0) | o
    pw, ph = page_size(o["page"])
    _, mm = make_page(text, Style.load(style_name), size=o["size"], page=(pw, ph), margin=o["margin"],
                      align=o["align"], valign=o["valign"], seed=o["seed"], variation=o["variation"],
                      pen=o["pen"], shade=o["shade"])
    return to_svg(mm, (pw, ph), o["pen"], title=text[:60])


def parse(svg: str) -> list[np.ndarray]:
    """Every pen stroke in the SVG, in drawing order, as points in mm."""
    out = []
    for d in re.findall(r'<path d="([^"]*)"', svg):
        nums = re.findall(r"-?\d+(?:\.\d+)?", d)
        out.append(np.asarray(nums, float).reshape(-1, 2))
    return out


def _dense(p: np.ndarray, step: float = 0.02) -> np.ndarray:
    return g.resample(p, step) if len(p) > 1 and g.length(p) > step else p


def stroke_distance(a: np.ndarray, b: np.ndarray) -> float:
    """How far apart two strokes are: the larger of the gap between their
    start points, between their end points, and the Hausdorff distance
    between their ink (each densely resampled). Which points simplification
    kept, or a little float noise along a long stroke, doesn't count; moved
    ink, or a stroke drawn the other way round, does."""
    from scipy.spatial import cKDTree

    ends = max(float(np.linalg.norm(a[0] - b[0])), float(np.linalg.norm(a[-1] - b[-1])))
    da, db = _dense(a), _dense(b)
    h = max(float(cKDTree(db).query(da)[0].max()), float(cKDTree(da).query(db)[0].max()))
    return max(ends, h)


def compare(old: str, new: str) -> str | None:
    """None if the two SVGs draw the same thing, else what changed."""
    a, b = parse(old), parse(new)
    if len(a) != len(b):
        return f"{len(a)} pen strokes -> {len(b)}"
    worst, at = 0.0, -1
    for k, (p, q) in enumerate(zip(a, b)):
        d = stroke_distance(p, q)
        if d > worst:
            worst, at = d, k
    if worst > TOLERANCE:
        moved = sum(stroke_distance(p, q) > TOLERANCE for p, q in zip(a, b))
        return f"{moved} of {len(a)} strokes moved, up to {worst:.2f} mm (stroke {at + 1})"
    return None


def diff_png(old: str, new: str, path: Path, dpi: int = 110) -> None:
    """before | after | overlay, stacked. In the overlay, strokes that moved
    are drawn red (before) and blue (after); unchanged ones are grey."""
    from PIL import Image, ImageDraw

    a, b = parse(old), parse(new)
    a_moved, b_moved, same = split_moved(a, b)
    # crop to the ink, with a small border
    pts = np.vstack(a + b)
    lo, hi = pts.min(0) - 4, pts.max(0) + 4
    k = dpi / 25.4
    size = (int((hi[0] - lo[0]) * k), int((hi[1] - lo[1]) * k))

    def panel(layers, label):
        img = Image.new("RGB", size, "white")
        d = ImageDraw.Draw(img)
        for strokes, col in layers:
            for p in strokes:
                pts = [tuple(v) for v in (p - lo) * k]
                if len(pts) > 1:
                    d.line(pts, fill=col, width=2, joint="curve")
        d.text((6, 4), label, fill=(120, 120, 120))
        return img

    panels = [panel([(a, (25, 25, 60))], "before"), panel([(b, (25, 25, 60))], "after"),
              panel([(same, (200, 200, 200)), (a_moved, (235, 60, 60)), (b_moved, (40, 90, 220))],
                    "overlay: changed strokes before (red) and after (blue); unchanged grey")]
    out = Image.new("RGB", (size[0], size[1] * 3 + 8), (200, 200, 200))
    for i, p in enumerate(panels):
        out.paste(p, (0, i * (size[1] + 4)))
    out.save(path)


def split_moved(a: list[np.ndarray], b: list[np.ndarray]):
    """(strokes only in before, strokes only in after, strokes in both).
    Strokes are paired in order when the counts match; otherwise each after
    stroke is matched to any unused before stroke within TOLERANCE, so a new
    join (two strokes becoming one) shows only the strokes it touched."""
    if len(a) == len(b):
        moved = [stroke_distance(p, q) > TOLERANCE for p, q in zip(a, b)]
        return ([p for p, m in zip(a, moved) if m], [q for q, m in zip(b, moved) if m],
                [q for q, m in zip(b, moved) if not m])
    used = [False] * len(a)
    same, b_moved = [], []
    for q in b:
        for i, p in enumerate(a):
            if (not used[i] and np.abs(p[0] - q[0]).max() < 1 and np.abs(p[-1] - q[-1]).max() < 1
                    and stroke_distance(p, q) <= TOLERANCE):
                used[i] = True
                same.append(q)
                break
        else:
            b_moved.append(q)
    return [p for p, u in zip(a, used) if not u], b_moved, same


def check(names=None, diff_dir: Path | None = None) -> list[tuple[str, str]]:
    """[(card, what changed)] for every card that differs from its snapshot."""
    changed = []
    for name, (style, text, o) in cases().items():
        if names and name not in names:
            continue
        f = SNAP_DIR / f"{name}.svg"
        new = render(style, text, o)
        if not f.exists():
            changed.append((name, "no snapshot yet (run tools/snapshots.py --update)"))
            continue
        old = f.read_text()
        why = compare(old, new)
        if why:
            changed.append((name, why))
            if diff_dir:
                diff_dir.mkdir(parents=True, exist_ok=True)
                diff_png(old, new, diff_dir / f"{name}.png")
                (diff_dir / f"{name}.svg").write_text(new)
    return changed


COMMENT_MARK = "<!-- cursive-snapshots -->"  # finds the PR comment to update


def report(changed: list[tuple[str, str]], image_url: str | None = None) -> str:
    """Markdown for the job summary and the pull request comment. With
    `image_url`, each changed card's diff picture (<image_url>/<card>.png) is
    shown inline."""
    if not changed:
        return f"{COMMENT_MARK}\n### Snapshots\n\nAll {len(cases())} cards unchanged.\n"
    out = [COMMENT_MARK, f"### Snapshots: {len(changed)} of {len(cases())} cards changed", "",
           "| card | change |", "|---|---|"]
    out += [f"| `{n}` | {w} |" for n, w in changed]
    out += ["", "This is for review and doesn't fail the build. Merging the pull request accepts these "
                "changes: CI then updates `tests/snapshots/` on main."]
    if image_url:
        out += ["", "Each picture: before, after, then an overlay with changed strokes in red (before) "
                    "and blue (after); unchanged strokes are grey.", ""]
        for k, (n, _) in enumerate(changed):
            out += [f"<details{' open' if k == 0 else ''}><summary><code>{n}</code></summary>", "",
                    f"![{n}]({image_url.rstrip('/')}/{n}.png)", "", "</details>"]
    else:
        out += ["", "The **snapshot-diffs** artifact of this run has before/after pictures."]
    return "\n".join(out) + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--update", action="store_true", help="write the current output as the snapshots")
    ap.add_argument("--only", nargs="*", help="card names, e.g. copperplate-card (default: all)")
    ap.add_argument("--diff", type=Path, help="directory for before/after PNGs of changed cards")
    ap.add_argument("--report", type=Path, help="write a Markdown report (for a PR comment) here")
    ap.add_argument("--image-url", help="with --report: URL the --diff PNGs will be served from")
    ap.add_argument("--no-fail", action="store_true",
                    help="exit 0 even when cards changed (CI: changes are for review)")
    args = ap.parse_args()
    if args.update:
        SNAP_DIR.mkdir(parents=True, exist_ok=True)
        for name, (style, text, o) in cases().items():
            if args.only and name not in args.only:
                continue
            svg = render(style, text, o)
            if not fits(svg):
                print(f"warning: {name} runs off its page; enlarge the page in cases()")
            (SNAP_DIR / f"{name}.svg").write_text(svg)
            print(f"wrote {SNAP_DIR / name}.svg")
        return 0
    changed = check(args.only, args.diff)
    for name, why in changed:
        print(f"CHANGED {name}: {why}")
    if args.report:
        args.report.write_text(report(changed, args.image_url))
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a") as fh:
            fh.write(report(changed))
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a") as fh:
            fh.write(f"changed={len(changed)}\n")
    if not changed:
        print(f"all {len(cases())} snapshot cards unchanged")
    return 1 if changed and not args.no_fail else 0


if __name__ == "__main__":
    sys.exit(main())
