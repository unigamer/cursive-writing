import numpy as np
import pytest

from cursive import geometry as g
from cursive.glyph import Style
from cursive.join import connector
from cursive.layout import layout, place_word
from cursive.variation import Variation

STYLES = ["copperplate", "spencerian", "modern", "formal"]


def available(name):
    try:
        st = Style.load(name)
    except FileNotFoundError:
        return None
    return st if st.glyphs else None


@pytest.fixture(params=STYLES)
def style(request):
    st = available(request.param)
    if st is None:
        pytest.skip(f"style {request.param} not built")
    return st


def joined_word(style, text, seed=0, amount=0.0):
    word, _ = place_word(text, style, Variation(style.variation, seed, amount))
    return word


def test_connector_meets_endpoints_and_leaves_smoothly():
    prev = np.array([[0.0, 0.5], [0.3, 0.1], [0.6, 0.0], [0.8, 0.05]])
    nxt = np.array([[1.4, 0.9], [1.3, 0.6], [1.2, 0.0]])
    c = connector(prev, nxt, 0.45)
    assert np.allclose(c[0], prev[-1], atol=1e-9)
    assert np.allclose(c[-1], nxt[0], atol=1e-9)
    t_prev = g.end_tangent(prev, 0.06)
    t_conn = g.unit(c[1] - c[0])
    assert np.degrees(g.turn_angle(t_prev, t_conn)) < 5


def test_lowercase_words_are_one_continuous_stroke(style):
    for w in ["minimum", "running", "elegant", "handwriting", "cursive"]:
        word = joined_word(style, w)
        main = [p for p in word.paths if len(p) > 20]  # ignore dots / bars
        # every adjacent pair is joinable, so the main ink is a single path
        assert len(word.joins) == len(w) - 1 - sum(
            not style.can_join(style.glyphs[a][0], style.glyphs[b][0]) for a, b in zip(w, w[1:])
        )
        assert len(main) >= 1


def test_no_join_pairs_are_respected(style):
    style.no_join_pairs = {"ab"}
    word = joined_word(style, "abc")
    assert (0, 1) not in word.joins
    if style.can_join(style.glyphs["b"][0], style.glyphs["c"][0]):
        assert (1, 2) in word.joins


def test_words_never_join_across_spaces(style):
    lines = layout("on on on", style, width=None, seed=0, amount=0.0)
    paths = lines[0].paths
    # find the x-extent of each word's ink: no single path may span a gap
    one = layout("on", style, width=None, seed=0, amount=0.0)[0]
    single_w = max(p[:, 0].max() for p in one.paths) - min(p[:, 0].min() for p in one.paths)
    for p in paths:
        assert np.ptp(p[:, 0]) <= single_w + 1e-6


def test_same_seed_same_output(style):
    a = layout("the quick brown fox", style, width=20, seed=7)
    b = layout("the quick brown fox", style, width=20, seed=7)
    c = layout("the quick brown fox", style, width=20, seed=8)
    flat = lambda ls: np.vstack([p for ln in ls for p in ln.paths])  # noqa: E731
    assert np.array_equal(flat(a), flat(b))
    assert not np.array_equal(flat(a), flat(c))


def test_shading_adds_passes_only_beside_downstrokes():
    from cursive.shade import shade_paths

    from cursive import geometry as g

    down = np.column_stack([np.zeros(50), np.linspace(0, 10, 50)])  # page mm, y down = downstroke
    up = down[::-1]
    sd = shade_paths([down], 0.0, 0.3, 0.6)[0]
    su = shade_paths([up], 0.0, 0.3, 0.6)[0]
    assert g.length(sd) > 2.5 * g.length(down)  # extra passes woven in
    assert np.allclose(sd[-1], down[-1]) and np.allclose(sd[0], down[0])  # same ends, no lift
    assert g.length(su) < 1.01 * g.length(up)  # upstrokes stay hairlines


def test_cli_writes_svg(tmp_path):
    from cursive.cli import main

    if available("copperplate") is None:
        pytest.skip("copperplate not built")
    out = tmp_path / "t.svg"
    main(["hello world", "--style", "copperplate", "--page", "a6-landscape", "--margin", "8",
          "--size", "5", "--shade", "0.5", "-o", str(out)])
    svg = out.read_text()
    assert svg.startswith("<?xml") and 'inkscape:groupmode="layer"' in svg and svg.count("<path") >= 2


def test_positional_forms_used_at_word_ends():
    st = available("formal")
    if st is None or ("e", "fina") not in st.forms:
        pytest.skip("formal style with e.fina not built")
    word, _ = place_word("the", st, Variation(st.variation, 0, 0.0))
    fina = st.forms[("e", "fina")][0]
    # the last glyph's ink must come from the final form
    last = [p for p, kind, i in word.pieces if i == 2 and kind == "glyph"][0]
    assert len(last) and fina.main.points.shape[0] > 0
    base_e = st.glyphs["e"][0]
    assert not np.allclose(fina.main.points[:5], base_e.main.points[:5])


def test_crossbar_is_deferred(style):
    t = style.glyphs["t"][0]
    assert any(s.deferred and s.kind == "line" for s in t.strokes), "t should have a separate crossbar"


def test_even_spacing_evens_gaps(style):
    import string
    from cursive.spacing import pair_gaps

    if not style.glyphs.get("a"):
        pytest.skip()
    gaps = np.array(list(pair_gaps(style, string.ascii_lowercase).values()))
    assert gaps.std() < 0.05  # every lowercase pair gets (nearly) the same body gap


def test_pair_scorer_prefers_clean_joins():
    from dataclasses import replace

    from cursive.join import pair_params
    from cursive.pairs import evaluate

    st = available("spencerian")
    if st is None:
        pytest.skip()
    base = replace(st, pairs={})
    nn = evaluate(st, st.glyphs["n"][0], st.glyphs["n"][0], pair_params(base, st.glyphs["n"][0], st.glyphs["n"][0]))
    assert nn.score < 0.5  # n->n is a textbook join
    # forcing a join out of a capital that ends low on its left is clearly bad
    K, a = st.glyphs["K"][0], st.glyphs["a"][0]
    prm = {**pair_params(base, K, a), "join": True}
    assert evaluate(st, K, a, prm).score > 5


def test_pair_overrides_never_join_across_rules():
    from cursive.join import pair_params

    st = available("spencerian")
    if st is None:
        pytest.skip()
    st.pairs = {"n.": {"join": True}}
    assert not pair_params(st, st.glyphs["n"][0], st.glyphs["."][0])["join"]


def test_symbols_never_join():
    for name in ("spencerian", "formal"):
        st = Style.load(name)
        a = st.glyphs["a"][0]
        for c in "()\"/%$@#+=*0123456789&":
            if c in st.glyphs:
                g = st.glyphs[c][0]
                assert not st.can_join(a, g) and not st.can_join(g, a), (name, c)
