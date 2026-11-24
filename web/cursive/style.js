// Glyph and style data: a port of cursive/glyph.py (Style.load) and
// cursive/spacing.py (even spacing, applied at load as in Python).
//
// A style "bundle" is the content of styles/<name>/ gathered into one JSON
// object by tools/build_web.py:
//   { name, style: <style.json>, pairs: <pairs.json "pairs">,
//     glyphs: [[filename, <glyph json>], ...] }

import * as g from "./geometry.js";
import { cutEnd, cutStart } from "./join.js";

export const isAlpha = (c) => /^\p{L}$/u.test(c);
export const isLower = (c) => c !== c.toUpperCase() && c === c.toLowerCase();
export const isUpper = (c) => c !== c.toLowerCase() && c === c.toUpperCase();
// Python's str.isspace()
export const isSpace = (c) =>
  /^[\t\n\x0b\x0c\r\x1c-\x1f \x85\xa0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000]$/.test(c);
const isDigit = (c) => /^\p{Nd}$/u.test(c);

function glyphFromDict(d) {
  return {
    char: d.char,
    advance: Number(d.advance),
    strokes: d.strokes.map((s, i) => ({
      points: s.points.map((q) => [Number(q[0]), Number(q[1])]),
      deferred: Boolean(s.deferred ?? i > 0),
      kind: s.kind ?? "line",
    })),
    lead_in: Number(d.lead_in ?? 0.0),
    lead_out: Number(d.lead_out ?? 0.0),
    entry: d.entry ?? "low",
    exit: d.exit ?? "low",
    hook_retrace: Boolean(d.hook_retrace ?? false),
    final_trim: Number(d.final_trim ?? 0.0),
    base: d.base ?? "",
    // the character this glyph joins and kerns as: its base letter (é -> e), or itself
    key: d.base || d.char,
  };
}

/** 'e' -> 'base', 'e.alt2' -> 'base', 'e.fina' -> 'fina', 'b.init' -> 'init' */
function formOf(stem) {
  const parts = stem.split(".").slice(1);
  for (const f of ["init", "fina"]) if (parts.includes(f)) return f;
  return "base";
}

// Python sorts file names by code point; so does this (no locale)
const byCodePoint = (a, b) => (a[0] < b[0] ? -1 : a[0] > b[0] ? 1 : 0);

export function loadStyle(bundle) {
  const meta = bundle.style ?? {};
  const glyphs = new Map(); // char -> [main, alternates...]
  const forms = new Map(); // "char|form" -> glyphs
  const files = [...bundle.glyphs].sort(byCodePoint);
  for (const [fname, data] of files) {
    const stem = fname.replace(/\.json$/, "");
    const gl = glyphFromDict(data);
    const form = formOf(stem);
    if (form !== "base") {
      const k = `${gl.char}|${form}`;
      if (!forms.has(k)) forms.set(k, []);
      forms.get(k).push(gl);
      continue;
    }
    if (!glyphs.has(gl.char)) glyphs.set(gl.char, []);
    if (stem.includes(".alt")) glyphs.get(gl.char).push(gl);
    else glyphs.get(gl.char).unshift(gl);
  }
  const style = {
    name: meta.name ?? bundle.name,
    glyphs,
    forms,
    slant: Number(meta.slant ?? 0.0),
    tracking: Number(meta.tracking ?? 0.0),
    word_space: Number(meta.word_space ?? 0.9),
    line_height: Number(meta.line_height ?? 4.0),
    tension: Number(meta.tension ?? 0.45),
    glyph_slant: Number(meta.glyph_slant ?? 0.0),
    no_join_pairs: new Set(meta.no_join_pairs ?? []),
    no_join_after: new Set(meta.no_join_after ?? ""),
    no_join_before: new Set(meta.no_join_before ?? ""),
    variation: meta.variation ?? {},
    use_forms: true,
    pairs: bundle.pairs ?? {},
    letter_gap: Number(meta.even_spacing ?? 0.6),
    // least ink distance between words before one is pushed (layout.js)
    word_clear: Number(meta.word_clear ?? Math.max(0.3, 0.9 * Number(meta.even_spacing ?? 0.6))),
    // body gap after an unjoined capital; only the kerning tool uses it (pairs.json carries the result)
    capital_gap: Number(meta.capital_gap ?? 0.72 * Number(meta.even_spacing ?? 0.6)),
    join_capitals: meta.join_capitals ?? "",
    counter_width: Number(meta.counter_width ?? 0.0),
  };
  if (meta.even_spacing) {
    const lower = new Set([...glyphs.keys(), ...[...forms.keys()].map((k) => k.split("|")[0])].filter((c) => isLower(c)));
    applyEvenSpacing(style, Number(meta.even_spacing), [...lower].join(""));
  }
  return style;
}

