// Seeded variation: a port of cursive/variation.py. Every random draw is made
// in the same order as in Python, from the same generator, so a seed gives
// the same letters in both.

import * as g from "./geometry.js";
import { Generator } from "./rng.js";

export const DEFAULTS = {
  size: 0.03,
  width: 0.04,
  slant: 0.03,
  baseline: 0.03,
  spacing: 0.03,
  wobble: 0.012,
  wobble_scale: 1.6,
  drift: 0.04,
  loop_width: 0.08,
  loop_height: 0.04,
  flourish: 0.35,
};

export class Variation {
  constructor(params, seed, amount = 1.0) {
    this.p = { ...DEFAULTS, ...(params ?? {}) };
    this.amount = amount;
    this.rng = new Generator(seed);
  }

  _n(key) {
    return this.rng.normal(0.0, this.p[key] * this.amount);
  }

  /** [matrix [[a,b],[c,d]], offset [x,y], extra advance] */
  glyphTransform() {
    const sy = 1.0 + this._n("size");
    const sx = sy * (1.0 + this._n("width"));
    const shear = this._n("slant");
    const m = [
      [sx, shear * sy],
      [0.0, sy],
    ];
    const off = [0.0, this._n("baseline")];
    return [m, off, this._n("spacing")];
  }

  loopWarp(main, slant) {
    const fw = this._n("loop_width");
    const fh = this._n("loop_height");
    const dw = this._n("loop_width");
    const dh = this._n("loop_height");
    if (!(fw || fh || dw || dh)) return null;
    const upU = [];
    const dnU = [];
    for (const [x, y] of main) {
      const u = x - slant * y;
      if (y > 1.2) upU.push(u);
      if (y < -0.3) dnU.push(u);
    }
    const ucUp = upU.length ? g.mean(upU) : null;
    const ucDn = dnU.length ? g.mean(dnU) : null;
    if (ucUp === null && ucDn === null) return null;
    const ramp = (t) => {
      t = Math.min(Math.max(t, 0.0), 1.0);
      return t * t * (3 - 2 * t);
    };
    return (p) =>
      p.map(([x, y]) => {
        let uu = x - slant * y;
        let ny = y;
        if (ucUp !== null) {
          const w = ramp((y - 1.0) / 0.4);
          uu = uu + (uu - ucUp) * fw * w;
          ny = y > 1.0 ? 1.0 + (y - 1.0) * (1 + fh) : ny;
        }
        if (ucDn !== null) {
          const w = ramp(-y / 0.4);
          uu = uu + (uu - ucDn) * dw * w;
          ny = y < 0.0 ? y * (1 + dh) : ny;
        }
        return [uu + slant * ny, ny];
      });
  }

  flourish() {
    if (this.amount <= 0 || this.rng.uniform() >= this.p.flourish) return 0.0;
    return this.rng.uniform(0.5, 0.9) * Math.min(1.0, this.amount);
  }

  choose(opts) {
    return opts.length ? opts[this.rng.integers(opts.length)] : null;
  }

  /** A smooth displacement f(points) -> points for one line. */
  lineField() {
    const a = this.p.wobble * this.amount;
    const lam = this.p.wobble_scale;
    const drift = this.p.drift * this.amount;
    const grid = (draw) => Array.from({ length: 6 }, () => [draw(), draw()]);
    const k = grid(() => this.rng.normal(0, 1)).map((r) => r.map((v) => v / lam));
    const ph = grid(() => this.rng.uniform(0, 2 * Math.PI));
    const sa = a / Math.sqrt(3);
    const amp = grid(() => this.rng.normal(0, sa));
    const dK = this.rng.uniform(0.02, 0.06);
    const dPh = this.rng.uniform(0, 2 * Math.PI);
    return (p) => {
      if (a === 0 && drift === 0) return p;
      return p.map(([x, y]) => {
        let ox = x;
        let oy = y;
        for (let j = 0; j < 6; j++) {
          const proj = x * k[j][0] + y * k[j][1];
          ox += amp[j][0] * Math.sin(proj + ph[j][0]);
          oy += amp[j][1] * Math.sin(proj + ph[j][1]);
        }
        oy += drift * Math.sin(x * dK * 2 * Math.PI + dPh);
        return [ox, oy];
      });
    };
  }
}
