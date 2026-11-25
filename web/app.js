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
  ink: "#000000",
  paper: "#ffffff",
  transparent: false,
};
const NUMERIC = ["size", "pw", "ph", "margin", "seed", "variation", "pen", "shade"];
const BOOLEAN = ["transparent"];
const COLOURS = ["ink", "paper"];
const HEX = /^#[0-9a-f]{6}$/i;
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
    } else if (BOOLEAN.includes(k)) s[k] = v === "1";
    else if (COLOURS.includes(k)) s[k] = HEX.test(v) ? v.toLowerCase() : DEFAULTS[k];
    else s[k] = v;
  }
  return s;
}

function writeHash(s) {
  const h = new URLSearchParams();
  for (const [k, v] of Object.entries(s)) {
    if (v !== DEFAULTS[k]) h.set(k, typeof v === "boolean" ? (v ? "1" : "0") : String(v));
  }
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
  $("ink").value = s.ink;
  $("paper").value = s.paper;
  $("transparent").checked = s.transparent;
}

function num(id, fallback, lo, hi) {
  const v = Number($(id).value);
  return Number.isFinite(v) && $(id).value !== "" ? Math.min(Math.max(v, lo), hi) : fallback;
}

const colour = (id) => (HEX.test($(id).value) ? $(id).value.toLowerCase() : DEFAULTS[id]);

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
    ink: colour("ink"),
    paper: colour("paper"),
    transparent: $("transparent").checked,
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

/** The engine's SVG (always drawn in black) in the chosen ink colour. */
const inked = (svg, ink) => (ink === "#000000" ? svg : svg.replace('stroke="black"', `stroke="${ink}"`));

