// Faux pointed-pen shading: a port of cursive/shade.py. Extra passes beside
// each downstroke are woven into the stroke, so no pen lifts are added.
// Page millimetres, y down.

import * as g from "./geometry.js";

function gradient(p) {
  const n = p.length;
  return p.map((q, i) => {
    if (i === 0) return [p[1][0] - p[0][0], p[1][1] - p[0][1]];
    if (i === n - 1) return [p[n - 1][0] - p[n - 2][0], p[n - 1][1] - p[n - 2][1]];
    return [(p[i + 1][0] - p[i - 1][0]) / 2.0, (p[i + 1][1] - p[i - 1][1]) / 2.0];
  });
}

const normalise = (d) =>
  d.map(([x, y]) => {
    const n = Math.max(g.hypot2(x, y), 1e-9);
    return [x / n, y / n];
  });

function weights(p, slant) {
  const d = normalise(gradient(p));
  const down = g.unit([-slant, 1.0]);
  const w = d.map((v) => Math.min(Math.max(g.dot(v, down), 0), 1) ** 2);
  // edge-padded moving average over 9 points (np.convolve "valid")
  const pad = [...new Array(4).fill(w[0]), ...w, ...new Array(4).fill(w[w.length - 1])];
  const k = 1 / 9;
  return w.map((_, i) => {
    let s = 0.0;
    for (let j = 0; j < 9; j++) s += pad[i + j] * k;
    return s;
  });
}

function runs(on) {
  const out = [];
  let start = -1;
  for (let i = 0; i <= on.length; i++) {
    const v = i < on.length && on[i];
    if (v && start < 0) start = i;
    else if (!v && start >= 0) {
      out.push([start, i]);
      start = -1;
    }
  }
  return out;
}

export function shadePath(p, slant, penMm, maxMm, minLenMm = 1.0, stepMm = 0.15) {
  if (p.length < 5 || maxMm <= 0) return p;
  p = g.resample(p, stepMm);
  const w = weights(p, slant);
  const spacing = penMm * 0.8;
  const out = [];
  let pos = 0;
  for (const [a, b] of runs(w.map((v) => v > 0.25))) {
    const seg = p.slice(a, b);
    const ws = w.slice(a, b);
    if (g.length(seg) < minLenMm) continue;
    const wmax = g.amax(ws);
    const swell = maxMm * wmax;
    let passes = Math.ceil(swell / spacing);
    passes += passes % 2;
    if (passes === 0) continue;
    const t = g.linspace(0, Math.PI, seg.length);
    const denom = Math.max(wmax, 1e-9);
    const taper = t.map((ti, i) => (Math.sin(ti) ** 0.7 * ws[i]) / denom);
    const tang = normalise(gradient(seg));
    const normal = tang.map(([x, y]) => [y, -x]);
    out.push(p.slice(pos, b));
    for (let k = 1; k <= passes; k++) {
      const o = Math.min(k * spacing, swell);
      const q = seg.map((s, i) => {
        const off = o * taper[i];
        return [s[0] + normal[i][0] * off, s[1] + normal[i][1] * off];
      });
      out.push(k % 2 ? q.reverse() : q);
    }
    pos = b;
  }
  out.push(p.slice(pos));
  return out.filter((o) => o.length).flat();
}

export const shadePaths = (paths, slant, penMm, maxMm) => paths.map((p) => shadePath(p, slant, penMm, maxMm));
