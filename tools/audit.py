"""Flag glyphs whose extracted pen path looks suspicious.

    python tools/audit.py [style ...]

Checks (lowercase unless noted):
  start-low    the pen starts below the baseline (on a descender tip)
  end-low      the pen ends below the baseline (a joining letter should exit right)
  end-left     the main stroke does not finish on the right of the letter
  no-exit      a lowercase letter that never joins onward
  retrace      a large share of the stroke is drawn twice
  tiny         the main stroke is suspiciously short (ink went missing)
"""

from __future__ import annotations

import string
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from cursive import geometry as g  # noqa: E402
from cursive.glyph import STYLES_DIR, Style  # noqa: E402


def retrace_share(p: np.ndarray, tol: float = 0.02) -> float:
    """Fraction of the path lying on top of an earlier part of itself."""
    q = g.resample(p, 0.02)
    if len(q) < 10:
        return 0.0
    over = 0
    for i in range(6, len(q)):
        d = np.linalg.norm(q[: i - 5] - q[i], axis=1)
        over += d.min() < tol
    return over / len(q)


def audit(style: Style) -> list[tuple[str, str, str]]:
    out = []
    k = style.glyph_slant
    for ch, variants in sorted(style.glyphs.items()):
        for n, gl in enumerate(variants + [v for (c, f), vs in style.forms.items() if c == ch for v in vs]):
            name = ch if n == 0 else f"{ch}#{n}"
            p = gl.main.points
            x = p[:, 0] - k * p[:, 1]
            lower = ch in string.ascii_lowercase
            issues = []
            if lower and p[0, 1] < -0.25:
                issues.append("start-low")
            if lower and p[-1, 1] < -0.15:
                issues.append("end-low")
            if lower and gl.exit != "none" and x[-1] < x.min() + 0.6 * (x.max() - x.min()):
                issues.append("end-left")
            if lower and gl.exit == "none":
                issues.append("no-exit")
            r = retrace_share(p)
            if r > 0.35:
                issues.append(f"retrace {r:.0%}")
            if g.length(p) < 0.8:
                issues.append("tiny")
            if issues:
                out.append((style.name, name, ", ".join(issues)))
    return out


def main():
    names = sys.argv[1:] or sorted(p.name for p in STYLES_DIR.iterdir() if (p / "glyphs").is_dir())
    total = 0
    for n in names:
        rows = audit(Style.load(n))
        total += len(rows)
        print(f"== {n}: {len(rows)} suspect glyphs")
        for _, name, issues in rows:
            print(f"   {name:6s} {issues}")
    print(f"total {total}")


if __name__ == "__main__":
    main()
