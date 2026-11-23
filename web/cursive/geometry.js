// Polyline geometry: a port of cursive/geometry.py plus the few numpy
// primitives the engine relies on, written to round the same way numpy does
// (summation order, interp, linspace) so results match the Python engine.
// The numpy-derived parts are BSD-3-Clause (NumPy Developers); see
// THIRD_PARTY_NOTICES.md.
//
// A point is [x, y]; a polyline is an array of points, y up.

// ------------------------------------------------------------ numpy bits

/** numpy's pairwise summation (add.reduce on a contiguous float64 array). */
export function pairwiseSum(a, lo = 0, n = a.length - lo) {
  if (n < 8) {
    let r = 0.0;
    for (let i = 0; i < n; i++) r += a[lo + i];
    return r;
  }
  if (n <= 128) {
    const r = [a[lo], a[lo + 1], a[lo + 2], a[lo + 3], a[lo + 4], a[lo + 5], a[lo + 6], a[lo + 7]];
    let i = 8;
    for (; i < n - (n % 8); i += 8) for (let j = 0; j < 8; j++) r[j] += a[lo + i + j];
    let res = r[0] + r[1] + (r[2] + r[3]) + (r[4] + r[5] + (r[6] + r[7]));
    for (; i < n; i++) res += a[lo + i];
    return res;
  }
  let n2 = Math.floor(n / 2);
  n2 -= n2 % 8;
  return pairwiseSum(a, lo, n2) + pairwiseSum(a, lo + n2, n - n2);
}

export function mean(a) {
  return (0.0 + pairwiseSum(a)) / a.length;
}

export function amin(a) {
  let m = Infinity;
  for (const v of a) if (v < m) m = v;
  return m;
}

export function amax(a) {
  let m = -Infinity;
  for (const v of a) if (v > m) m = v;
  return m;
}

/** index of the first maximum (np.argmax) */
export function argmax(a) {
  let k = 0;
  for (let i = 1; i < a.length; i++) if (a[i] > a[k]) k = i;
  return k;
}

/** np.searchsorted(a, v) (side="left"): first i with a[i] >= v */
export function searchsorted(a, v) {
  let lo = 0;
  let hi = a.length;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (a[mid] < v) lo = mid + 1;
    else hi = mid;
  }
  return lo;
}

/** np.interp for one x (xp increasing) */
export function interp(x, xp, fp) {
  const n = xp.length;
  if (n === 1) return fp[0];
  if (x > xp[n - 1]) return fp[n - 1];
  if (x < xp[0]) return fp[0];
  // last j with xp[j] <= x
  let lo = 0;
  let hi = n;
  while (lo < hi) {
    const mid = (lo + hi) >> 1;
    if (xp[mid] <= x) lo = mid + 1;
    else hi = mid;
  }
  const j = lo - 1;
  if (j === n - 1) return fp[j];
  if (xp[j] === x) return fp[j];
  const slope = (fp[j + 1] - fp[j]) / (xp[j + 1] - xp[j]);
  let r = slope * (x - xp[j]) + fp[j];
  if (Number.isNaN(r)) {
    r = slope * (x - xp[j + 1]) + fp[j + 1];
    if (Number.isNaN(r) && fp[j] === fp[j + 1]) r = fp[j];
  }
  return r;
}

/** np.linspace(start, stop, num) */
export function linspace(start, stop, num) {
  if (num === 1) return [start];
  const div = num - 1;
  const step = (stop - start) / div;
  const out = new Array(num);
  for (let i = 0; i < num; i++) out[i] = step === 0 ? (i / div) * (stop - start) + start : i * step + start;
  out[num - 1] = stop;
  return out;
}

export const hypot2 = (x, y) => Math.sqrt(x * x + y * y);

// ------------------------------------------------------------ polylines

export const xs = (p) => p.map((q) => q[0]);
export const ys = (p) => p.map((q) => q[1]);
export const copy = (p) => p.map((q) => [q[0], q[1]]);
export const add = (p, d) => p.map((q) => [q[0] + d[0], q[1] + d[1]]);

