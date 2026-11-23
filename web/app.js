// Page controller: reads the form, asks the worker for a page, shows it.
// Settings live in the URL hash, so a link reproduces the same writing.

const $ = (id) => document.getElementById(id);

// Set by the single-file build (tools/build_web.py --standalone, see
// standalone.js): it supplies the style list and an engine with the data inside.
const STANDALONE = window.CURSIVE_STANDALONE;

const DEFAULTS = {
  text: "Dear friend,\nThank you for everything.",
  style: "copperplate",
  size: 8,
  page: "a4",
  orient: "landscape",
  pw: 200,
  ph: 120,
  margin: 15,
  align: "left",
  seed: 3,
  variation: 1,
  pen: 0.35,
  shade: 0.5,
};
const NUMERIC = ["size", "pw", "ph", "margin", "seed", "variation", "pen", "shade"];
const PAGES_MM = { a3: [297, 420], a4: [210, 297], a5: [148, 210], a6: [105, 148], letter: [215.9, 279.4], dl: [220, 110], c5: [229, 162] };

// ------------------------------------------------------------ state <-> form

function readHash() {
  const s = { ...DEFAULTS };
  const h = new URLSearchParams(location.hash.slice(1));
  for (const k of Object.keys(DEFAULTS)) {
    if (!h.has(k)) continue;
    const v = h.get(k);
    if (NUMERIC.includes(k)) {
      const n = Number(v);
      if (Number.isFinite(n)) s[k] = n;
    } else s[k] = v;
  }
  return s;
}

function writeHash(s) {
  const h = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) if (v !== DEFAULTS[k]) h.set(k, String(v));
  const str = h.toString();
  history.replaceState(null, "", str ? `#${str}` : location.pathname + location.search);
}

const radio = (name) => document.querySelector(`input[name="${name}"]:checked`)?.value;
const setRadio = (name, v) => {
  const el = document.querySelector(`input[name="${name}"][value="${v}"]`);
  if (el) el.checked = true;
};

function toForm(s) {
  $("text").value = s.text;
  if ([...$("style").options].some((o) => o.value === s.style)) $("style").value = s.style;
  $("size").value = s.size;
  $("margin").value = s.margin;
  $("page").value = s.page in PAGES_MM || s.page === "custom" ? s.page : "a4";
  setRadio("orient", s.orient);
  $("page-w").value = s.pw;
  $("page-h").value = s.ph;
  setRadio("align", s.align);
  $("variation").value = s.variation;
  $("seed").value = s.seed;
  $("pen").value = s.pen;
  $("shade").value = s.shade;
}

function num(id, fallback, lo, hi) {
  const v = Number($(id).value);
  return Number.isFinite(v) && $(id).value !== "" ? Math.min(Math.max(v, lo), hi) : fallback;
}

function fromForm() {
  return {
    text: $("text").value,
    style: $("style").value || DEFAULTS.style,
    size: num("size", DEFAULTS.size, 0.5, 200),
    page: $("page").value,
    orient: radio("orient") ?? "portrait",
    pw: num("page-w", DEFAULTS.pw, 10, 5000),
    ph: num("page-h", DEFAULTS.ph, 10, 5000),
    margin: num("margin", DEFAULTS.margin, 0, 500),
    align: radio("align") ?? "left",
    seed: Math.trunc(num("seed", DEFAULTS.seed, 0, Number.MAX_SAFE_INTEGER)),
    variation: num("variation", DEFAULTS.variation, 0, 10),
    pen: num("pen", DEFAULTS.pen, 0.01, 10),
    shade: num("shade", DEFAULTS.shade, 0, 10),
  };
}

/** The CLI's --page value for these settings. */
function pageSpec(s) {
  if (s.page === "custom") return `${s.pw}x${s.ph}`;
  return s.orient === "landscape" ? `${s.page}-landscape` : s.page;
}

function pageDims(s) {
  if (s.page === "custom") return [s.pw, s.ph];
  const [w, h] = PAGES_MM[s.page] ?? PAGES_MM.a4;
  return s.orient === "landscape" ? [h, w] : [w, h];
}

const engineOpts = (s) => ({
  size: s.size,
  page: pageSpec(s),
  margin: s.margin,
  align: s.align,
  seed: s.seed,
  variation: s.variation,
  pen: s.pen,
  shade: s.shade,
});

