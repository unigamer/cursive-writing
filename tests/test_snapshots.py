"""Visual regression: each card must still draw what tests/snapshots/ holds.

If a change is intended, accept it with `python tools/snapshots.py --update`
(and look at `python tools/snapshots.py --diff diffs/` first)."""

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import snapshots  # noqa: E402


@pytest.mark.parametrize("name", list(snapshots.cases()))
def test_snapshot_unchanged(name):
    changed = snapshots.check([name])
    assert not changed, f"{changed[0][1]}; see `python tools/snapshots.py --diff diffs/`, then --update if intended"


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
