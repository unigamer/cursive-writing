// Test driver for the single-file page, used by tests/test_web.py:
//
//   deno run --allow-read web/test/standalone_runner.js page.html requests.json
//
// Pulls the bundled engine out of the HTML, runs it the way standalone.js's
// in-page fallback does, and sends it the worker's own messages.
// requests.json is a list of {style, text, opts}; prints [{svg} or {error}].

const readText = globalThis.Deno
  ? (p) => Deno.readTextFile(p)
  : async (p) => (await import("node:fs/promises")).readFile(p, "utf8");
const [htmlPath, reqPath] = globalThis.Deno ? Deno.args : process.argv.slice(2);

const html = await readText(htmlPath);
const m = html.match(/<script type="text\/plain" id="cursive-engine">([\s\S]*?)<\/script>/);
if (!m) throw new Error("no engine script in the page");

const replies = new Map();
const self = { onmessage: null, postMessage: (d) => replies.get(d.id)(d) };
new Function("self", m[1])(self);

const requests = JSON.parse(await readText(reqPath));
const results = [];
for (const [i, r] of requests.entries()) {
  const id = i + 1;
  const reply = new Promise((resolve) => replies.set(id, resolve));
  self.onmessage({ data: { id, text: r.text, style: r.style, opts: r.opts } });
  const d = await reply;
  results.push(d.error ? { error: d.error } : { svg: d.svg });
}
console.log(JSON.stringify(results));
