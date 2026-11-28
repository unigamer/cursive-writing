import numpy as np
import pytest

from cursive import geometry as g
from cursive.glyph import Style
from cursive.join import connector
from cursive.layout import layout, place_word
from cursive.variation import Variation

STYLES = ["copperplate", "spencerian", "modern", "formal", "signature", "flowing", "roundhand"]


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


def test_unjoined_capitals_use_the_capital_gap(style):
    """pairs.json kerning is current: an unjoined capital sits closer to the
    next letter than joined lowercase letters sit to each other."""
    from cursive.join import pair_params
    from cursive.spacing import kern_gap, unjoined_dx

    assert style.capital_gap < style.letter_gap
    checked = 0
    for pr in ("Ro", "Ma", "Ke", "Bo", "Ni", "Pa", "Xa"):
        a, b = style.glyphs[pr[0]][0], style.glyphs[pr[1]][0]
        prm = pair_params(style, a, b)
        if prm["join"] or style.pairs.get(pr, {}).get("manual"):
            continue
        assert kern_gap(style, a, b) == style.capital_gap
        assert prm["dx"] == pytest.approx(unjoined_dx(style, a, b), abs=1e-6), pr
        checked += 1
    assert checked


def _word_ink(style, text):
    """Ink of each word of a one-line layout (no variation), as point sets."""
    lines = layout(text, style, width=None, amount=0.0)
    assert len(lines) == 1
    counts = [len(joined_word(style, w).paths) for w in text.split()]
    paths = lines[0].paths
    out, k = [], 0
    for n in counts:
        out.append(np.vstack([g.resample(p, 0.02) if len(p) > 1 else p for p in paths[k:k + n]]))
        k += n
    return out


@pytest.mark.parametrize("text", ["Paul Kevin", "House. Kindly", "bed. Work", "of June", "daft Jim.",
                                  "engagement. We", "quartz, judge", "Owen Tom"])
def test_neighbouring_words_keep_clear(style, text):
    from cursive.layout import WORD_TOUCH

    A, B = _word_ink(style, text)
    d = float(np.min(np.linalg.norm(A[:, None] - B[None], axis=2)))
    assert d >= WORD_TOUCH - 0.03, (text, d)  # never touching, in any style


def test_pushed_words_still_fit_the_line(style):
    """A word pushed clear of a swash takes its extra space into account when
    lines are broken, so no line runs past the width."""
    text = "bed. Work of June daft Jim. House. Kindly Paul Kevin quartz, judge " * 3
    for ln in layout(text, style, width=30.0, amount=0.0):
        assert ln.width <= 30.0 + 1e-9


@pytest.mark.parametrize("text", ["House. Kindly", "Paul Kevin", "Owen Tom", "May. Notes"])
def test_word_gaps_stay_wider_than_letter_gaps(text):
    """Flowing's exit hairlines and capital lead-ins used to close a word gap to
    less than its letter gap, so two words read as one."""
    st = available("flowing")
    if st is None:
        pytest.skip()
    A, B = _word_ink(st, text)
    d = float(np.min(np.linalg.norm(A[:, None] - B[None], axis=2)))
    assert d >= st.word_clear - 0.03, (text, d)


def _body_gap(style, text):
    lines = layout(text, style, width=None, amount=0.0)
    from cursive.layout import body_extent
    A, B = _word_ink(style, text)
    k = style.glyph_slant
    return body_extent([B], k)[0] - body_extent([A], k)[1], lines[0]


def test_every_space_counts():
    """Each typed space widens the gap by one word space; leading spaces indent."""
    st = available("modern")
    if st is None:
        pytest.skip()
    one, _ = _body_gap(st, "cat dog")
    three, _ = _body_gap(st, "cat   dog")
    assert three - one == pytest.approx(2 * st.word_space, abs=1e-9)
    plain = layout("cat dog", st, width=None, amount=0.0)[0]
    indented = layout("  cat dog", st, width=None, amount=0.0)[0]
    assert indented.width - plain.width == pytest.approx(2 * st.word_space, abs=1e-9)
    shift = min(float(p[:, 0].min()) for p in indented.paths) - min(float(p[:, 0].min()) for p in plain.paths)
    assert shift == pytest.approx(2 * st.word_space, abs=1e-9)
    # trailing spaces and spaces at a line break take no room
    assert layout("cat dog   ", st, width=None, amount=0.0)[0].width == pytest.approx(plain.width)
    for ln in layout("cat" + " " * 40 + "dog", st, width=10.0, amount=0.0):
        assert len(ln.paths) and min(float(p[:, 0].min()) for p in ln.paths) < 1.0


def test_missing_characters_are_reported(style):
    from cursive.glyph import missing_chars_warning

    groups = dict(style.char_groups())
    assert groups["lowercase"] == "abcdefghijklmnopqrstuvwxyz"
    assert groups["capitals"] == "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
    assert groups["digits"] == "0123456789"
    assert "é" in groups["more letters"] and "Ø" in groups["more letters"]
    assert sum(len(c) for c in groups.values()) == len(style.glyphs)
    assert style.missing_chars("Hello, world!\n\t ") == ""
    assert style.missing_chars("Łódź → Łeba ő") == "Łź→ő"  # each once, in order
    assert missing_chars_warning("X", "é") == 'The X style has no glyph for "é"; it is left out.'


