"""Local glyph editor.

    python tools/editor.py [--port 8765]

then open http://localhost:8765 . Edits are previewed live in joined words
using the real join engine; "Save" writes the glyph JSON (marked "edited" so
re-extraction leaves it alone) and keeps a timestamped backup.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from cursive.glyph import STYLES_DIR, Glyph, Style  # noqa: E402
from cursive.layout import place_word  # noqa: E402
from cursive.variation import Variation  # noqa: E402

HTML = Path(__file__).with_name("editor.html")
_styles: dict[str, Style] = {}


def style_dir(name: str) -> Path:
    d = (STYLES_DIR / name).resolve()
    if STYLES_DIR.resolve() not in d.parents or not (d / "glyphs").is_dir():
        raise ValueError(f"unknown style {name!r}")
    return d


def get_style(name: str, reload: bool = False) -> Style:
    if reload or name not in _styles:
        _styles[name] = Style.load(style_dir(name))
    return _styles[name]


def preview(style_name: str, text: str, override: dict | None, variation: float, seed: int):
    style = get_style(style_name)
    overrides = None
    if override:
        gl = Glyph.from_dict(override)
        overrides = {gl.char: gl}
    lines = []
    for line in text.split("\n"):
        words = []
        for k, w in enumerate(line.split()):
            word, _ = place_word(w, style, Variation(style.variation, seed + k, variation), overrides)
            words.append([[np.round(p, 4).tolist(), kind, i] for p, kind, i in word.pieces])
        lines.append(words)
    return {"lines": lines, "slant": style.glyph_slant, "word_space": style.word_space}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass

    def _send(self, code: int, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        u = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(u.query).items()}
        try:
            if u.path == "/":
                return self._send(200, HTML.read_bytes(), "text/html; charset=utf-8")
            if u.path == "/api/styles":
                names = sorted(p.name for p in STYLES_DIR.iterdir() if (p / "glyphs").is_dir())
                return self._send(200, names)
            if u.path == "/api/style":
                d = style_dir(q["name"])
                glyphs = {f.stem: json.loads(f.read_text()) for f in sorted((d / "glyphs").glob("*.json"))}
                meta = json.loads((d / "style.json").read_text()) if (d / "style.json").exists() else {}
                return self._send(200, {"meta": meta, "glyphs": glyphs})
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"error": str(e)})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if u.path == "/api/preview":
                return self._send(200, preview(body["style"], body["text"], body.get("glyph"),
                                               float(body.get("variation", 0)), int(body.get("seed", 0))))
            if u.path == "/api/save":
                d = style_dir(body["style"])
                stem = Path(body["file"]).name
                if not stem.replace(".", "").replace("_", "").isalnum():
                    raise ValueError("bad file name")
                f = d / "glyphs" / f"{stem}.json"
                if f.exists():
                    bak = d / ".backup"
                    bak.mkdir(exist_ok=True)
                    shutil.copy2(f, bak / f"{stem}.{time.strftime('%Y%m%d-%H%M%S')}.json")
                glyph = body["glyph"]
                glyph["edited"] = True
                Glyph.from_dict(glyph)  # validate
                f.write_text(json.dumps(glyph, indent=1))
                get_style(body["style"], reload=True)
                return self._send(200, {"ok": True, "file": str(f.relative_to(ROOT))})
            if u.path == "/api/save_meta":
                d = style_dir(body["style"])
                (d / "style.json").write_text(json.dumps(body["meta"], indent=2) + "\n")
                get_style(body["style"], reload=True)
                return self._send(200, {"ok": True})
            return self._send(404, {"error": "not found"})
        except Exception as e:  # noqa: BLE001
            return self._send(400, {"error": f"{type(e).__name__}: {e}"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"glyph editor on http://localhost:{args.port}  (Ctrl+C to stop)")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
