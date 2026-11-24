"""Bundle each style for the web page (web/index.html).

The browser cannot list a directory, so each styles/<name>/ is gathered into
one file, web/data/<name>.json, holding the same style.json, pairs.json and
glyph files the Python engine reads. Numbers are copied unchanged; only
bookkeeping fields the engine never reads (glyph "source"/"note"/"edited",
pair "score"/"was"/"note"/"manual") are left out to keep downloads small.

    python tools/build_web.py           # all styles
    python tools/build_web.py --check   # exit 1 if a bundle is out of date

Re-run after editing glyphs, style.json or pairs.json.

It also writes the licence files that must travel with the style data, which
is derived from fonts under the SIL Open Font License: styles/LICENSE.md and
web/LICENSES.txt (everything: MIT for the code, OFL for the styles, and the
third-party notices). The standalone page carries the same text inside it.

It can also write the whole page as one self-contained HTML file, with the
CSS, the JavaScript engine and the style data inside, to share or open
straight from disk (no web server needed):

    python tools/build_web.py --standalone                 # dist/cursive-writer.html
    python tools/build_web.py --standalone card.html modern copperplate
"""

from __future__ import annotations

import argparse
import html as _html
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
STYLES = ROOT / "styles"
WEB = ROOT / "web"
OUT = WEB / "data"
STANDALONE_OUT = ROOT / "dist" / "cursive-writer.html"
FONTS = ROOT / "fonts"
STYLES_LICENSE = STYLES / "LICENSE.md"
WEB_LICENSES = WEB / "LICENSES.txt"
AUTHOR = "unigamer"  # as in LICENSE
YEAR = 2026

GLYPH_KEYS = ("char", "advance", "strokes", "lead_in", "lead_out", "entry", "exit", "hook_retrace", "final_trim")
PAIR_KEYS = ("join", "dx", "lead_out", "lead_in", "tension", "arrive", "over")  # what join.pair_params reads


def style_names() -> list[str]:
    return sorted(p.name for p in STYLES.iterdir() if (p / "glyphs").is_dir())


# ------------------------------------------------------------------ licences


def _style_meta(name: str) -> dict:
    f = STYLES / name / "style.json"
    return json.loads(f.read_text()) if f.exists() else {}


def font_license_file(name: str) -> Path:
    """fonts/OFL-<font>.txt for the font a style was traced from."""
    src = _style_meta(name).get("source_font", "")
    family = re.sub(r"[-_ ].*$", "", src.split(".")[0]).lower()  # PinyonScript-Regular.ttf -> pinyonscript
    for f in FONTS.glob("OFL-*.txt"):
        if f.stem[4:].lower().replace("-", "") == family:
            return f
    raise SystemExit(f"styles/{name}: no fonts/OFL-*.txt licence for source_font {src!r}")


def font_copyright(name: str) -> str:
    """The font's copyright statement: the lines before the licence text."""
    head = font_license_file(name).read_text().split("This Font Software is licensed")[0]
    return " ".join(line.strip() for line in head.splitlines() if line.strip())


def _ofl_text() -> str:
    """SIL Open Font License 1.1, from the font licence files."""
    texts = {font_license_file(n).read_text().split("This Font Software is licensed", 1)[1] for n in style_names()}
    body = min(texts, key=lambda s: ("openfontlicense.org" not in s, s))  # prefer the current URL
    return "This Font Software is licensed" + body.rstrip() + "\n"


def styles_license() -> str:
    """styles/LICENSE.md: the style data is a modified version of OFL fonts."""
    rfns = [m for n in style_names() for m in re.findall(r'Reserved Font Names? "?([^".,]+)', font_copyright(n))]
    quoted = [f'"{r.strip()}"' for r in rfns]
    reserved = (", ".join(quoted[:-1]) + " and " + quoted[-1]) if len(quoted) > 1 else (quoted[0] if quoted else "none here")
    lines = [
        "# Licence for the style data",
        "",
        "The glyph skeletons, joins and spacing in `styles/` (and the copies of them",
        "in `web/data/` and in any page built by `tools/build_web.py`) were traced",
        "from the fonts listed below and then edited. That makes them Modified",
        "Versions of those fonts under the SIL Open Font License, Version 1.1, so",
        "they are licensed under the same licence, reproduced at the end.",
        "",
        "In short: they may be used, modified and redistributed, also commercially",
        "and bundled with any software, but not sold on their own; each copy must",
        "keep these notices and the licence; and a modified version must not be",
        f"called by a Reserved Font Name ({reserved}),",
        "which is why the styles have their own names.",
        "",
        "Writing produced with these styles (SVG, PNG, plotted ink) is not covered",
        "by the licence and may be used freely.",
        "",
    ]
    for name in style_names():
        meta = _style_meta(name)
        lines += [
            f"## {meta.get('name', name)} (`styles/{name}/`)",
            "",
            f"Traced from {meta.get('source_font', '?')}.",
            "",
            f"- Original font: {font_copyright(name)}",
            f"- Modifications: Copyright (c) {YEAR} {AUTHOR}",
            "",
        ]
    lines += ["## SIL Open Font License, Version 1.1", "", "```", _ofl_text().rstrip(), "```", ""]
    return "\n".join(lines)


