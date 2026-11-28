"""The web page's JavaScript engine (web/cursive/) must write exactly what the
Python engine writes.

The JS runs under deno (or node) via web/test/runner.js; these tests are
skipped when neither is installed. They check that:

  * the bundled style data (web/data/) is up to date with styles/
  * the JS random generator reproduces numpy's default_rng draw for draw
  * every joined letter pair, in every style, matches with and without variation
  * whole pages (wrapping, alignment, shading, page sizes) give a
    byte-identical SVG
  * the single-file page (build_web.py --standalone) is self-contained and
    its bundled engine writes the same SVGs
"""

from __future__ import annotations

import json
import os
import re
import shutil
import string
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

from cursive.cli import make_page
from cursive.glyph import Style
from cursive.layout import place_word
from cursive.render import page_size, to_svg
from cursive.variation import Variation

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import build_web  # noqa: E402

STYLES = build_web.style_names()


def js_runtime() -> list[str] | None:
    deno = shutil.which("deno") or next(
        (p for p in [os.path.expanduser("~/.deno/bin/deno")] if os.path.exists(p)), None)
    if deno:
        return [deno, "run", "--allow-read"]
    node = shutil.which("node")
    return [node] if node else None


RUNTIME = js_runtime()
needs_js = pytest.mark.skipif(RUNTIME is None, reason="needs deno or node to run the JS engine")


def run_js(requests: list[dict], tmp: Path) -> list:
    req = tmp / "requests.json"
    req.write_text(json.dumps(requests))
    out = subprocess.run([*RUNTIME, str(ROOT / "web" / "test" / "runner.js"), str(req)],
                         capture_output=True, text=True, cwd=ROOT, timeout=600)
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout)


# ------------------------------------------------------------------ data


def test_bundles_are_up_to_date():
    for name in STYLES:
        path = build_web.OUT / f"{name}.json"
        assert path.exists() and path.read_text() == build_web.render(name), (
            f"web/data/{name}.json is out of date: run python tools/build_web.py")
    assert (build_web.OUT / "index.json").read_text() == build_web.index()
    assert build_web.STYLES_LICENSE.read_text() == build_web.styles_license(), "run python tools/build_web.py"
    assert build_web.WEB_LICENSES.read_text() == build_web.licenses_text(), "run python tools/build_web.py"


def test_bundle_holds_the_same_glyph_data():
    for name in STYLES:
        b = json.loads((build_web.OUT / f"{name}.json").read_text())
        files = sorted((ROOT / "styles" / name / "glyphs").glob("*.json"))
        assert [f for f, _ in b["glyphs"]] == [f.name for f in files]
        for (_, gl), f in zip(b["glyphs"], files):
            src = json.loads(f.read_text())
            assert gl["strokes"] == src["strokes"]
            assert all(gl[k] == src[k] for k in gl)


# ------------------------------------------------------------- JS engine


@pytest.fixture(scope="module")
def js_tmp(tmp_path_factory):
    return tmp_path_factory.mktemp("web")


@needs_js
def test_random_stream_matches_numpy(js_tmp):
    seeds = [0, 1, 3, 42, 2**32 + 5, 2**70 + 123]
    # seeds past 2^53 go as strings: a JS number cannot hold them exactly
    js = run_js([{"op": "rng", "seed": s if s < 2**53 else str(s), "n": 3000} for s in seeds], js_tmp)
    for seed, got in zip(seeds, js):
        rng = np.random.default_rng(seed)
        want = []
        for _ in range(3000):
            want += [int(rng.integers(3)), float(rng.normal(0, 0.03)), float(rng.uniform(0.5, 0.9)),
                     int(rng.integers(2))]
        assert got == want, f"seed {seed}"


WORDS = ([a + b for a in string.ascii_letters for b in string.ascii_lowercase]
         + ["minimum", "handwriting", "Quick,", "fox's", "£12.50!", "e-mail", "(yes)", "\"Hi\"", "ü"]
         # composed accented letters (all variants and forms), and letters with their own pairs
         + ["café", "naïve", "Ångström", "façade", "señor", "Zoë", "Écoute", "øre", "élève", "gâteau",
            "cæsar", "manœuvre", "straße", "Œuvre", "Æsop", "¿Qué?", "«oui»", "‘so’ — “it” – …", "€5"])


