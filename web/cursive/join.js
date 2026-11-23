// Assemble glyphs into joined words: a port of cursive/join.py.
//
// Between each pair that may join, the first glyph's exit hairline
// (lead_out) and the second's entry hairline (lead_in) are cut away and
// replaced by one connector curve. Joins never cross word boundaries.

import * as g from "./geometry.js";
import { canJoin } from "./style.js";

const TANGENT_PROBE = 0.06;

/** Drop the first `s` of arc length. */
export function cutStart(p, s) {
  if (s <= 0) return p;
  const a = g.arcLengths(p);
  if (s >= a[a.length - 1]) return p.slice(-1);
  const i = g.searchsorted(a, s);
  return [g.pointAt(p, s), ...p.slice(i)];
}

/** Drop the last `s` of arc length. */
export function cutEnd(p, s) {
  if (s <= 0) return p;
  const a = g.arcLengths(p);
  const keep = a[a.length - 1] - s;
  if (keep <= 0) return p.slice(0, 1);
  const i = g.searchsorted(a, keep);
  return [...p.slice(0, i), g.pointAt(p, keep)];
}

export function connector(prev, nxt, tension, slant = 0.0, arrive = "auto") {
  const p0 = prev[prev.length - 1];
  const p1 = nxt[0];
  const chord = [p1[0] - p0[0], p1[1] - p0[1]];
  const dist = g.hypot2(chord[0], chord[1]);
  if (dist < 1e-6) return [p0, p1];
  let t0 = prev.length > 1 ? g.endTangent(prev, Math.min(TANGENT_PROBE, 0.5 * g.length(prev))) : g.unit(chord);
  let t1 = nxt.length > 1 ? g.startTangent(nxt, Math.min(TANGENT_PROBE, 0.5 * g.length(nxt))) : g.unit(chord);
  const c = [chord[0] / dist, chord[1] / dist];
  const n = Math.max(8, Math.trunc(dist / 0.02));
  if (g.dot(t0, c) < -0.2) t0 = g.unit(c);
  if (typeof arrive !== "string") return g.hermite(p0, t0, p1, g.unit(arrive), tension, n);
  if (arrive === "glyph") return g.hermite(p0, t0, p1, t1, tension, n);
  if (arrive === "slant") return g.hermite(p0, t0, p1, g.unit([slant, 1.0]), tension, n);
  if (arrive === "retrace") return g.hermite(p0, t0, p1, [-t1[0], -t1[1]], tension, n);
  if (arrive === "chord") return g.hermite(p0, t0, p1, c, tension, n);
  if (arrive === "horizontal") return g.hermite(p0, t0, p1, [1.0, 0.0], tension, n);
  // auto
  if (p1[1] > 1.4 && t1[1] < 0) return g.hermite(p0, t0, p1, t1, tension, n, 0.45);
  if (g.dot(t1, c) < 0.25) {
    t1 = g.unit([slant, 1.0]);
    if (g.dot(t1, c) < 0.2) t1 = g.unit([c[0] + 0.0, c[1] + 0.3]);
    tension = Math.max(tension, 0.55);
  }
  return g.hermite(p0, t0, p1, t1, tension, n);
}

/** Join settings for a->b: defaults, overridden by the style's pairs.json. */
export function pairParams(style, a, b) {
  const p = {
    join: canJoin(style, a, b),
    dx: 0.0,
    lead_out: a.lead_out,
    lead_in: b.lead_in,
    tension: style.tension,
    arrive: "auto",
    over: null,
  };
  const o = style.pairs[a.char + b.char];
  if (o) {
    for (const k of Object.keys(o)) if (k in p) p[k] = o[k];
    if (!canJoin(style, a, b)) p.join = false;
  }
  return p;
}

export function entryStroke(stroke, gl, prev, prm, slant = 0.0) {
  let over = prm.over;
  if (over === null || over === undefined) over = prev.exit === "high" && !gl.hook_retrace;
  if (over) {
    const mode = over === "corner" || over === "bottom" ? over : "top";
    const v = topStartVariant(stroke, mode, slant);
    if (v !== null) {
      const auto = { top: "horizontal", corner: "slant", bottom: "glyph" }[mode];
      return [v, prm.arrive !== "auto" ? prm.arrive : auto];
    }
  }
  const leadIn = prm.lead_in;
  let cut = cutStart(stroke, leadIn);
  if (gl.hook_retrace && leadIn > 0) {
    const hook = cutEnd(stroke, g.length(stroke) - leadIn);
    cut = [...[...hook].reverse(), ...hook.slice(1), ...cut.slice(1)];
  }
  return [cut, prm.arrive];
}