/** Glyph choices for `ch` at `position` ("init", "medi", "fina", "isol"). */
export function options(style, ch, position) {
  const k = `${ch}|${position}`;
  if (style.use_forms && (position === "init" || position === "fina") && style.forms.has(k)) return style.forms.get(k);
  return style.glyphs.get(ch) ?? [];
}

export function canJoin(style, a, b) {
  if (!(isAlpha(a.char) && isAlpha(b.char))) return false;
  if (a.exit === "none" || b.entry === "none") return false;
  if (style.no_join_after.has(a.key) || style.no_join_before.has(b.key)) return false;
  return !style.no_join_pairs.has(a.key + b.key);
}

// ------------------------------------------------------------ even spacing

const HEIGHTS = g.linspace(0.15, 0.85, 8);

function bodyPoints(gl) {
  let p = gl.strokes[0].points;
  if (gl.lead_in && !gl.hook_retrace) p = cutStart(p, gl.lead_in);
  if (gl.lead_out) p = cutEnd(p, gl.lead_out);
  return p.length > 1 ? g.resample(p, 0.01) : p;
}

function edges(gl, slant) {
  const p = bodyPoints(gl);
  if (p.length < 2) return null;
  const x = p.map((q) => q[0] - slant * q[1]);
  const lefts = [];
  const rights = [];
  for (const h of HEIGHTS) {
    let lo = Infinity;
    let hi = -Infinity;
    let any = false;
    for (let i = 0; i < p.length; i++) {
      if (Math.abs(p[i][1] - h) < 0.06) {
        any = true;
        if (x[i] < lo) lo = x[i];
        if (x[i] > hi) hi = x[i];
      }
    }
    if (any) {
      lefts.push(lo);
      rights.push(hi);
    }
  }
  if (!lefts.length) return null;
  return [0.5 * g.mean(lefts) + 0.5 * g.amin(lefts), 0.5 * g.mean(rights) + 0.5 * g.amax(rights)];
}

function applyEvenSpacing(style, gap, chars) {
  const groups = [
    ...[...style.glyphs.entries()].map(([ch, v]) => [ch, v]),
    ...[...style.forms.entries()].map(([k, v]) => [k.split("|")[0], v]),
  ];
  for (const [ch, variants] of groups) {
    if (chars && !chars.includes(ch)) continue;
    for (const gl of variants) {
      const e = edges(gl, style.glyph_slant);
      if (e === null) continue;
      const [left, right] = e;
      for (const s of gl.strokes) s.points = s.points.map((q) => [q[0] - left, q[1] - 0.0]);
      gl.advance = right - left + gap;
    }
  }
}

/** Every character the style can write, grouped for display (Style.char_groups). */
export function charGroups(style) {
  const cs = [...style.glyphs.keys()].sort((a, b) => (a < b ? -1 : a > b ? 1 : 0));
  const ascii = (c) => c.codePointAt(0) < 128;
  const groups = [
    ["lowercase", cs.filter((c) => ascii(c) && isLower(c))],
    ["capitals", cs.filter((c) => ascii(c) && isUpper(c))],
    ["more letters", [...cs.filter((c) => !ascii(c) && isLower(c)), ...cs.filter((c) => !ascii(c) && isUpper(c))]],
    ["digits", cs.filter((c) => isDigit(c))],
    ["punctuation and symbols", cs.filter((c) => !(isLower(c) || isUpper(c) || isDigit(c)))],
  ];
  return groups.filter(([, chars]) => chars.length).map(([name, chars]) => [name, chars.join("")]);
}

/** Characters in `text` the style has no glyph for, once each, in order (Style.missing_chars). */
export function missingChars(style, text) {
  const out = [];
  for (const ch of text) if (!isSpace(ch) && !style.glyphs.has(ch) && !out.includes(ch)) out.push(ch);
  return out.join("");
}

/** The warning for characters a style can't write (glyph.missing_chars_warning). */
export function missingCharsWarning(styleName, missing) {
  const n = Array.from(missing).length;
  const shown = Array.from(missing, (c) => `"${c}"`).join(", ");
  return `The ${styleName} style has no glyph for ${shown}; ${n === 1 ? "it is" : "they are"} left out.`;
}
