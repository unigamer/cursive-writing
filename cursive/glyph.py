"""Glyph and style data (JSON on disk).

Coordinates are in x-height units: baseline y=0, x-height y=1, y up, and the
glyph's pen origin at x=0. Each glyph file holds:

    char      the character
    advance   pen advance to the next glyph origin
    strokes   [{points: [[x,y],...], deferred: bool, kind: "line"|"dot"}]
              strokes[0] is the main (joining) stroke; deferred strokes such as
              i-dots and t-bars are drawn after the word
    lead_in   arc length of the entry hairline on the main stroke, replaced
              by the connector when this glyph is joined from the left
    lead_out  arc length of the exit hairline, replaced when joined rightwards
    entry     "low" | "mid" | "high" | "none"   ("none" = never joined into)
    exit      "low" | "high" | "none"            ("none" = never joins onward)

Variants live beside the main file:
    <name>.alt1.json, <name>.alt2.json   alternates, picked at random
    <name>.init.json                    form used at the start of a word
    <name>.fina.json                    form used at the end of a word
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

STYLES_DIR = Path(__file__).resolve().parents[1] / "styles"
# An unjoined capital is kerned to this fraction of the letter gap: with no
# connector bridging it, a full letter gap after a capital reads as too wide.
CAPITAL_GAP = 0.72
# Neighbouring words keep at least this fraction of the letter gap between
# their ink (never less than 0.3): any closer and two words read as one.
WORD_CLEAR = 0.9


def glyph_name(ch: str) -> str:
    if ch.isascii() and ch.islower():
        return ch
    if ch.isascii() and ch.isupper():
        return f"{ch}_cap"
    if ch.isdigit():
        return f"digit{ch}"
    return f"u{ord(ch):04X}"


def glyph_filename(ch: str, alt: int = 0) -> str:
    return f"{glyph_name(ch)}{f'.alt{alt}' if alt else ''}.json"


@dataclass
class Stroke:
    points: np.ndarray
    deferred: bool = False
    kind: str = "line"


@dataclass
class Glyph:
    char: str
    advance: float
    strokes: list[Stroke]
    lead_in: float = 0.0
    lead_out: float = 0.0
    entry: str = "low"
    exit: str = "low"
    hook_retrace: bool = False  # when joined, re-draw the cut lead-in as a flick out and back
    final_trim: float = 0.0  # arc length trimmed from the exit tail when the glyph ends a word

    @property
    def main(self) -> Stroke:
        return self.strokes[0]

    @property
    def deferred(self) -> list[Stroke]:
        return self.strokes[1:]

    @classmethod
    def from_dict(cls, d: dict) -> "Glyph":
        strokes = [
            Stroke(np.asarray(s["points"], float), bool(s.get("deferred", i > 0)), s.get("kind", "line"))
            for i, s in enumerate(d["strokes"])
        ]
        return cls(
            char=d["char"],
            advance=float(d["advance"]),
            strokes=strokes,
            lead_in=float(d.get("lead_in", 0.0)),
            lead_out=float(d.get("lead_out", 0.0)),
            entry=d.get("entry", "low"),
            exit=d.get("exit", "low"),
            hook_retrace=bool(d.get("hook_retrace", False)),
            final_trim=float(d.get("final_trim", 0.0)),
        )


def form_of(stem: str) -> str:
    """'e' -> 'base', 'e.alt2' -> 'base' (alternate), 'e.fina' -> 'fina', 'b.init' -> 'init'."""
    parts = stem.split(".")[1:]
    for f in ("init", "fina"):
        if f in parts:
            return f
    return "base"


@dataclass
class Style:
    name: str
    glyphs: dict[str, list[Glyph]]  # char -> [main, alternates...]
    forms: dict[tuple[str, str], list[Glyph]] = field(default_factory=dict)  # (char, "init"/"fina") -> glyphs
    slant: float = 0.0  # extra shear (degrees, positive = lean right)
    tracking: float = 0.0  # extra space between glyphs, x-height units
    word_space: float = 0.9
    line_height: float = 4.0
    tension: float = 0.45
    glyph_slant: float = 0.0  # the glyphs' own slant (dx/dy), measured at extraction
    no_join_pairs: set[str] = field(default_factory=set)  # e.g. {"Bo", "Gx"}
    no_join_after: set[str] = field(default_factory=set)  # never join after these chars
    no_join_before: set[str] = field(default_factory=set)  # never join into these chars
    variation: dict = field(default_factory=dict)
    use_forms: bool = True  # use init/fina forms when the style has them
    pairs: dict = field(default_factory=dict)  # per-pair join overrides (pairs.json)
    letter_gap: float = 0.6  # body gap between letters (even_spacing), also used to kern unjoined pairs
    word_clear: float = 0.54  # least ink distance between words before one is pushed (layout.py)
    capital_gap: float = 0.432  # body gap after a capital that doesn't join (default 0.72 x letter_gap)
    join_capitals: str = ""  # capitals that traditionally join to the next letter
    counter_width: float = 0.0  # narrow end (5th percentile) of letter counters, x-heights
    # (measured by tools/legibility.py --save; 0 = unknown)

    @classmethod
    def load(cls, name_or_path: str | Path) -> "Style":
        p = Path(name_or_path)
        if not p.exists():
            p = STYLES_DIR / str(name_or_path)
        meta = json.loads((p / "style.json").read_text()) if (p / "style.json").exists() else {}
        glyphs: dict[str, list[Glyph]] = {}
        forms: dict[tuple[str, str], list[Glyph]] = {}
        for f in sorted((p / "glyphs").glob("*.json")):
            gl = Glyph.from_dict(json.loads(f.read_text()))
            form = form_of(f.stem)
            if form != "base":
                forms.setdefault((gl.char, form), []).append(gl)
                continue
            glyphs.setdefault(gl.char, [])
            if ".alt" in f.stem:
                glyphs[gl.char].append(gl)
            else:
                glyphs[gl.char].insert(0, gl)
        style = cls(
            name=meta.get("name", p.name),
            glyphs=glyphs,
            forms=forms,
            slant=float(meta.get("slant", 0.0)),
            tracking=float(meta.get("tracking", 0.0)),
            word_space=float(meta.get("word_space", 0.9)),
            line_height=float(meta.get("line_height", 4.0)),
            tension=float(meta.get("tension", 0.45)),
            glyph_slant=float(meta.get("glyph_slant", 0.0)),
            no_join_pairs=set(meta.get("no_join_pairs", [])),
            no_join_after=set(meta.get("no_join_after", "")),
            no_join_before=set(meta.get("no_join_before", "")),
            variation=meta.get("variation", {}),
            letter_gap=float(meta.get("even_spacing", 0.6)),
            word_clear=float(meta.get("word_clear", max(0.3, WORD_CLEAR * float(meta.get("even_spacing", 0.6))))),
            capital_gap=float(meta.get("capital_gap", CAPITAL_GAP * float(meta.get("even_spacing", 0.6)))),
            counter_width=float(meta.get("counter_width", 0.0)),
            join_capitals=meta.get("join_capitals", ""),
        )
        if (p / "pairs.json").exists():
            style.pairs = json.loads((p / "pairs.json").read_text()).get("pairs", {})
        if meta.get("even_spacing"):
            from .spacing import apply_even_spacing  # local import: spacing uses join

            apply_even_spacing(style, float(meta["even_spacing"]), "abcdefghijklmnopqrstuvwxyz")
        return style

    def options(self, ch: str, position: str) -> list[Glyph]:
        """Glyph choices for `ch` at `position` ("init", "medi", "fina", "isol")."""
        if self.use_forms and position in ("init", "fina") and (ch, position) in self.forms:
            return self.forms[(ch, position)]
        return self.glyphs.get(ch, [])

    def can_join(self, a: Glyph, b: Glyph) -> bool:
        if not (a.char.isalpha() and b.char.isalpha()):
            return False  # digits, punctuation and symbols always stand alone
        if a.exit == "none" or b.entry == "none":
            return False
        if a.char in self.no_join_after or b.char in self.no_join_before:
            return False
        return (a.char + b.char) not in self.no_join_pairs