export function topStartVariant(p, mode = "top", slant = 0.0) {
  const a = g.arcLengths(p);
  const total = a[a.length - 1];
  if (total === 0 || p[0][1] > 0.6) return null;
  const lim = Math.max(1.2, 0.2 * total);
  let c = -1;
  for (let i = 0; i < p.length; i++) {
    if (a[i] > lim && g.hypot2(p[i][0] - p[0][0], p[i][1] - p[0][1]) < 0.1) {
      c = i;
      break;
    }
  }
  if (c < 0) return null;
  const loop = p.slice(0, c + 1);
  const loopTop = g.amax(g.ys(loop));
  if (mode === "bottom") {
    let b = -1;
    for (let i = 0; i < loop.length; i++) {
      if (loop[i][1] < 0.45 * loopTop && (b < 0 || loop[i][1] < loop[b][1])) b = i;
    }
    if (b < 0) return null;
    if (b === 0 || b >= c) return null;
    return [...loop.slice(b), ...loop.slice(1, b + 1), ...loop.slice(b).slice(1), ...p.slice(c + 1)];
  }
  let t;
  if (mode === "corner") {
    t = -1;
    let best = -Infinity;
    for (let i = 0; i < loop.length; i++) {
      if (loop[i][1] > 0.55 * loopTop) {
        const x = loop[i][0] - slant * loop[i][1];
        if (x > best) {
          best = x;
          t = i;
        }
      }
    }
  } else {
    t = g.argmax(g.ys(loop));
  }
  if (t === 0 || loop[t][1] < 0.6) return null;
  const rest = p.slice(c + 1);
  if (rest.length) {
    const head = rest.slice(0, Math.max(2, Math.floor(rest.length / 2)));
    let dmin = Infinity;
    for (const q of head) dmin = Math.min(dmin, g.hypot2(q[0] - loop[t][0], q[1] - loop[t][1]));
    if (dmin < 0.12) return [...loop.slice(t), ...rest];
  }
  return [...loop.slice(t), ...loop.slice(1, t + 1), ...loop.slice(0, t).reverse(), ...rest];
}

function rot(v, deg) {
  const a = deg * (Math.PI / 180.0);
  const c = Math.cos(a);
  const s = Math.sin(a);
  return [c * v[0] - s * v[1], s * v[0] + c * v[1]];
}

export function extendFlourish(stroke, len) {
  if (stroke.length < 3 || g.length(stroke) < 0.2) return stroke;
  const t = g.endTangent(stroke, Math.min(TANGENT_PROBE, 0.5 * g.length(stroke)));
  const p0 = stroke[stroke.length - 1];
  if (!(t[0] > 0.25 && t[1] > 0.1 && p0[1] < 1.0)) return stroke;
  const r = rot(t, 15);
  const p1 = [p0[0] + len * r[0], p0[1] + len * r[1]];
  const tail = g.hermite(p0, t, p1, rot(t, 40), 0.45, Math.max(8, Math.trunc(len / 0.02)));
  return [...stroke, ...tail.slice(1)];
}

/**
 * Join placed glyphs (already positioned) into pen paths.
 * placed: [{glyph, main, deferred, x, flourish}]
 */
export function assembleWord(placed, style) {
  const w = { paths: [], joins: [], width: 0.0, glyph_x: [], pieces: [] };
  if (!placed.length) return w;
  const params = [];
  for (let i = 0; i + 1 < placed.length; i++) params.push(pairParams(style, placed[i].glyph, placed[i + 1].glyph));
  let current = null;
  placed.forEach((pg, i) => {
    let stroke = pg.main;
    const prmIn = i > 0 ? params[i - 1] : null;
    const prmOut = i < placed.length - 1 ? params[i] : null;
    const joinedIn = prmIn !== null && prmIn.join;
    const joinsOut = prmOut !== null && prmOut.join;
    let arrive = "auto";
    if (joinedIn) [stroke, arrive] = entryStroke(stroke, pg.glyph, placed[i - 1].glyph, prmIn, style.glyph_slant);
    if (joinsOut) stroke = cutEnd(stroke, prmOut.lead_out);
    else if (i === placed.length - 1 && pg.glyph.final_trim > 0) stroke = cutEnd(stroke, pg.glyph.final_trim);
    else if (i === placed.length - 1 && pg.flourish > 0) stroke = extendFlourish(stroke, pg.flourish);
    if (joinedIn && current !== null) {
      const bridge = connector(current, stroke, prmIn.tension, style.glyph_slant, arrive);
      current = [...current, ...bridge.slice(1, -1), ...stroke];
      w.joins.push([i - 1, i]);
      w.pieces.push([bridge, "conn", i]);
    } else {
      if (current !== null) w.paths.push(current);
      current = stroke;
    }
    w.pieces.push([stroke, "glyph", i]);
    w.glyph_x.push(pg.x);
  });
  if (current !== null) w.paths.push(current);
  placed.forEach((pg, i) => {
    for (const d of pg.deferred) {
      w.paths.push(d);
      w.pieces.push([d, "deferred", i]);
    }
  });
  let mx = -Infinity;
  for (const p of w.paths) for (const q of p) if (q[0] > mx) mx = q[0];
  w.width = w.paths.length ? mx : 0.0;
  return w;
}