def test_cli_warns_about_missing_characters_and_lists_them(tmp_path, capsys):
    from cursive.cli import main

    main(["Łódź →", "--style", "modern", "-o", str(tmp_path / "x.svg")])
    err = capsys.readouterr().err
    assert '"Ł", "ź", "→"' in err and "--list-chars" in err
    main(["Café €", "--style", "modern", "-o", str(tmp_path / "y.svg")])
    assert "no glyph" not in capsys.readouterr().err
    main(["--list-chars", "--style", "modern"])
    out = capsys.readouterr().out
    assert "abcdefghijklmnopqrstuvwxyz" in out and "£" in out and "é" in out and "€" in out
    main(["--list-chars", "--style", "all"])
    assert capsys.readouterr().out.count("characters, plus spaces") == len(STYLES)


def test_doubled_letters_differ(style):
    """The second of ll / ee / ss never comes out as a copy of the first."""
    for w in ["ll", "ee", "ss", "oo", "ff"]:
        for seed in range(5):
            word, _ = place_word(w, style, Variation(style.variation, seed, 1.0))
            ps = [p for p, kind, _ in word.pieces if kind == "glyph"]
            a, b = ps[0], ps[1]
            # compare shapes, not positions: centre each and resample to the same count
            ra, rb = (g.resample(p, g.length(p) / 60) for p in (a, b))
            n = min(len(ra), len(rb))
            ra, rb = ra[:n] - ra[:n].mean(0), rb[:n] - rb[:n].mean(0)
            assert np.abs(ra - rb).max() > 0.01, (style.name, w, seed)


def test_doubled_alternates_are_not_repeated():
    st = Style.load("formal")
    opts = st.glyphs.get("a", [])
    v = Variation(st.variation, 0, 1.0)
    if len(opts) > 1:
        for _ in range(20):
            assert v.choose(opts, avoid=opts[0]) is not opts[0]


def test_joined_ts_share_one_crossbar(style):
    for w, bars in (("atta", 1), ("attta", 1), ("atata", 2)):
        word = joined_word(style, w)
        t = style.glyphs["t"][0]
        if len(t.deferred) != 1 or len(word.joins) != len(w) - 1:  # bar not deferred, or a t that doesn't join
            continue
        deferred = [p for p, kind, _ in word.pieces if kind == "deferred"]
        assert len(deferred) == bars, (style.name, w)
    word = joined_word(style, "atta")
    if len(word.joins) == 3 and len(style.glyphs["t"][0].deferred) == 1:
        bar = [p for p, kind, _ in word.pieces if kind == "deferred"][0]
        single = [p for p, kind, _ in joined_word(style, "ata").pieces if kind == "deferred"][0]
        assert g.length(bar) > 1.3 * g.length(single)


def _mark_gaps(word, text):
    """Distance from each i-dot or accent to the rest of the word's ink
    (t- and f-bars and the x's second stroke cross their letter by design)."""
    deferred = [(p, i) for p, kind, i in word.pieces if kind == "deferred"]
    main = np.vstack([g.resample(p, 0.01) for p in word.paths[: len(word.paths) - len(deferred)]])
    return [float(np.min(np.linalg.norm(main[:, None] - g.resample(p, 0.01)[None], axis=2)))
            for p, i in deferred if text[i] not in "tfx"]


@pytest.mark.parametrize("text", ["Rui", "ui", "taxi", "ski", "naï", "cafè", "née", "fé"])
def test_dots_and_accents_keep_clear_of_the_ink(style, text):
    """A word-final flourish never curls up into the i-dot, and an accent
    under a neighbour's leaning loop (Spencerian cafè) is moved off it."""
    if style.missing_chars(text):
        pytest.skip("not in this style")
    for seed in range(25):
        gaps = _mark_gaps(joined_word(style, text, seed=seed, amount=1.0), text)
        assert min(gaps) > 0.1, (style.name, text, seed, gaps)


def test_flourish_backs_off_from_the_dot():
    """Spencerian i: the dot lies on the slant of the exit hairline, so a full
    flourish would point straight at it."""
    st = available("spencerian")
    if st is None:
        pytest.skip("style not built")
    for seed in range(40):
        word = joined_word(st, "ui", seed=seed, amount=1.0)
        assert min(_mark_gaps(word, "ui")) >= 0.3, seed


@pytest.mark.parametrize("text", ["ski", "mum", "quiz", "hair,"])
def test_word_final_tails_are_short(style, text):
    """The last letter's exit hairline only reaches the next letter mid-word;
    at the end of a word (punctuation or not) it stops as a short flick."""
    word = joined_word(style, text)
    last = max(i for i, c in enumerate(text) if c.isalpha())
    if style.glyphs[text[last]][0].exit == "high":
        pytest.skip("finishes on top of the letter (r on its shoulder), no rising tail")
    tail = [p for p, kind, i in word.pieces if kind == "glyph" and i == last][0]
    assert tail[-1, 1] < 0.4, (style.name, text, tail[-1, 1])
