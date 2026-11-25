"""The snapshot tool itself. Whether the cards still match tests/snapshots/ is
not a test: changes are for review (see tools/snapshots.py and CI), and
merging to main accepts them."""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import snapshots  # noqa: E402


def test_snapshot_cards_fit_their_pages():
    for f in sorted(snapshots.SNAP_DIR.glob("*.svg")):
        assert snapshots.fits(f.read_text()), f.name


def test_compare_ignores_tiny_float_noise_but_not_real_moves():
    svg = (snapshots.SNAP_DIR / "copperplate-card.svg").read_text()
    # every coordinate off by up to 0.009 mm, as another machine's rounding might be
    noisy = re.sub(r"(\.\d\d)(\d)", lambda m: m.group(1) + str((int(m.group(2)) + 1) % 10), svg)
    assert noisy != svg
    assert snapshots.compare(svg, noisy) is None
    first = svg.index('<path d="M ') + len('<path d="M ')
    x = svg[first:svg.index(",", first)]
    moved = svg[:first] + f"{float(x) + 1:.3f}" + svg[first + len(x):]
    assert snapshots.compare(svg, moved)
