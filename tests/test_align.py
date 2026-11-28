"""Horizontal alignment (layout(align=...), --align, the web page's Align).

Centre and right alignment work on the final ink: after slant and the per-line
wobble, so slanted ascenders, capital swashes and exit strokes are centred too.
Aligning on the advance width instead pushed centred text visibly to the right
(by almost two x-heights for "Alistaur Gaul" in spencerian). The web port is
checked against these same layouts, byte for byte, in tests/test_web.py.
"""

import numpy as np
import pytest

from cursive.cli import make_page
from cursive.glyph import Style
from cursive.layout import layout

STYLES = ["copperplate", "spencerian", "modern", "formal", "signature", "flowing", "roundhand"]
# big swash capitals, long exit strokes, and lines of very different lengths
TEXTS = ["Alistaur Gaul", "Christopher", "Queen Mary\nLady Grey", "Jo\nXavier Quentin\nl"]
WIDTH = 142 / 3.9  # the reported card: 162 mm page, 10 mm margins, 3.9 mm x-height
TOL = 0.05  # x-heights


def load(name):
    try:
        st = Style.load(name)
    except FileNotFoundError:
        pytest.skip(f"{name} not available")
    if not st.glyphs:
        pytest.skip(f"{name} has no glyphs")
    return st


def xs(ln):
    return np.vstack(ln.paths)[:, 0]


@pytest.fixture(params=STYLES)
def style(request):
    return load(request.param)


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("seed,amount", [(0, 1.0), (3, 1.0), (7, 2.0), (1, 0.0)])
def test_center_puts_the_ink_midpoint_on_the_centre(style, text, seed, amount):
    lines = layout(text, style, width=WIDTH, seed=seed, amount=amount, align="center")
    assert lines
    for ln in lines:
        x = xs(ln)
        assert x.max() - x.min() < WIDTH  # these lines all fit, so nothing is clamped
        assert abs((x.min() + x.max()) / 2 - WIDTH / 2) < TOL


@pytest.mark.parametrize("text", TEXTS)
@pytest.mark.parametrize("seed", [0, 3])
def test_right_puts_the_ink_on_the_right_margin(style, text, seed):
    for ln in layout(text, style, width=WIDTH, seed=seed, align="right"):
        x = xs(ln)
        assert x.min() >= 0
        assert abs(x.max() - WIDTH) < TOL


@pytest.mark.parametrize("align", ["center", "right"])
def test_alignment_only_moves_each_line_sideways(style, align):
    """Same strokes, same wobble, same advance width and baseline: each line is
    the left-aligned one shifted right by a single amount."""
    text = "Alistaur Gaul\nChristopher Quill\nwith love"
    left = layout(text, style, width=WIDTH, seed=3, align="left")
    other = layout(text, style, width=WIDTH, seed=3, align=align)
    assert len(left) == len(other)
    for a, b in zip(left, other):
        assert b.width == a.width  # still the advance width
        assert b.baseline == a.baseline
        assert len(a.paths) == len(b.paths)
        shift = float(b.paths[0][0, 0] - a.paths[0][0, 0])  # either sign: a full line can move left
        for p, q in zip(a.paths, b.paths):
            assert p.shape == q.shape
            np.testing.assert_allclose(q[:, 1], p[:, 1], rtol=0, atol=1e-12)
            np.testing.assert_allclose(q[:, 0] - p[:, 0], shift, rtol=0, atol=1e-9)


@pytest.mark.parametrize("align", ["left", "center", "right"])
def test_ink_wider_than_the_line_stays_on_the_left_margin(style, align):
    narrow = 4.0  # far narrower than any word, so every line overflows
    for ln in layout("Extraordinarily Xavier", style, width=narrow, seed=2, align=align):
        x = xs(ln)
        assert x.max() - x.min() > narrow
        assert x.min() > -1e-9  # never past the left margin
        if align != "left":
            # centring or right-aligning overflowing ink would push it past the
            # margin, so the guard puts it exactly on it (left-aligned ink may
            # start a little in, at the letter's own lead-in)
            assert abs(x.min()) < 1e-9


def test_without_a_width_alignment_does_nothing(style):
    a = layout("Alistaur Gaul", style, width=None, seed=3, align="left")
    for align in ("center", "right"):
        b = layout("Alistaur Gaul", style, width=None, seed=3, align=align)
        for p, q in zip(a[0].paths, b[0].paths):
            np.testing.assert_array_equal(p, q)


@pytest.mark.parametrize("name", ["spencerian", "copperplate"])
def test_reported_card_is_centred_on_the_page(name):
    """The bug as reported, at page level in mm (what the SVG and plotter get)."""
    st = load(name)
    size, pw, margin = 3.9, 162.0, 10.0
    lines, mm = make_page("Alistaur Gaul", st, size=size, page=(pw, 112.0), margin=margin,
                          align="center", seed=3)
    assert len(mm) == 1
    x = np.vstack(mm[0])[:, 0]
    assert abs((x.min() + x.max()) / 2 - pw / 2) < TOL * size


def test_reported_card_ink_is_off_centre_of_its_advance_width():
    """Keeps the tests above meaningful: in the reported case the ink is well
    off the middle of the advance width, so centring on `ln.width` (the old
    behaviour) would fail them."""
    st = load("spencerian")
    ln = layout("Alistaur Gaul", st, width=None, seed=3)[0]
    x = xs(ln)
    assert (x.min() + x.max()) / 2 - ln.width / 2 > 0.5
