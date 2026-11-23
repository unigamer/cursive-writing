// Text in, plotter-ready SVG out, entirely client side. The equivalent of
// `python -m cursive.cli`: same options, same defaults, same output.

import { layout } from "./layout.js";
import { linesToMm, pageSize, stats, toSvg } from "./render.js";
import { shadePaths } from "./shade.js";
import { loadStyle } from "./style.js";

export { loadStyle, layout, pageSize };
export { placeWord } from "./layout.js";
export { Generator } from "./rng.js";
export { Variation } from "./variation.js";

export const DEFAULTS = {
  size: 6.0, // x-height, mm
  page: "a4",
  margin: 20.0,
  align: "left",
  seed: 0,
  variation: 1.0,
  pen: 0.35,
  shade: 0.0,
};

const WHITE_FRAC = 0.5; // cursive/legibility.py

/** Smallest x-height (mm) at which this style's counters stay open. */
export const minSizeFor = (counterWidth, penMm) => (counterWidth > 0 ? ((1 + WHITE_FRAC) * penMm) / counterWidth : 0.0);

/**
 * Generate a page. `style` is a loaded style (loadStyle(bundle)).
 * Returns {svg, mm, page, stats, lines, warnings}.
 */
export function generate(text, style, opts = {}) {
  const o = { ...DEFAULTS, ...opts };
  const page = pageSize(o.page);
  const [pw, ph] = page.size;
  const widthXh = (pw - 2 * o.margin) / o.size;
  const lines = layout(text, style, { width: widthXh, seed: o.seed, amount: o.variation, align: o.align });
  let firstTop = 2.0;
  if (lines.length && lines[0].paths.length) {
    firstTop = -Infinity;
    for (const p of lines[0].paths) for (const q of p) if (q[1] > firstTop) firstTop = q[1];
  }
  const top = o.margin + firstTop * o.size;
  let mm = linesToMm(lines, o.size, [o.margin, top]);
  if (o.shade > 0) mm = mm.map((paths) => shadePaths(paths, style.glyph_slant, o.pen, o.shade));
  const title = Array.from(text).slice(0, 60).join("");
  const svg = toSvg(mm, page, o.pen, title);

  const warnings = [];
  if (style.counter_width) {
    const need = minSizeFor(style.counter_width, o.pen + o.shade);
    if (o.size < need) {
      warnings.push(
        `At ${o.size} mm with a ${o.pen} mm pen${o.shade ? ` and ${o.shade} mm shading` : ""}, ` +
          `loops and letter eyes will fill in; use a size of ${need.toFixed(1)} mm or more.`,
      );
    }
  }
  let bottom = 0;
  for (const paths of mm) for (const p of paths) for (const q of p) if (q[1] > bottom) bottom = q[1];
  if (bottom > ph - o.margin) {
    warnings.push(`Text runs past the bottom margin (${bottom.toFixed(0)} mm of ${ph} mm).`);
  }
  return { svg, mm, page, stats: stats(mm), lines: lines.length, warnings };
}