@needs_js
@pytest.mark.parametrize("amount", [0.0, 1.0, 2.5])
def test_joined_words_match(js_tmp, amount):
    js = run_js([{"op": "words", "style": s, "words": WORDS, "seed": 5, "amount": amount} for s in STYLES], js_tmp)
    for name, got in zip(STYLES, js):
        st = Style.load(name)
        var = Variation(st.variation, 5, amount)
        for w, jpaths in zip(WORDS, got):
            paths = place_word(w, st, var)[0].paths
            assert [len(p) for p in jpaths] == [len(p) for p in paths], f"{name} {w!r}"
            for p, q in zip(paths, jpaths):
                # identical up to last-bit rounding in numpy's matrix products
                np.testing.assert_allclose(np.asarray(q, float).reshape(-1, 2), p, rtol=0, atol=1e-9,
                                           err_msg=f"{name} {w!r}")


LONG = ("It was the best of times, it was the worst of times, it was the age of wisdom, it was the "
        "age of foolishness. Quick brown foxes jump over lazy dogs! 1234567890 £5 & 10% (yes) "
        "\"quoted\" a/b @home #1 x+y=z *")


def page_cases():
    cases = []
    for i, s in enumerate(STYLES):
        cases += [
            (s, "Dear friend,\nThank you for everything.",
             dict(size=6, page="a5-landscape", margin=15, seed=3, shade=0.6)),
            (s, LONG, dict(size=5, page="a4", margin=20, seed=i)),
            (s, "Hello\n\nWorld of Script\n  indented  words ",
             dict(size=8, page="200x120", margin=10, seed=11, align="center", valign="middle", variation=2.0)),
            (s, "minimum running elegant handwriting cursive",
             dict(size=4, page="letter", margin=12, seed=7, align="right", valign="bottom", pen=0.5, shade=0.4)),
            (s, "    Two  spaces,   three   and\ta tab;\u00a0\u3000odd ones     at a wrap point too",
             dict(size=9, page="a5", margin=10, seed=5)),
            (s, "Zebra Quilt Xylophone Juggling Kites <&>",
             dict(size=7, page="dl", margin=8, seed=123456789, variation=0.0, pen=1.0)),
            (s, "Little letters: coffee, butter, attitude, Mississippi, Llanelli, Wattt, AAh",
             dict(size=6, page="a5-landscape", margin=12, seed=21 + i)),
        ]
    return cases


def python_page(name, text, o):
    o = dict(size=6.0, page="a4", margin=20.0, align="left", valign="top", seed=0, variation=1.0, pen=0.35,
             shade=0.0) | o
    pw, ph = page_size(o["page"])
    _, mm = make_page(text, Style.load(name), size=o["size"], page=(pw, ph), margin=o["margin"],
                      align=o["align"], valign=o["valign"], seed=o["seed"], variation=o["variation"],
                      pen=o["pen"], shade=o["shade"])
    return mm, to_svg(mm, (pw, ph), float(o["pen"]), title=text[:60])


@needs_js
def test_pages_are_byte_identical(js_tmp):
    cases = page_cases()
    js = run_js([{"op": "page", "style": s, "text": t, "opts": o} for s, t, o in cases], js_tmp)
    for (name, text, o), got in zip(cases, js):
        mm, svg = python_page(name, text, o)
        assert [[len(p) for p in ln] for ln in got["mm"]] == [[len(p) for p in ln] for ln in mm], (name, text)
        for ln, jln in zip(mm, got["mm"]):
            for p, q in zip(ln, jln):
                np.testing.assert_allclose(np.asarray(q, float).reshape(-1, 2), p, rtol=0, atol=1e-8)
        assert got["svg"] == svg, (name, text)


# ------------------------------------------------------------------ licences

