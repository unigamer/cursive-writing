"""Seeded, natural-looking variation so no two letters are identical.

Two levels:
  * per-glyph affine jitter (size, width, slant, baseline) applied before
    joining, so connectors adapt to the jittered letters;
  * a smooth low-frequency displacement field applied to whole lines after
    joining, which wobbles strokes without ever breaking a join.

Amplitudes come from the style's "variation" block; `amount` scales them all.

Doubled letters (ll, ee, ss) are where identical copies give machine writing
away, so the second of a pair never reuses the first's alternate and its
size, width, slant and loop draws are kept at least `repeat_apart` std-devs
from the first's (see `_apart`). This moves values only, never adds random
draws, so the rest of the text is unchanged.
"""

from __future__ import annotations

import numpy as np

DEFAULTS = {
    "size": 0.03,  # relative std-dev of glyph height
    "width": 0.04,  # relative std-dev of glyph width
    "slant": 0.03,  # std-dev of extra shear (dx/dy)
    "baseline": 0.03,  # std-dev of baseline offset, x-heights
    "spacing": 0.03,  # std-dev of advance change, x-heights
    "wobble": 0.012,  # amplitude of smooth displacement field, x-heights
    "wobble_scale": 1.6,  # wavelength of the field, x-heights
    "drift": 0.04,  # slow baseline drift amplitude across a line, x-heights
    "loop_width": 0.08,  # relative std-dev of ascender/descender loop width
    "loop_height": 0.04,  # relative std-dev of ascender height / descender depth
    "flourish": 0.35,  # chance a word-final letter gets a longer finishing hairline
    "repeat_apart": 1.0,  # a doubled letter (ll, ee, ss) differs from the first by at least this many std-devs
}


class Variation:
    def __init__(self, params: dict | None, seed: int | None, amount: float = 1.0):
        self.p = {**DEFAULTS, **(params or {})}
        self.amount = amount
        self.rng = np.random.default_rng(seed)
        self.repeat = False  # set by place_word while drawing the second of a doubled letter
        self._last: dict[str, float] = {}  # the previous letter's draws, by slot

    def _n(self, key: str) -> float:
        return float(self.rng.normal(0.0, self.p[key] * self.amount))

    def _apart(self, slot: str, key: str) -> float:
        """A `key` draw for `slot`, kept `repeat_apart` std-devs from the
        previous letter's draw for that slot when this letter repeats it."""
        v = self._n(key)
        s = self.p["repeat_apart"] * self.p[key] * self.amount
        if self.repeat and slot in self._last and s > 0:
            d = v - self._last[slot]
            if abs(d) < s:
                v = self._last[slot] + (s if d >= 0 else -s)
        self._last[slot] = v
        return v

    def glyph_transform(self):
        """Return (matrix 2x2, offset 2, extra advance)."""
        sy = 1.0 + self._apart("size", "size")
        sx = sy * (1.0 + self._apart("width", "width"))
        shear = self._apart("slant", "slant")
        m = np.array([[sx, shear * sy], [0.0, sy]])
        off = np.array([0.0, self._n("baseline")])
        return m, off, self._n("spacing")

    def loop_warp(self, main: np.ndarray, slant: float):
        """A per-letter reshaping of ascender and descender loops (lowercase):
        their width and length vary a little, as in handwriting, while the
        x-height body is untouched so joins still meet where they should.
        Returns f(points) -> points, or None when there is nothing to vary."""
        fw = self._apart("fw", "loop_width")
        fh = self._apart("fh", "loop_height")
        dw = self._apart("dw", "loop_width")
        dh = self._apart("dh", "loop_height")
        if not (fw or fh or dw or dh):
            return None
        u = main[:, 0] - slant * main[:, 1]
        up = main[:, 1] > 1.2
        down = main[:, 1] < -0.3
        uc_up = float(u[up].mean()) if up.any() else None
        uc_dn = float(u[down].mean()) if down.any() else None
        if uc_up is None and uc_dn is None:
            return None

        def ramp(t):
            t = np.clip(t, 0.0, 1.0)
            return t * t * (3 - 2 * t)

        def f(p: np.ndarray) -> np.ndarray:
            x, y = p[:, 0], p[:, 1]
            uu = x - slant * y
            ny = y.copy()
            if uc_up is not None:
                w = ramp((y - 1.0) / 0.4)
                uu = uu + (uu - uc_up) * fw * w
                ny = np.where(y > 1.0, 1.0 + (y - 1.0) * (1 + fh), ny)
            if uc_dn is not None:
                w = ramp(-y / 0.4)
                uu = uu + (uu - uc_dn) * dw * w
                ny = np.where(y < 0.0, y * (1 + dh), ny)
            return np.column_stack([uu + slant * ny, ny])

        return f

    def flourish(self) -> float:
        """Extra length (x-heights) for a word-final hairline, or 0."""
        if self.amount <= 0 or self.rng.uniform() >= self.p["flourish"]:
            return 0.0
        return float(self.rng.uniform(0.5, 0.9)) * min(1.0, self.amount)

    def choose(self, options: list, avoid=None):
        """A random pick; `avoid` (the previous copy of a doubled letter) is
        left out when there is anything else to pick."""
        if avoid is not None and len(options) > 1 and any(o is avoid for o in options):
            options = [o for o in options if o is not avoid]
        return options[int(self.rng.integers(len(options)))] if options else None

    def line_field(self):
        """A smooth displacement function f(points) -> points for one line."""
        a = self.p["wobble"] * self.amount
        lam = self.p["wobble_scale"]
        drift = self.p["drift"] * self.amount
        k = self.rng.normal(0, 1, size=(6, 2)) / lam
        ph = self.rng.uniform(0, 2 * np.pi, size=(6, 2))
        amp = self.rng.normal(0, a / np.sqrt(3), size=(6, 2))
        d_k = self.rng.uniform(0.02, 0.06)
        d_ph = self.rng.uniform(0, 2 * np.pi)

        def f(p: np.ndarray) -> np.ndarray:
            if a == 0 and drift == 0:
                return p
            out = p.copy()
            for j in range(6):
                for axis in range(2):
                    out[:, axis] += amp[j, axis] * np.sin(p @ k[j] + ph[j, axis])
            out[:, 1] += drift * np.sin(p[:, 0] * d_k * 2 * np.pi + d_ph)
            return out

        return f
