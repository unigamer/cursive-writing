"""Accented letters, composed from each style's own base letters, and the
other characters beyond ASCII."""

import json

import numpy as np
import pytest

from cursive.compose import ACCENTED, STANDALONE, base_of, compose
from cursive.glyph import STYLES_DIR, Style, glyph_name
from cursive.layout import place_word
from cursive.variation import Variation

STYLES = ["copperplate", "spencerian", "modern", "formal", "signature", "flowing", "roundhand"]


@pytest.fixture(params=STYLES)
def name(request):
    return request.param


def test_every_style_has_the_extra_characters(name):
    st = Style.load(name)
    missing = st.missing_chars(ACCENTED + STANDALONE)
    assert missing == "", f"{name} lacks {missing}"


def test_composed_letters_are_up_to_date(name):
    """Each composed file is exactly its base letter's file plus the marks in
    marks.json: re-run tools/compose_glyphs.py after editing a base letter."""
    sdir = STYLES_DIR / name
    slant = json.loads((sdir / "style.json").read_text())["glyph_slant"]
    marks = json.loads((sdir / "marks.json").read_text())["marks"]
    gdir = sdir / "glyphs"
    checked = 0
    for ch in ACCENTED:
        mark = marks[ch]
        assert mark["base"] == base_of(ch)
        for f in gdir.glob(f"{glyph_name(ch)}*.json"):
            have = json.loads(f.read_text())
            if have.get("edited"):
                continue
            base_file = gdir / f"{glyph_name(mark['base'])}{f.stem[len(glyph_name(ch)):]}.json"
            assert base_file.exists(), f"{f.name} has no base {base_file.name}"
            assert have == compose(ch, json.loads(base_file.read_text()), mark, slant), \
                f"{name}/{f.name} is stale: run tools/compose_glyphs.py {name}"
            checked += 1
    assert checked >= len(ACCENTED)


def test_every_variant_of_a_base_letter_is_accented(name):
    gdir = STYLES_DIR / name / "glyphs"
    for ch in ACCENTED:
        base = glyph_name(base_of(ch))
        variants = {f.stem[len(base):] for f in gdir.glob(f"{base}*.json") if f.stem == base or f.stem.startswith(base + ".")}
        accented = {f.stem[len(glyph_name(ch)):] for f in gdir.glob(f"{glyph_name(ch)}*.json")}
        assert variants == accented, (name, ch)


def _main_path(st, word):
    w, _ = place_word(word, st, Variation(st.variation, 0, 0.0))
    return w


@pytest.mark.parametrize("word,plain", [("café", "cafe"), ("naïve", "naive"), ("Ångström", "Angstrom"),
                                         ("façade", "facade"), ("señor", "senor"), ("Zoë", "Zoe"),
                                         ("Écoute", "Ecoute"), ("øre", "ore")])
def test_accented_words_join_like_plain_ones(name, word, plain):
    """An accented letter is its base letter plus marks drawn after the word:
    the joined pen path of the word is unchanged."""
    st = Style.load(name)
    a, b = _main_path(st, word), _main_path(st, plain)
    np.testing.assert_allclose(a.paths[0], b.paths[0], atol=1e-9)
    # the marks are extra pen strokes; the i-dot of naïve is replaced by them
    assert len(a.paths) > len(b.paths) - ("ï" in word)


def test_new_letters_join_inside_words(name):
    """æ, œ and ß are letters with their own optimised pairs: lowercase words
    containing them are joined throughout, like any other word. (A few pairs
    may lift where joining would cross the letter, as signature's oß does.)"""
    st = Style.load(name)
    for word in ("cæsar", "manœuvre", "straße", "grüße"):
        w = _main_path(st, word)
        assert len(w.joins) == len(word) - 1, (name, word, w.joins)