# What any copy of the style data or the page must carry
OFL_MARKERS = ["SIL OPEN FONT LICENSE Version 1.1", "PERMISSION & CONDITIONS", "Reserved Font Name"]
MIT_MARKER = "Permission is hereby granted, free of charge"
NOTICE_MARKERS = ["NumPy Developers", "Kevin Sheppard", "Melissa O'Neill", "Jeff Bezanson"]


def required_notices(names):
    return [*OFL_MARKERS, MIT_MARKER, *NOTICE_MARKERS, *(build_web.font_copyright(n) for n in names)]


def test_every_style_has_its_font_licence():
    for name in STYLES:
        assert build_web.font_copyright(name).startswith("Copyright"), name
    text = build_web.styles_license()
    for marker in OFL_MARKERS:
        assert marker in text


def test_served_page_carries_the_notices():
    text = build_web.WEB_LICENSES.read_text()
    for marker in required_notices(STYLES):
        assert marker in text, marker
    assert 'href="LICENSES.txt"' in (ROOT / "web" / "index.html").read_text()
    for name in STYLES:
        b = json.loads((build_web.OUT / f"{name}.json").read_text())
        assert b["copyright"][0] == build_web.font_copyright(name) and "Open Font License" in b["license"]


# ------------------------------------------------------------------ single file


@pytest.fixture(scope="module")
def standalone(js_tmp):
    path = js_tmp / "cursive-writer.html"
    path.write_text(build_web.standalone_html())
    return path


def test_standalone_page_is_self_contained(standalone):
    html = standalone.read_text()
    # nothing to fetch: every src and <link> href is inline data or an in-page
    # anchor; plain <a> links (the repo, the release) may point at the web
    refs = re.findall(r'src="([^"]*)"', html) + re.findall(r'<link\b[^>]*\bhref="([^"]*)"', html)
    assert all(r.startswith(("data:", "#")) for r in refs), refs
    links = re.findall(r'<a\b[^>]*\bhref="([^"]*)"', html)
    assert all(r.startswith(("#", "https://")) for r in links), links
    for name in STYLES:
        assert f'"{name}":{{"name":"{name}"' in html


@pytest.mark.parametrize("names", [None, ["modern"]])
def test_standalone_page_carries_the_licences(names):
    """Sharing only the HTML file must still meet the OFL and MIT conditions."""
    import html as html_mod

    page = build_web.standalone_html(names)
    m = re.search(r'<details id="licences"[^>]*>([\s\S]*?)</details>', page)
    assert m, "no visible licences section"
    shown = html_mod.unescape(m[1])
    for marker in required_notices(names or STYLES):
        assert marker in shown, marker
    head = page[:page.index("<html")]
    for name in names or STYLES:
        assert build_web.font_copyright(name) in head


@needs_js
def test_standalone_engine_writes_the_same_pages(js_tmp, standalone):
    cases = page_cases()[::2] + [("modern", "x", dict(seed=1))]
    req = js_tmp / "standalone-requests.json"
    req.write_text(json.dumps([{"style": s, "text": t, "opts": o} for s, t, o in cases]))
    out = subprocess.run([*RUNTIME, str(ROOT / "web" / "test" / "standalone_runner.js"), str(standalone), str(req)],
                         capture_output=True, text=True, cwd=ROOT, timeout=600)
    assert out.returncode == 0, out.stderr
    for (name, text, o), got in zip(cases, json.loads(out.stdout)):
        assert got.get("svg") == python_page(name, text, o)[1], (name, text, got.get("error"))


@needs_js
def test_supported_and_missing_characters_match(js_tmp):
    from cursive.glyph import missing_chars_warning

    texts = ["Café — naïve €5 «ok» 𝒜 ß\tend", "plain text, nothing missing!", "éé è é"]
    cases = [(s, t) for s in STYLES for t in texts]
    got = run_js([{"op": "chars", "style": s, "text": t} for s, t in cases], js_tmp)
    for (name, text), js in zip(cases, got):
        st = Style.load(name)
        missing = st.missing_chars(text)
        assert js["groups"] == [list(gr) for gr in st.char_groups()], name
        assert js["missing"] == missing, (name, text)
        assert js["warning"] == (missing_chars_warning(st.name, missing) if missing else None)
