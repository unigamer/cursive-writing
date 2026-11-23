// Lay out text as lines of joined words: a port of cursive/layout.py.
// Units are x-heights, y up.

import * as g from "./geometry.js";
import { assembleWord } from "./join.js";
import { isAlpha, isLower, options } from "./style.js";
import { Variation } from "./variation.js";

const WORD_CLEAR = 0.3;
const WORD_PUSH_MAX = 1.2;

// Python's str.split() whitespace
const PY_SPACE = new RegExp(
  "[\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000]+",
);
export const pySplit = (s) => s.split(PY_SPACE).filter((w) => w.length);

/** Smallest of the distances between points of A and of B shifted right by d. */
function closestShifted(A, B, d) {
  let best = Infinity;
  for (const b of B) {
    const bx = b[0] + d;
    const by = b[1] + 0.0;
    for (const a of A) {
      const dx = a[0] - bx;
      const dy = a[1] - by;
      const q = dx * dx + dy * dy;
      if (q < best) best = q;
    }
  }
  return Math.sqrt(best);
}

/** How far to move point set B right so no point comes within `clear` of A. */
export function clearancePush(A, B, clear, limit) {
  let bmin = Infinity;
  for (const b of B) if (b[0] < bmin) bmin = b[0];
  A = A.filter((a) => a[0] > bmin - clear - limit);
  let amax = -Infinity;
  for (const a of A) if (a[0] > amax) amax = a[0];
  const closest = (d) => {
    const a = A.filter((q) => q[0] > bmin + d - clear);
    const b = A.length ? B.filter((q) => q[0] + d < amax + clear) : [];
    if (!a.length || !b.length) return Infinity;
    return closestShifted(a, b, d);
  };
  let d = 0.0;
  while (closest(d) < clear && d < limit) d += 0.1;
  return Math.min(d, limit);
}

/** Left/right edge of a word's ink within the x-height band, slant removed. */
export function bodyExtent(paths, slant) {
  const pts = paths.flat();
  let band = pts.filter((q) => q[1] > -0.05 && q[1] < 1.05);
  if (!band.length) band = pts;
  let lo = Infinity;
  let hi = -Infinity;
  for (const q of band) {
    const x = q[0] - slant * q[1];
    if (x < lo) lo = x;
    if (x > hi) hi = x;
  }
  return [lo, hi];
}

const transform = (p, m, o) => p.map(([x, y]) => [x * m[0][0] + y * m[0][1] + o[0], x * m[1][0] + y * m[1][1] + o[1]]);

/** [word, advance width]; `overrides` maps a char to a glyph to use instead. */
export function placeWord(text, style, v, overrides = null) {
  const placed = [];
  let x = 0.0;
  const chars = Array.from(text);
  const letters = [];
  chars.forEach((c, i) => {
    if (isAlpha(c)) letters.push(i);
  });
  const [first, last] = letters.length ? [letters[0], letters[letters.length - 1]] : [-1, -1];
  chars.forEach((ch, i) => {
    const pos = first === last && last === i ? "isol" : i === first ? "init" : i === last ? "fina" : "medi";
    const opts = overrides && ch in overrides ? [overrides[ch]] : options(style, ch, pos);
    if (!opts.length) {
      x += style.word_space * 0.5;
      return;
    }
    const gl = v.choose(opts);
    const [m, off, dadv] = v.glyphTransform();
    const warp = isLower(ch) ? v.loopWarp(gl.strokes[0].points, style.glyph_slant) : null;
    let o = [x + off[0], 0.0 + off[1]];
    if (placed.length) {
      const pair = style.pairs[placed[placed.length - 1].glyph.char + gl.char];
      if (pair && pair.dx) {
        x += Number(pair.dx);
        o = [x + off[0], 0.0 + off[1]];
      }
    }
    const shape = warp ?? ((p) => p);
    placed.push({
      glyph: gl,
      main: transform(shape(gl.strokes[0].points), m, o),
      deferred: gl.strokes.slice(1).map((s) => transform(shape(s.points), m, o)),
      x,
      flourish: i === last && last === chars.length - 1 && isLower(ch) ? v.flourish() : 0.0,
    });
    x += gl.advance * m[0][0] + style.tracking + dadv;
  });
  return [assembleWord(placed, style), x];
}

/**
 * Break text into lines no wider than `width` (x-heights, null = no wrap).
 * Returns [{paths, width, baseline}].
 */
export function layout(text, style, { width = null, seed = 0, amount = 1.0, align = "left" } = {}) {
  const v = new Variation(style.variation, seed, amount);
  const lines = [];
  let y = 0.0;
  for (const para of text.split("\n")) {
    let cur = [];
    let curW = 0.0;
    const flush = () => {
      const paths = [];
      let x = 0.0;
      let prevInk = null;
      for (const [word, [lo, hi]] of cur) {
        const ink = word.paths.flatMap((p) => (p.length > 1 ? g.resample(p, 0.03) : p));
        let sx = x - lo;
        if (prevInk !== null) {
          const push = clearancePush(prevInk, g.add(ink, [sx, 0.0]), WORD_CLEAR, WORD_PUSH_MAX);
          x += push;
          sx += push;
        }
        for (const p of word.paths) paths.push(g.add(p, [sx, y]));
        prevInk = g.add(ink, [sx, 0.0]);
        x += hi - lo + style.word_space;
      }
      lines.push({ paths, width: Math.max(x - style.word_space, 0.0), baseline: y });
      y -= style.line_height;
      cur = [];
      curW = 0.0;
    };
    for (const wtext of pySplit(para)) {
      const [word] = placeWord(wtext, style, v);
      if (!word.paths.length) continue;
      const [lo, hi] = bodyExtent(word.paths, style.glyph_slant);
      let addW = !cur.length ? hi - lo : style.word_space + (hi - lo);
      if (width !== null && cur.length && curW + addW > width) {
        flush();
        addW = hi - lo;
      }
      cur.push([word, [lo, hi]]);
      curW += addW;
    }
    flush();
  }

  const shear = Math.tan(style.slant * (Math.PI / 180.0));
  for (const ln of lines) {
    let dx = 0.0;
    if (width !== null && align === "center") dx = (width - ln.width) / 2;
    else if (width !== null && align === "right") dx = width - ln.width;
    const field = v.lineField();
    let out = ln.paths.map((p) => {
      let q = g.add(p, [dx, 0.0]);
      if (shear) q = q.map(([qx, qy]) => [qx + (qy - ln.baseline) * shear, qy + 0.0]);
      q = q.length > 1 ? g.resample(q, 0.02) : q;
      return field(q);
    });
    let minx = Infinity;
    for (const p of out) for (const q of p) if (q[0] < minx) minx = q[0];
    if (!out.length) minx = 0.0;
    if (width !== null && minx < 0) out = out.map((p) => g.add(p, [-minx, 0.0]));
    ln.paths = out;
  }
  return lines;
}