def licenses_text() -> str:
    """Every licence that applies to the web page, as one plain-text file."""
    rule = "\n" + "=" * 78 + "\n\n"
    return rule.join([
        "Cursive Writer: licences\n\n"
        "- The program (the Python and JavaScript code and the web page) is under\n"
        "  the MIT License, below.\n"
        "- The script style data is derived from fonts under the SIL Open Font\n"
        "  License 1.1; the font copyrights and that licence follow.\n"
        "- Parts of the JavaScript engine are ported from numpy; their notices\n"
        "  come last.\n"
        "- Writing you make with it is yours; none of these licences cover it.\n",
        (ROOT / "LICENSE").read_text(),
        styles_license(),
        (ROOT / "THIRD_PARTY_NOTICES.md").read_text(),
    ])


def bundle(name: str) -> dict:
    d = STYLES / name
    style = json.loads((d / "style.json").read_text()) if (d / "style.json").exists() else {}
    pairs = json.loads((d / "pairs.json").read_text()).get("pairs", {}) if (d / "pairs.json").exists() else {}
    glyphs = []
    for f in sorted((d / "glyphs").glob("*.json")):
        gl = json.loads(f.read_text())
        glyphs.append([f.name, {k: gl[k] for k in GLYPH_KEYS if k in gl}])
    return {
        "name": name,
        "license": "SIL Open Font License 1.1 (see LICENSES.txt); modified version of the font below",
        "copyright": [font_copyright(name), f"Modifications: Copyright (c) {YEAR} {AUTHOR}"],
        "style": style,
        "pairs": {k: {kk: v[kk] for kk in PAIR_KEYS if kk in v} for k, v in pairs.items()},
        "glyphs": glyphs,
    }


def render(name: str) -> str:
    return json.dumps(bundle(name), separators=(",", ":"), ensure_ascii=False) + "\n"


def index() -> str:
    styles = []
    for name in style_names():
        meta = json.loads((STYLES / name / "style.json").read_text()) if (STYLES / name / "style.json").exists() else {}
        styles.append({"id": name, "name": meta.get("name", name), "source_font": meta.get("source_font", "")})
    return json.dumps({"styles": styles}, indent=1, ensure_ascii=False) + "\n"


# ------------------------------------------------------------------ single file

_IMPORT = re.compile(r'^import (?:\* as (\w+)|\{([^}]*)\}) from "\./([\w/]+)\.js";$')
_REEXPORT = re.compile(r'^export \{([^}]*)\} from "\./([\w/]+)\.js";$')
_EXPORT_LIST = re.compile(r'^export \{([^}]*)\};$')
_EXPORT_DECL = re.compile(r'^export (?:async )?(?:function\*?|const|let|class) (\w+)')


def _names(spec: str) -> list[tuple[str, str]]:
    """'a, b as c' -> [('a', 'a'), ('b', 'c')]"""
    out = []
    for part in filter(None, (s.strip() for s in spec.split(","))):
        src, _, dst = part.partition(" as ")
        out.append((src.strip(), (dst or src).strip()))
    return out


def _module_id(base: str, rel: str) -> str:
    parts = [*base.split("/")[:-1], *rel.split("/")]
    out = []
    for s in parts:
        if s == "..":
            out.pop()
        elif s not in (".", ""):
            out.append(s)
    return "/".join(out)


def bundle_js(entry: str = "worker") -> str:
    """Join web/<entry>.js and the modules it imports into one classic script.

    A tiny module loader, enough for the plain import/export forms the engine
    uses (anything else is an error, so the build cannot silently go wrong).
    Each module runs in its own function scope; its exports are getters until
    the module finishes, which keeps the circular style.js <-> join.js imports
    working just as in the browser's own loader.
    """
    mods: dict[str, str] = {}
    todo = [entry]
    while todo:
        mid = todo.pop()
        if mid in mods:
            continue
        exports: list[tuple[str, str]] = []  # (exported name, expression)
        body = []
        for line in (WEB / f"{mid}.js").read_text().splitlines():
            if m := _IMPORT.match(line):
                dep = _module_id(mid, m[3])
                todo.append(dep)
                if m[1]:
                    body.append(f"const {m[1]} = __require({dep!r});")
                else:
                    pairs = ", ".join(s if s == d else f"{s}: {d}" for s, d in _names(m[2]))
                    body.append(f"const {{ {pairs} }} = __require({dep!r});")
            elif m := _REEXPORT.match(line):
                dep = _module_id(mid, m[2])
                todo.append(dep)
                exports += [(d, f"__require({dep!r}).{s}") for s, d in _names(m[1])]
            elif m := _EXPORT_LIST.match(line):
                exports += [(d, s) for s, d in _names(m[1])]
            elif m := _EXPORT_DECL.match(line):
                exports.append((m[1], m[1]))
                body.append(line[len("export "):])
            elif re.match(r"\s*(import|export)\b", line) or "import.meta" in line:
                raise ValueError(f"web/{mid}.js: the single-file build cannot handle: {line.strip()}")
            else:
                body.append(line)
        getters = "".join(f"\n  __export(__e, {n!r}, () => {x});" for n, x in exports)
        done = "".join(f"\n  __seal(__e, {n!r}, {x});" for n, x in exports)
        mods[mid] = f"__modules[{mid!r}] = (__e) => {{{getters}\n" + "\n".join(body) + f"{done}\n}};\n"
    loader = """\
const __modules = {}, __loaded = {};
const __require = (id) => {
  if (!(id in __loaded)) __modules[id]((__loaded[id] = {}));
  return __loaded[id];
};
const __export = (e, k, get) => Object.defineProperty(e, k, { get, enumerable: true, configurable: true });
const __seal = (e, k, v) => Object.defineProperty(e, k, { value: v, enumerable: true });
"""
    return "(() => {\n\"use strict\";\n" + loader + "".join(mods[m] for m in sorted(mods)) + f"__require({entry!r});\n}})();\n"