export function arcLengths(p) {
  if (p.length < 2) return new Array(p.length).fill(0.0);
  const a = new Array(p.length);
  a[0] = 0.0;
  let s = 0.0;
  for (let i = 1; i < p.length; i++) {
    s += hypot2(p[i][0] - p[i - 1][0], p[i][1] - p[i - 1][1]);
    a[i] = s;
  }
  return a;
}

export function length(p) {
  return p.length > 1 ? arcLengths(p)[p.length - 1] : 0.0;
}

export function resample(p, step) {
  if (p.length < 2) return copy(p);
  const s = arcLengths(p);
  const total = s[s.length - 1];
  if (total === 0) return [[p[0][0], p[0][1]]];
  const n = Math.max(2, Math.ceil(total / step) + 1);
  const t = linspace(0, total, n);
  const px = xs(p);
  const py = ys(p);
  return t.map((v) => [interp(v, s, px), interp(v, s, py)]);
}

/** Ramer-Douglas-Peucker simplification */
export function rdp(p, eps) {
  if (p.length < 3) return copy(p);
  const keep = new Array(p.length).fill(false);
  keep[0] = keep[p.length - 1] = true;
  const stack = [[0, p.length - 1]];
  while (stack.length) {
    const [i, j] = stack.pop();
    if (j <= i + 1) continue;
    const a = p[i];
    const abx = p[j][0] - a[0];
    const aby = p[j][1] - a[1];
    const n = hypot2(abx, aby);
    let best = -1;
    let k = 0;
    for (let m = i + 1; m < j; m++) {
      const wx = p[m][0] - a[0];
      const wy = p[m][1] - a[1];
      const d = n === 0 ? hypot2(wx, wy) : Math.abs(abx * wy - aby * wx) / n;
      if (d > best) {
        best = d;
        k = m;
      }
    }
    if (best > eps) {
      keep[k] = true;
      stack.push([i, k]);
      stack.push([k, j]);
    }
  }
  return p.filter((_, i) => keep[i]);
}

export function unit(v) {
  const n = hypot2(v[0], v[1]);
  return n > 1e-12 ? [v[0] / n, v[1] / n] : [0.0, 0.0];
}

export const dot = (a, b) => a[0] * b[0] + a[1] * b[1];

export function pointAt(p, s) {
  const a = arcLengths(p);
  const top = a.length ? a[a.length - 1] : 0;
  s = Math.min(Math.max(s, 0), top);
  return [interp(s, a, xs(p)), interp(s, a, ys(p))];
}

export function startTangent(p, dist) {
  const q = pointAt(p, dist);
  return unit([q[0] - p[0][0], q[1] - p[0][1]]);
}

export function endTangent(p, dist) {
  const q = pointAt(p, length(p) - dist);
  const e = p[p.length - 1];
  return unit([e[0] - q[0], e[1] - q[1]]);
}

export function cubicBezier(p0, p1, p2, p3, n = 32) {
  const t = linspace(0, 1, n);
  return t.map((ti) => {
    const mt = 1 - ti;
    const mt3 = mt ** 3;
    const mt2 = mt * mt;
    const t2 = ti * ti;
    const t3 = ti ** 3;
    const b1 = 3 * mt2 * ti;
    const b2 = 3 * mt * t2;
    return [0, 1].map((k) => mt3 * p0[k] + b1 * p1[k] + b2 * p2[k] + t3 * p3[k]);
  });
}

/** Cubic from p0 leaving along t0 to p1 arriving along t1 (see geometry.py). */
export function hermite(p0, t0, p1, t1, tension = 0.45, n = 32, h1 = null) {
  const chord = hypot2(p1[0] - p0[0], p1[1] - p0[1]);
  const h = tension * chord;
  const u0 = unit(t0);
  const u1 = unit(t1);
  const k1 = h1 === null ? h : h1;
  return cubicBezier(
    p0,
    [p0[0] + u0[0] * h, p0[1] + u0[1] * h],
    [p1[0] - u1[0] * k1, p1[1] - u1[1] * k1],
    p1,
    n,
  );
}