// ------------------------------------------------------------ engine

let worker;
let latest = 0;
let current = null; // {svg, settings}

function startWorker() {
  worker = STANDALONE
    ? STANDALONE.worker()
    : new Worker(new URL("worker.js", import.meta.url), { type: "module" });
  worker.onmessage = (e) => onResult(e.data);
  worker.onerror = (e) => {
    e.preventDefault?.();
    showError(
      location.protocol === "file:"
        ? "This page has to be served over http to load its modules and style data, e.g. python3 -m http.server -d web"
        : `The generator failed to start: ${e.message || "unknown error"}`,
    );
  };
}

let timer = 0;
function schedule(delay = 120) {
  clearTimeout(timer);
  timer = setTimeout(run, delay);
}

function run() {
  const s = fromForm();
  writeHash(s);
  updateLabels(s);
  sizeSheet(s);
  latest += 1;
  $("sheet").classList.add("busy");
  worker.postMessage({ id: latest, text: s.text, style: s.style, opts: engineOpts(s), settings: s });
  pending.set(latest, s);
}
const pending = new Map();

function onResult(r) {
  const s = pending.get(r.id);
  pending.delete(r.id);
  if (r.id !== latest) return; // a newer request is on its way
  $("sheet").classList.remove("busy");
  if (r.error) return showError(r.error);
  current = { svg: r.svg, settings: s };
  showSvg(r.svg, s);
  const st = r.stats;
  $("status").classList.remove("error");
  $("status").textContent =
    `${r.lines} ${r.lines === 1 ? "line" : "lines"} · ${st.paths} pen strokes · ` +
    `${(st.pen_down_mm / 1000).toFixed(2)} m drawn · ${(st.pen_up_mm / 1000).toFixed(2)} m travel · ${Math.round(r.ms)} ms`;
  const ul = $("warnings");
  ul.replaceChildren(
    ...r.warnings.map((w) => {
      const li = document.createElement("li");
      li.textContent = w;
      return li;
    }),
  );
  setButtons(true);
}

function showError(msg) {
  $("sheet").classList.remove("busy");
  $("status").textContent = msg;
  $("status").classList.add("error");
  setButtons(Boolean(current));
}

function setButtons(on) {
  for (const id of ["dl-svg", "dl-png", "copy-cli"]) $(id).disabled = !on;
}

// ------------------------------------------------------------ preview

function sizeSheet(s) {
  const [w, h] = pageDims(s);
  const sheet = $("sheet");
  sheet.style.aspectRatio = `${w} / ${h}`;
  sheet.style.maxWidth = `max(260px, calc((100vh - 190px) * ${w / h}))`;
}

function showSvg(svg, s) {
  const doc = new DOMParser().parseFromString(svg, "image/svg+xml");
  const el = document.importNode(doc.documentElement, true);
  el.removeAttribute("width");
  el.removeAttribute("height");
  el.setAttribute("role", "img");
  el.setAttribute("aria-label", s.text);
  const sheet = $("sheet");
  sheet.replaceChildren(el);
  if ($("guides").checked) {
    const [w, h] = pageDims(s);
    const g = document.createElement("div");
    g.className = "guides";
    const mx = (100 * s.margin) / w;
    const my = (100 * s.margin) / h;
    Object.assign(g.style, { left: `${mx}%`, right: `${mx}%`, top: `${my}%`, bottom: `${my}%` });
    sheet.append(g);
  }
}

function updateLabels(s) {
  $("variation-out").textContent = s.variation.toFixed(2);
  $("shade-out").textContent = s.shade > 0 ? `${s.shade.toFixed(2)} mm` : "off";
  $("custom-page").hidden = s.page !== "custom";
  for (const el of document.querySelectorAll('input[name="orient"]')) el.disabled = s.page === "custom";
  const st = styleInfo.get(s.style);
  $("style-credit").textContent = st?.source_font ? `Built from ${st.source_font.replace(/\s*\(.*\)\s*$/, "")}` : "";
}

// ------------------------------------------------------------ downloads

function fileStem(s) {
  const words = s.text.trim().split(/\s+/).slice(0, 4).join("-").toLowerCase().replace(/[^a-z0-9-]+/g, "");
  return `cursive-${s.style}-${words || "page"}`;
}