def _inline_safe(text: str, what: str) -> str:
    """Text placed inside <script> must not close it early."""
    low = text.lower()
    if "</script" in low or "<!--" in low:
        raise ValueError(f"{what} contains </script or <!-- and cannot be inlined")
    return text


def engine_js(names: list[str]) -> str:
    """The worker as one classic script, with these styles' data built in."""
    data = {n: bundle(n) for n in names}
    js = json.dumps(data, separators=(",", ":"), ensure_ascii=False).replace("</", "<\\/")
    return f"self.CURSIVE_BUNDLES = {js};\n" + bundle_js("worker")


def standalone_html(names: list[str] | None = None) -> str:
    """The web page as a single HTML file needing no server and no network."""
    names = names or style_names()
    unknown = set(names) - set(style_names())
    if unknown:
        raise SystemExit(f"unknown style(s): {', '.join(sorted(unknown))}")
    styles = [s for s in json.loads(index())["styles"] if s["id"] in names]
    html = (WEB / "index.html").read_text()
    css = _inline_safe((WEB / "app.css").read_text(), "app.css")
    blocks = "\n".join([
        '<script type="application/json" id="cursive-styles">'
        + json.dumps({"styles": styles}, ensure_ascii=False).replace("</", "<\\/") + "</script>",
        '<script type="text/plain" id="cursive-engine">' + _inline_safe(engine_js(names), "the engine") + "</script>",
        "<script>\n" + _inline_safe((WEB / "standalone.js").read_text(), "standalone.js") + "</script>",
        '<script type="module">\n' + _inline_safe((WEB / "app.js").read_text(), "app.js") + "</script>",
    ])
    notice = ("<!--\n  Cursive Writer. Code: MIT License. Script style data: modified versions of\n"
              "  fonts under the SIL Open Font License 1.1:\n"
              + "".join(f"    {font_copyright(n)}\n" for n in names)
              + "  Full licence texts and notices: the \"Licences\" section at the end of\n"
              "  this page (element #licences).\n-->\n")
    licences = (f'<details id="licences" class="licences">\n<summary>Licences</summary>\n'
                f"<pre>{_html.escape(licenses_text(), quote=False)}</pre>\n</details>\n")
    for old, new in [("<!doctype html>\n", "<!doctype html>\n" + notice),
                     ('<link rel="stylesheet" href="app.css">', f"<style>\n{css}</style>"),
                     ('href="LICENSES.txt"', 'href="#licences"'),
                     ("</footer>", "</footer>\n" + licences),
                     ('<script type="module" src="app.js"></script>', blocks)]:
        if html.count(old) != 1:
            raise ValueError(f"web/index.html no longer contains {old!r}")
        html = html.replace(old, new)
    return html


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("styles", nargs="*", help="styles to bundle (default: all)")
    ap.add_argument("--check", action="store_true", help="only check that bundles are up to date")
    ap.add_argument("--standalone", nargs="?", const=STANDALONE_OUT, type=Path, metavar="HTML",
                    help=f"write the page as one self-contained HTML file (default {STANDALONE_OUT.relative_to(ROOT)})")
    args = ap.parse_args(argv)
    if args.standalone:
        text = standalone_html(args.styles)
        args.standalone.parent.mkdir(parents=True, exist_ok=True)
        args.standalone.write_text(text)
        print(f"{args.standalone}: {len(text.encode()) / 1024:.0f} KB")
        return 0
    names = args.styles or style_names()
    files = {OUT / f"{n}.json": render(n) for n in names}
    if not args.styles:
        files[OUT / "index.json"] = index()
        files[STYLES_LICENSE] = styles_license()
        files[WEB_LICENSES] = licenses_text()
    stale = [p for p, text in files.items() if not p.exists() or p.read_text() != text]
    if args.check:
        for p in stale:
            print(f"out of date: {p.relative_to(ROOT)}", file=sys.stderr)
        if stale:
            print("run: python tools/build_web.py", file=sys.stderr)
        return 1 if stale else 0
    OUT.mkdir(parents=True, exist_ok=True)
    for p, text in files.items():
        p.write_text(text)
        print(f"{p.relative_to(ROOT)}: {len(text) / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
