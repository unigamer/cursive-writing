// Runs the engine off the main thread so typing stays responsive.
// Messages in:  {id, text, style, opts}
// Messages out: {id, svg, stats, warnings, lines, ms} or {id, error}

import { generate, loadStyle } from "./cursive/index.js";

const styles = new Map(); // id -> Promise<style>

// The single-file build (tools/build_web.py --standalone) puts the style data
// here instead of in data/*.json.
const embedded = self.CURSIVE_BUNDLES;

function fetchBundle(id) {
  if (embedded) {
    return Object.hasOwn(embedded, id)
      ? Promise.resolve(embedded[id])
      : Promise.reject(new Error(`style "${id}" is not in this page`));
  }
  return fetch(new URL(`data/${encodeURIComponent(id)}.json`, self.location.href)).then((r) => {
    if (!r.ok) throw new Error(`could not load style "${id}" (${r.status})`);
    return r.json();
  });
}

function getStyle(id) {
  if (!styles.has(id)) {
    const p = fetchBundle(id).then(loadStyle);
    p.catch(() => styles.delete(id)); // allow a retry
    styles.set(id, p);
  }
  return styles.get(id);
}

self.onmessage = async (e) => {
  const { id, text, style, opts, preload } = e.data;
  try {
    const st = await getStyle(style);
    if (preload) return;
    const t0 = performance.now();
    const out = generate(text, st, opts);
    self.postMessage({
      id,
      svg: out.svg,
      stats: out.stats,
      warnings: out.warnings,
      lines: out.lines,
      ms: performance.now() - t0,
    });
  } catch (err) {
    self.postMessage({ id, error: String(err?.message ?? err) });
  }
};
