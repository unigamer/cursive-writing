// Test driver for the JS engine, used by tests/test_web.py:
//
//   deno run --allow-read web/test/runner.js requests.json > results.json
//   node web/test/runner.js requests.json > results.json
//
// requests.json is a list of
//   {op: "page",  style, text, opts}            -> {svg, mm}
//   {op: "words", style, words, seed, amount}   -> [[path, ...] per word]
//   {op: "rng",   seed, n}                      -> a mixed stream of draws
//   {op: "chars", style, text}                  -> {groups, missing, warning}

import { charGroups, Generator, generate, loadStyle, missingChars, placeWord, Variation } from "../cursive/index.js";
import { missingCharsWarning } from "../cursive/style.js";

const here = new URL(".", import.meta.url);
const readText = globalThis.Deno
  ? (url) => Deno.readTextFile(url)
  : async (url) => (await import("node:fs/promises")).readFile(url, "utf8");
const args = globalThis.Deno ? Deno.args : process.argv.slice(2);

const styles = new Map();
async function style(name) {
  if (!styles.has(name)) {
    const text = await readText(new URL(`../data/${name}.json`, here));
    styles.set(name, loadStyle(JSON.parse(text)));
  }
  return styles.get(name);
}

const requests = JSON.parse(await readText(new URL(args[0], `file://${globalThis.Deno ? Deno.cwd() : process.cwd()}/`)));
const results = [];
for (const r of requests) {
  if (r.op === "page") {
    const out = generate(r.text, await style(r.style), r.opts);
    results.push({ svg: out.svg, mm: out.mm, warnings: out.warnings });
  } else if (r.op === "words") {
    const st = await style(r.style);
    const v = new Variation(st.variation, r.seed, r.amount);
    results.push(r.words.map((w) => placeWord(w, st, v)[0].paths));
  } else if (r.op === "rng") {
    const gen = new Generator(r.seed);
    const out = [];
    for (let i = 0; i < r.n; i++) out.push(gen.integers(3), gen.normal(0, 0.03), gen.uniform(0.5, 0.9), gen.integers(2));
    results.push(out);
  } else if (r.op === "chars") {
    const st = await style(r.style);
    const missing = missingChars(st, r.text);
    results.push({ groups: charGroups(st), missing, warning: missing ? missingCharsWarning(st.name, missing) : null });
  } else {
    throw new Error(`unknown op ${r.op}`);
  }
}
console.log(JSON.stringify(results));
