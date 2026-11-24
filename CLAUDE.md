# CLAUDE.md

Text in, joined single-line cursive SVG out, for pen plotters. A Python engine (`cursive/`) and a byte-identical JavaScript port of it (`web/cursive/`) that runs the static web page. README.md has the full design notes.

## Commands

```sh
.venv/bin/pip install -e ".[dev,extract]"      # setup (extract extras only needed for tools/extract_glyphs.py)
.venv/bin/python -m pytest -q                   # all tests; tests/test_web.py needs deno or node, else skips
.venv/bin/python tools/build_web.py             # rebuild web/data/ + licence files after any styles/ edit
.venv/bin/python tools/build_web.py --check     # what CI runs: fails if web/data/ is stale
.venv/bin/python tools/build_web.py --standalone   # single-file page -> dist/cursive-writer.html
python3 -m http.server -d web 8000              # serve the web page (won't work from file://)
.venv/bin/python -m cursive.cli "Hello" --style copperplate -o out.svg --png out.png
```

Style tuning tools: `tools/editor.py` (glyph editor, port 8765), `tools/compose_glyphs.py` (accented letters), `tools/sheets.py`, `tools/audit.py`, `tools/pairs.py optimise|stats|sheet|kern`, `tools/review.py`, `tools/legibility.py`.

## Releasing

Publishing a GitHub release triggers `.github/workflows/release.yml`: tests, `build_web.py --check`, builds the standalone page, attaches `cursive-writer.html` to the release, deploys GitHub Pages and appends both links to the release notes.

```sh
# bump `version` in pyproject.toml first if needed, commit and push to main, then:
gh release create vX.Y.Z --target main --title "vX.Y.Z" --generate-notes
```

To redeploy the Pages site without a release: `gh workflow run release.yml` (the release-asset steps are skipped).

Run the tests and `build_web.py --check` locally before releasing; a failure in CI means no page is published.

## Rules

- **Keep Python and JS in lockstep.** Any change to runtime code in `cursive/` (glyph, join, variation, layout, spacing, shade, render) must be mirrored in `web/cursive/`. `tests/test_web.py` checks byte-identical SVG and the numpy-exact RNG in `web/cursive/rng.js`; don't "simplify" rounding or summation order there.
- **After editing anything in `styles/`, re-run `tools/build_web.py`** and commit the regenerated `web/data/`, `styles/LICENSE.md` and `web/LICENSES.txt`.
- After editing a base letter, re-run `tools/compose_glyphs.py <style>` so its accented copies (é, è, ê…) follow; tests fail while they are stale. Never hand-edit composed glyphs (`"base"` set): edit the base letter or `marks.json`.
- After editing glyphs, re-run `tools/pairs.py optimise <style>`. Never overwrite pair entries marked `"manual": true` or glyphs marked `"edited"`.
- After changing `even_spacing` or `capital_gap` in a `style.json` (or after `optimise`), re-run `tools/pairs.py kern <style>` so unjoined pairs are re-kerned.
- Judge visual changes by rendering PNGs (`tools/sheets.py`, `--png`); there is no plotter available to test on.
- Licensing: code is MIT, style data is OFL-1.1. The standalone HTML must carry all notices (build_web.py embeds them, tests enforce). Style names must not use the fonts' Reserved Font Names (Parisienne, Petit Formal Script, Monsieur La Doulaise).
- Don't write plotter trademark names in code, docs or UI; say "pen plotter".
- Don't commit unless asked.