function download(blob, name) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = name;
  document.body.append(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

function downloadSvg() {
  if (!current) return;
  download(new Blob([current.svg], { type: "image/svg+xml" }), `${fileStem(current.settings)}.svg`);
}

async function downloadPng() {
  if (!current) return;
  const dpi = 150; // as the CLI's --png
  const [w, h] = pageDims(current.settings);
  const k = dpi / 25.4;
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(w * k);
  canvas.height = Math.round(h * k);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff";
  ctx.fillRect(0, 0, canvas.width, canvas.height);
  const svg = current.svg.replace('stroke="black"', 'stroke="#19193c"');
  const url = URL.createObjectURL(new Blob([svg], { type: "image/svg+xml" }));
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    ctx.drawImage(img, 0, 0, canvas.width, canvas.height);
  } finally {
    URL.revokeObjectURL(url);
  }
  canvas.toBlob((b) => b && download(b, `${fileStem(current.settings)}.png`), "image/png");
}

const shQuote = (s) => `'${s.replace(/'/g, `'\\''`)}'`;

function cliCommand(s) {
  const d = { size: 6, margin: 20, align: "left", seed: 0, variation: 1, pen: 0.35, shade: 0 };
  const parts = ["python", "-m", "cursive.cli", shQuote(s.text.replace(/\n/g, "\\n")), "--style", s.style];
  const add = (flag, v, dv) => v !== dv && parts.push(flag, String(v));
  add("--size", s.size, d.size);
  add("--page", pageSpec(s), "a4");
  add("--margin", s.margin, d.margin);
  add("--align", s.align, d.align);
  add("--seed", s.seed, d.seed);
  add("--variation", s.variation, d.variation);
  add("--pen", s.pen, d.pen);
  add("--shade", s.shade, d.shade);
  parts.push("-o", `${fileStem(s)}.svg`);
  return parts.join(" ");
}

async function copyCli() {
  const cmd = cliCommand(fromForm());
  try {
    await navigator.clipboard.writeText(cmd);
    flash($("copy-cli"), "Copied");
  } catch {
    window.prompt("Command:", cmd);
  }
}

function flash(btn, text) {
  const old = btn.textContent;
  btn.textContent = text;
  setTimeout(() => (btn.textContent = old), 1200);
}

// ------------------------------------------------------------ start

const styleInfo = new Map();

async function init() {
  setButtons(false);
  startWorker();
  try {
    let styles;
    if (STANDALONE) styles = STANDALONE.styles;
    else {
      const r = await fetch(new URL("data/index.json", import.meta.url));
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      ({ styles } = await r.json());
    }
    for (const st of styles) {
      styleInfo.set(st.id, st);
      $("style").append(new Option(st.name, st.id));
    }
  } catch (err) {
    showError(
      location.protocol === "file:"
        ? "Open this page through a web server (it loads its style data with fetch), e.g. python3 -m http.server -d web"
        : `Could not load the style list (${err.message}). Run python tools/build_web.py to build web/data/.`,
    );
    return;
  }
  toForm(readHash());
  $("controls").addEventListener("input", (e) => schedule(e.target.id === "text" ? 220 : 60));
  $("controls").addEventListener("change", () => schedule(0));
  $("reseed").addEventListener("click", () => {
    $("seed").value = Math.floor(Math.random() * 100000);
    schedule(0);
  });
  $("dl-svg").addEventListener("click", downloadSvg);
  $("dl-png").addEventListener("click", downloadPng);
  $("copy-cli").addEventListener("click", copyCli);
  // The single-file page shows its licences in-page; open them without
  // touching the URL hash, which holds the settings.
  $("licences-link").addEventListener("click", (e) => {
    const box = $("licences");
    if (!box) return; // served page: follow the link to LICENSES.txt
    e.preventDefault();
    box.open = true;
    box.scrollIntoView({ behavior: "smooth" });
  });
  window.addEventListener("hashchange", () => {
    toForm(readHash());
    schedule(0);
  });
  // warm the other styles in the background so switching is instant
  for (const id of styleInfo.keys()) worker.postMessage({ id: 0, style: id, preload: true });
  run();
}

init();
