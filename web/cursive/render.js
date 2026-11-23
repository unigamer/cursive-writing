// SVG output for pen plotters: a port of cursive/render.py.

import * as g from "./geometry.js";

// page sizes in mm; `int` marks the ones Python stores as ints (it prints
// them without ".0", and the SVG should come out byte-identical)
export const PAGES_MM = {
  a3: [297, 420],
  a4: [210, 297],
  a5: [148, 210],
  a6: [105, 148],
  letter: [215.9, 279.4],
  dl: [220, 110],
  c5: [229, 162],
};

/** A number as Python prints it: {value, int} or a plain float. */
export const pyFloat = (v, isInt = false) => (isInt || !Number.isInteger(v) ? String(v) : `${v}.0`);

/** 'a4', 'a4-landscape' or 'WxH' -> [[w, h], areInts] */
export function pageSize(spec) {
  let s = spec.toLowerCase().trim();
  const land = s.endsWith("-landscape");
  if (land) s = s.slice(0, -"-landscape".length);
  let wh;
  let ints = false;
  if (s in PAGES_MM) {
    wh = [...PAGES_MM[s]];
    ints = true;
  } else {
    const parts = s.split("x").map(Number);
    if (parts.length !== 2 || parts.some((v) => !Number.isFinite(v) || v <= 0)) throw new Error(`bad page size "${spec}"`);
    wh = parts;
  }
  const [w, h] = wh;
  return { size: land ? [h, w] : [w, h], ints };
}

export function linesToMm(lines, xhMm, origin) {
  const [ox, oy] = origin;
  return lines.map((ln) => ln.paths.map((p) => p.map(([x, y]) => [ox + x * xhMm, oy - y * xhMm])));
}

/** Python's f"{x:.3f}": round half to even on the exact binary value. */
export function fmt3(x) {
  let s = x.toFixed(3);
  // toFixed rounds exact ties up; Python rounds them to even. A double is
  // exactly halfway at 3 decimals only if it is an odd multiple of 1/16.
  const m = x * 16;
  if (Number.isInteger(m) && Math.abs(m) % 2 === 1) {
    const k = Math.round(Math.abs(x) * 1000 - 0.5); // the lower neighbour
    const even = k % 2 === 0 ? k : k + 1;
    s = (x < 0 ? "-" : "") + (even / 1000).toFixed(3);
  }
  if (Object.is(x, -0) || (x < 0 && !s.startsWith("-"))) s = `-${s}`;
  return s;
}

export function pathD(p, epsMm = 0.02) {
  let q = p.length > 2 ? g.rdp(p, epsMm) : p;
  if (q.length === 1) q = [q[0], [q[0][0] + 0.05, q[0][1] + 0]];
  const pts = q.map(([x, y]) => `${fmt3(x)},${fmt3(y)}`);
  return q.length > 1 ? `M ${pts[0]} L ${pts.slice(1).join(" ")}` : `M ${pts.join(" ")}`;
}

const escapeXml = (s) => s.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

/**
 * mmLines: [[path, ...] per line]; page: {size:[w,h], ints}
 * strokeMm is printed as a Python float (0.35, 1.0).
 */
export function toSvg(mmLines, page, strokeMm = 0.35, title = "cursive") {
  const [w, h] = page.size.map((v) => pyFloat(v, page.ints));
  const out = [
    '<?xml version="1.0" encoding="UTF-8"?>',
    '<svg xmlns="http://www.w3.org/2000/svg" ' +
      'xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape" ' +
      `width="${w}mm" height="${h}mm" viewBox="0 0 ${w} ${h}">`,
    `<title>${escapeXml(title)}</title>`,
    '<g inkscape:groupmode="layer" inkscape:label="1 cursive" ' +
      `fill="none" stroke="black" stroke-width="${pyFloat(strokeMm)}" ` +
      'stroke-linecap="round" stroke-linejoin="round">',
  ];
  mmLines.forEach((paths, i) => {
    out.push(`<g id="line${i + 1}">`);
    for (const p of paths) out.push(`<path d="${pathD(p)}"/>`);
    out.push("</g>");
  });
  out.push("</g>", "</svg>");
  return out.join("\n");
}

export function stats(mmLines) {
  let down = 0.0;
  let up = 0.0;
  let n = 0;
  let last = null;
  for (const paths of mmLines) {
    for (const p of paths) {
      down += g.length(p);
      if (last !== null) up += g.hypot2(p[0][0] - last[0], p[0][1] - last[1]);
      last = p[p.length - 1];
      n += 1;
    }
  }
  return { paths: n, pen_down_mm: Math.round(down * 10) / 10, pen_up_mm: Math.round(up * 10) / 10 };
}