/** Show the ink and page colours in the preview without asking the engine again. */
function applyInk(s) {
  $("sheet").style.setProperty("--ink-stroke", s.ink);
  $("sheet").style.setProperty("--page-colour", s.paper);
  $("viewport").classList.toggle("clear", s.transparent);
  $("paper").disabled = s.transparent; // a transparent PNG has no page colour
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

function restyle() {
  const s = fromForm();
  writeHash(s);
  applyInk(s);
  if (!current) return;
  const guidesChanged = Boolean($("sheet").querySelector(".guides")) !== $("guides").checked;
  current.settings = { ...current.settings, ink: s.ink, paper: s.paper, transparent: s.transparent };
  if (guidesChanged) showSvg(current.svg, current.settings);
}

function run() {
  const s = fromForm();
  writeHash(s);
  applyInk(s);
  updateLabels(s);
  sizeSheet(s);
  latest += 1;
  $("sheet").classList.add("busy");
  worker.postMessage({ id: latest, text: s.text, style: s.style, opts: engineOpts(s), settings: s });
  pending.set(latest, s);
}
const pending = new Map();

function onResult(r) {
  if (r.sample) return showSample(r);
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
  showChars(r.chars);
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

let shownChars = "";
function showChars(groups) {
  const key = JSON.stringify(groups);
  if (!groups || key === shownChars) return;
  shownChars = key;
  $("charset-list").replaceChildren(
    ...groups.flatMap(([name, chars]) => {
      const dt = document.createElement("dt");
      dt.textContent = name[0].toUpperCase() + name.slice(1);
      const dd = document.createElement("dd");
      const spaced = !["lowercase", "capitals", "digits"].includes(name); // easier to tell apart
      dd.textContent = spaced ? Array.from(chars).join(" ") : chars;
      return [dt, dd];
    }),
  );
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

let sheetShape = "";

function sizeSheet(s) {
  const [w, h] = pageDims(s);
  const shape = `${w} / ${h}`;
  if (shape === sheetShape) return;
  sheetShape = shape;
  const vp = $("viewport");
  vp.style.aspectRatio = shape;
  vp.style.maxWidth = `max(260px, calc((100vh - 270px) * ${w / h}))`;
  $("sheet").style.aspectRatio = shape;
  setZoom(1); // a different page: start from the whole sheet again
}

// ------------------------------------------------------------ zoom and pan
//
// The viewport keeps the page's fitted size; zooming widens the sheet inside
// it (so the SVG is redrawn sharp, not scaled as a bitmap) and panning
// scrolls the viewport. Pinch or Ctrl/Cmd + wheel zooms about the pointer.

const ZOOM_MIN = 1;
const ZOOM_MAX = 16;
const ZOOM_STEP = 1.5;
let zoom = 1;

/** Zoom to z, keeping the point (cx, cy) of the viewport (in px) still. */
function setZoom(z, cx, cy) {
  const vp = $("viewport");
  z = Math.min(ZOOM_MAX, Math.max(ZOOM_MIN, z));
  if (cx === undefined) [cx, cy] = [vp.clientWidth / 2, vp.clientHeight / 2];
  const k = z / zoom;
  const left = (vp.scrollLeft + cx) * k - cx;
  const top = (vp.scrollTop + cy) * k - cy;
  zoom = z;
  $("sheet").style.width = `${z * 100}%`;
  vp.scrollLeft = left; // the browser clamps these to the sheet
  vp.scrollTop = top;
  vp.classList.toggle("zoomed", z > 1);
  $("zoom-level").textContent = `${Math.round(z * 100)}%`;
  $("zoom-out").disabled = z <= ZOOM_MIN;
  $("zoom-in").disabled = z >= ZOOM_MAX;
  $("zoom-fit").disabled = z === 1;
}

function initZoom() {
  const vp = $("viewport");
  const local = (e) => {
    const r = vp.getBoundingClientRect();
    return [e.clientX - r.left, e.clientY - r.top];
  };

  $("zoom-in").addEventListener("click", () => setZoom(zoom * ZOOM_STEP));
  $("zoom-out").addEventListener("click", () => setZoom(zoom / ZOOM_STEP));
  $("zoom-fit").addEventListener("click", () => setZoom(1));

  vp.addEventListener(
    "wheel",
    (e) => {
      const px = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? vp.clientHeight : 1;
      if (e.ctrlKey || e.metaKey) {
        // trackpad pinches arrive as ctrl + wheel
        e.preventDefault();
        setZoom(zoom * Math.exp(-e.deltaY * px * 0.0025), ...local(e));
        return;
      }
      if (zoom === 1) return; // let the page scroll
      const dx = e.shiftKey && !e.deltaX ? e.deltaY : e.deltaX;
      const dy = e.shiftKey && !e.deltaX ? 0 : e.deltaY;
      const canX = (dx < 0 && vp.scrollLeft > 0) || (dx > 0 && vp.scrollLeft < vp.scrollWidth - vp.clientWidth - 1);
      const canY = (dy < 0 && vp.scrollTop > 0) || (dy > 0 && vp.scrollTop < vp.scrollHeight - vp.clientHeight - 1);
      if (!canX && !canY) return; // at the edge: scroll the page instead
      e.preventDefault();
      vp.scrollLeft += dx * px;
      vp.scrollTop += dy * px;
    },
    { passive: false },
  );

  // drag to pan; two fingers pinch and pan together
  const pointers = new Map();
  let last = null; // {x, y, dist} of the previous move
  const gesture = () => {
    const ps = [...pointers.values()];
    const x = ps.reduce((a, p) => a + p.x, 0) / ps.length;
    const y = ps.reduce((a, p) => a + p.y, 0) / ps.length;
    const dist = ps.length > 1 ? Math.hypot(ps[0].x - ps[1].x, ps[0].y - ps[1].y) : 0;
    return { x, y, dist };
  };
  vp.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse" && e.button !== 0) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (pointers.size === 1 && zoom === 1 && e.pointerType !== "mouse") return; // page scroll
    try {
      vp.setPointerCapture(e.pointerId); // keep panning when the pointer leaves the preview
    } catch { /* not an active pointer (e.g. already lifted) */ }
    last = gesture();
  });
  vp.addEventListener("pointermove", (e) => {
    if (!pointers.has(e.pointerId)) return;
    pointers.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (!last || (pointers.size === 1 && zoom === 1)) return;
    const g = gesture();
    if (pointers.size > 1 && last.dist > 0) {
      const r = vp.getBoundingClientRect();
      setZoom(zoom * (g.dist / last.dist), g.x - r.left, g.y - r.top);
    }
    vp.scrollLeft -= g.x - last.x;
    vp.scrollTop -= g.y - last.y;
    if (Math.abs(g.x - last.x) + Math.abs(g.y - last.y) > 0) vp.classList.add("dragging");
    last = g;
  });
  const lift = (e) => {
    pointers.delete(e.pointerId);
    last = pointers.size ? gesture() : null;
    if (!pointers.size) vp.classList.remove("dragging");
  };
  vp.addEventListener("pointerup", lift);
  vp.addEventListener("pointercancel", lift);

  vp.addEventListener("dblclick", (e) => {
    e.preventDefault();
    setZoom(zoom < 3 ? 4 : 1, ...local(e));
  });

  vp.addEventListener("keydown", (e) => {
    const pan = 60;
    const keys = {
      "+": () => setZoom(zoom * ZOOM_STEP),
      "=": () => setZoom(zoom * ZOOM_STEP),
      "-": () => setZoom(zoom / ZOOM_STEP),
      0: () => setZoom(1),
      ArrowLeft: () => (vp.scrollLeft -= pan),
      ArrowRight: () => (vp.scrollLeft += pan),
      ArrowUp: () => (vp.scrollTop -= pan),
      ArrowDown: () => (vp.scrollTop += pan),
    };
    if (e.ctrlKey || e.metaKey || e.altKey || !keys[e.key]) return;
    if (e.key.startsWith("Arrow") && zoom === 1) return; // nothing to pan; let the page scroll
    e.preventDefault();
    keys[e.key]();
  });
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
  updatePicker(s.style);
  const st = styleInfo.get(s.style);
  $("style-credit").textContent = st?.source_font ? `Built from ${st.source_font.replace(/\s*\(.*\)\s*$/, "")}` : "";
}

// ------------------------------------------------------------ style picker
//
// A listbox in place of the <select> (kept, hidden, as the form's value) so
// each style's name can be shown written in that style by the engine itself.

const SAMPLE_OPTS = { size: 5, page: "400x60", margin: 10, align: "left", seed: 0, variation: 0, pen: 0.35, shade: 0 };
const samples = new Map(); // style id -> <svg> cropped to its ink

function requestSamples() {
  for (const [id, st] of styleInfo) {
    worker.postMessage({ id: 0, sample: id, style: id, text: st.name, opts: SAMPLE_OPTS });
  }
}

/** The engine's page, cropped to the writing. Paths are "M x,y L x,y x,y ...". */
function showSample(r) {
  if (r.error) return;
  const doc = new DOMParser().parseFromString(r.svg, "image/svg+xml");
  const svg = doc.documentElement;
  let [x0, y0, x1, y1] = [Infinity, Infinity, -Infinity, -Infinity];
  for (const p of svg.querySelectorAll("path")) {
    const n = p.getAttribute("d").match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
    for (let i = 0; i + 1 < n.length; i += 2) {
      x0 = Math.min(x0, n[i]); x1 = Math.max(x1, n[i]);
      y0 = Math.min(y0, n[i + 1]); y1 = Math.max(y1, n[i + 1]);
    }
  }
  if (!Number.isFinite(x0)) return;
  const pad = 0.6;
  svg.setAttribute("viewBox", `${x0 - pad} ${y0 - pad} ${x1 - x0 + 2 * pad} ${y1 - y0 + 2 * pad}`);
  svg.removeAttribute("width");
  svg.removeAttribute("height");
  svg.querySelector("title")?.remove();
  svg.setAttribute("aria-hidden", "true");
  svg.setAttribute("focusable", "false");
  samples.set(r.sample, document.importNode(svg, true));
  for (const el of document.querySelectorAll(`[data-style="${r.sample}"] .sample`)) {
    el.replaceChildren(samples.get(r.sample).cloneNode(true));
  }
}

function sampleEl(id) {
  const box = document.createElement("span");
  box.className = "sample";
  box.dataset.fallback = styleInfo.get(id)?.name ?? id;
  const svg = samples.get(id);
  if (svg) box.append(svg.cloneNode(true));
  return box;
}

function pickerItem(id) {
  const name = document.createElement("span");
  name.className = "picker-name";
  name.textContent = styleInfo.get(id)?.name ?? id;
  return [sampleEl(id), name];
}

function buildPicker() {
  const list = $("style-list");
  list.replaceChildren(
    ...[...styleInfo.keys()].map((id) => {
      const li = document.createElement("li");
      li.id = `style-opt-${id}`;
      li.setAttribute("role", "option");
      li.dataset.style = id;
      li.append(...pickerItem(id));
      li.addEventListener("click", () => choose(id));
      return li;
    }),
  );
  const btn = $("style-button");
  btn.addEventListener("click", () => (list.hidden ? openPicker() : closePicker(false)));
  btn.addEventListener("keydown", (e) => {
    if (["ArrowDown", "ArrowUp"].includes(e.key)) {
      e.preventDefault();
      openPicker();
    }
  });
  list.addEventListener("keydown", (e) => {
    const ids = [...styleInfo.keys()];
    const at = ids.indexOf(list.getAttribute("aria-activedescendant")?.slice(10));
    const go = (i) => highlight(ids[(i + ids.length) % ids.length]);
    if (e.key === "ArrowDown") go(at + 1);
    else if (e.key === "ArrowUp") go(at - 1);
    else if (e.key === "Home") go(0);
    else if (e.key === "End") go(ids.length - 1);
    else if (e.key === "Enter" || e.key === " ") choose(ids[at]);
    else if (e.key === "Escape") closePicker(true);
    else if (e.key === "Tab") closePicker(false);
    else return;
    e.preventDefault();
  });
  list.addEventListener("mousemove", (e) => {
    const li = e.target.closest("li");
    if (li) highlight(li.dataset.style, false);
  });
  document.addEventListener("pointerdown", (e) => {
    if (!list.hidden && !e.target.closest(".picker")) closePicker(false);
  });
}

function highlight(id, scroll = true) {
  const list = $("style-list");
  for (const li of list.children) li.classList.toggle("active", li.dataset.style === id);
  list.setAttribute("aria-activedescendant", `style-opt-${id}`);
  if (scroll) $(`style-opt-${id}`)?.scrollIntoView({ block: "nearest" });
}

function openPicker() {
  const list = $("style-list");
  list.hidden = false;
  $("style-button").setAttribute("aria-expanded", "true");
  highlight($("style").value);
  list.focus();
}

function closePicker(refocus) {
  $("style-list").hidden = true;
  $("style-button").setAttribute("aria-expanded", "false");
  if (refocus) $("style-button").focus();
}

function choose(id) {
  closePicker(true);
  if (!id || id === $("style").value) return;
  $("style").value = id;
  $("style").dispatchEvent(new Event("change", { bubbles: true }));
}

let pickerShown = "";
function updatePicker(id) {
  for (const li of $("style-list").children) li.setAttribute("aria-selected", String(li.dataset.style === id));
  const key = `${id}:${samples.has(id)}`;
  if (key === pickerShown) return;
  pickerShown = key;
  const btn = $("style-button");
  btn.dataset.style = id;
  btn.replaceChildren(...pickerItem(id));
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
  const svg = inked(current.svg, current.settings.ink);
  download(new Blob([svg], { type: "image/svg+xml" }), `${fileStem(current.settings)}.svg`);
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
  if (!current.settings.transparent) {
    ctx.fillStyle = current.settings.paper;
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  const svg = inked(current.svg, current.settings.ink);
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
  $("view-opts").addEventListener("input", restyle);
  $("view-opts").addEventListener("change", restyle);
  $("dl-svg").addEventListener("click", downloadSvg);
  $("dl-png").addEventListener("click", downloadPng);
  $("copy-cli").addEventListener("click", copyCli);
  initZoom();
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
  buildPicker();
  run();
  // write each style's name in that style; this also loads every style so switching is instant
  requestSamples();
}

init();
