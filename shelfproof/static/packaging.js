const MAX_BYTES = 20 * 1024 * 1024;
const HEX = /^[0-9a-f]+$/;
const initialHash = location.hash;
const job = () => new URLSearchParams(location.search).get("job");
const base = () => `/api/jobs/${job()}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const file = (name) => String(name).split("/").pop();

const dialog = document.createElement("dialog");
dialog.id = "lab";
dialog.setAttribute("aria-labelledby", "lab-title");
dialog.innerHTML = `
<div class="lab-head">
  <h2 id="lab-title">Packaging lab</h2>
  <p id="lab-status" role="status" aria-live="polite"></p>
  <button type="button" id="lab-close">Close</button>
</div>
<div class="lab-body">
  <section class="lab-products" aria-labelledby="lab-products-h">
    <h3 id="lab-products-h">Products in this photo</h3>
    <ul id="lab-product-list"></ul>
    <button type="button" id="lab-new">New product</button>
  </section>
  <section id="lab-pick" class="lab-step" aria-labelledby="lab-instr">
    <p id="lab-instr"><strong>Click your product, or drag a box around it.</strong> Keyboard: focus the photo, move the crosshair with arrow keys (Shift for bigger steps), press Enter.</p>
    <div id="lab-stage" tabindex="0" role="application" aria-label="Shelf photo for selecting a product" aria-describedby="lab-instr">
      <img id="lab-photo" alt="Original shelf photo" draggable="false">
      <div id="lab-mask" hidden></div>
      <div id="lab-bbox" hidden></div>
      <div id="lab-drag" hidden></div>
      <div id="lab-cursor" hidden></div>
    </div>
    <div class="lab-row" id="lab-verdict" hidden>
      <button type="button" id="lab-yes">Looks right</button>
      <button type="button" id="lab-retry">Try again</button>
    </div>
  </section>
  <div id="lab-current" class="lab-current" hidden>
    <img id="lab-cutout" alt="">
    <p id="lab-current-text"></p>
    <button type="button" id="lab-reselect">Change selection</button>
  </div>
  <form id="lab-confirm" class="lab-step" hidden>
    <h3>About this product</h3>
    <label><span>Product name <span aria-hidden="true">*</span></span><input name="name" required maxlength="80" autocomplete="off"></label>
    <label>Category<input name="category" list="lab-categories" maxlength="60" placeholder="e.g. breakfast cereal"></label>
    <datalist id="lab-categories"><option>breakfast cereal</option><option>snacks</option><option>beverages</option><option>dairy</option><option>confectionery</option><option>household</option><option>personal care</option></datalist>
    <fieldset>
      <legend>Extra photos (optional, improves consistency)</legend>
      <label>Side photo<input type="file" name="side" accept="image/*"></label>
      <img class="lab-thumb" data-preview="side" alt="Side photo preview" hidden>
      <label>Back photo<input type="file" name="back" accept="image/*"></label>
      <img class="lab-thumb" data-preview="back" alt="Back photo preview" hidden>
      <p class="lab-hint">Images up to 20 MB.</p>
    </fieldset>
    <button>Continue to brief</button>
  </form>
  <form id="lab-brief" class="lab-step" hidden>
    <h3>Design brief</h3>
    <label>Target audience<input name="target_audience" id="lab-audience" maxlength="300"></label>
    <div class="lab-row" role="group" aria-label="Audience suggestions">
      <button type="button" class="lab-chip">budget families</button>
      <button type="button" class="lab-chip">health-conscious young professionals</button>
      <button type="button" class="lab-chip">premium foodies</button>
      <button type="button" class="lab-chip">students</button>
    </div>
    <fieldset class="lab-row">
      <legend>Price tier</legend>
      <label class="lab-inline"><input type="radio" name="price_tier" value="value"> Value</label>
      <label class="lab-inline"><input type="radio" name="price_tier" value="mid" checked> Mid</label>
      <label class="lab-inline"><input type="radio" name="price_tier" value="premium"> Premium</label>
    </fieldset>
    <label>Brand tone<select name="brand_tone">
      <option>friendly</option><option>playful</option><option>bold</option><option>natural and wholesome</option><option>elegant and premium</option><option>clinical and trustworthy</option><option>retro</option>
    </select></label>
    <label>Keep<input name="keep" value="brand name and logo" maxlength="300"></label>
    <label>Avoid<input name="avoid" maxlength="300" placeholder="e.g. cartoon mascots"></label>
    <label>Notes<textarea name="notes" rows="3" maxlength="1000"></textarea></label>
    <fieldset class="lab-models">
      <legend>Image model</legend>
      <label class="lab-model"><input type="radio" name="model" value="gpt-image-2.5-sunburst" checked aria-describedby="lab-model-gpt"> <span><strong>GPT-Image-2.5 Sunburst</strong> <span class="lab-hint" id="lab-model-gpt">best text &amp; editing, ~$0.06/image</span></span></label>
      <label class="lab-model"><input type="radio" name="model" value="nano-banana-pro" aria-describedby="lab-model-nano"> <span><strong>Nano Banana Pro</strong> <span class="lab-hint" id="lab-model-nano">~$0.14/image</span></span></label>
    </fieldset>
    <label>Number of variants<input type="number" name="count" min="1" max="4" value="2" required></label>
    <p class="lab-hint">Paid generation: each concept uses two image calls (design the pack, then put it on the shelf). Expect about 30–70 s in total.</p>
    <button>Generate concepts</button>
  </form>
  <section id="lab-results" class="lab-step" hidden aria-labelledby="lab-results-h">
    <h3 id="lab-results-h">Packaging concepts</h3>
    <p class="lab-caption">AI-generated concepts. Check label text and claims before use.</p>
    <p id="lab-summary" class="lab-hint" hidden></p>
    <div id="lab-grid" class="lab-grid"></div>
    <section id="lab-compare" hidden aria-labelledby="lab-compare-h">
      <h4 id="lab-compare-h">Compare</h4>
      <div class="lab-side">
        <figure><img id="lab-cmp-a" alt="Original shelf"><figcaption>Original shelf</figcaption></figure>
        <figure><img id="lab-cmp-b" alt=""><figcaption id="lab-cmp-b-cap"></figcaption></figure>
      </div>
      <div class="lab-slider" id="lab-slider">
        <img id="lab-sl-b" alt="">
        <img id="lab-sl-a" class="lab-top" alt="Original shelf (before)">
        <div class="lab-handle" aria-hidden="true"></div>
      </div>
      <label>Before / after (left: original, right: concept)<input type="range" id="lab-range" min="0" max="100" value="50"></label>
    </section>
  </section>
</div>`;
document.body.append(dialog);

const $ = (id) => document.getElementById(id);
const photo = $("lab-photo"), stage = $("lab-stage");
const S = { pid: null, vid: null, product: null, products: [], pending: false, token: 0, cursor: null, filesKey: "" };

function status(msg, { busy = false, error = false } = {}) {
  const el = $("lab-status");
  el.textContent = msg;
  el.classList.toggle("lab-busy", busy);
  el.classList.toggle("lab-error", error);
}
const fail = (e) => status(e.message || String(e), { error: true });

async function api(path, opts) {
  const res = await fetch(base() + path, opts);
  const text = await res.text();
  let data;
  try { data = JSON.parse(text); } catch { data = text; }
  if (!res.ok) {
    const d = data?.detail;
    throw new Error(d ? (typeof d === "string" ? d : JSON.stringify(d)) : `Request failed (${res.status}).`);
  }
  return data;
}
const postJSON = (body) => ({ method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });

function setPending(value) {
  S.pending = value;
  stage.setAttribute("aria-busy", String(value));
  for (const el of dialog.querySelectorAll("button, input, select, textarea")) if (el.id !== "lab-close") el.disabled = value;
}

function writeHash() {
  if (!dialog.open) return;
  history.replaceState(null, "", `${location.pathname}${location.search}#${["lab", S.pid, S.vid].filter(Boolean).join("/")}`);
}

function showStep(step) {
  for (const id of ["lab-pick", "lab-confirm", "lab-brief", "lab-results"]) $(id).hidden = id !== `lab-${step}`;
  $("lab-current").hidden = step === "pick" || !S.product;
  if (S.product) {
    $("lab-cutout").src = `${base()}/products/${S.pid}/cutout.png`;
    $("lab-current-text").textContent = S.product.name ? `${S.product.name}${S.product.category ? ` · ${S.product.category}` : ""}` : "Selected product";
  }
  writeHash();
}

function contentRect() {
  const r = photo.getBoundingClientRect(), nw = photo.naturalWidth, nh = photo.naturalHeight;
  const s = Math.min(r.width / nw, r.height / nh);
  const ox = (r.width - nw * s) / 2, oy = (r.height - nh * s) / 2;
  return { s, ox, oy, left: r.left + ox, top: r.top + oy, nw, nh };
}
function place(el, x0, y0, x1, y1) {
  const c = contentRect();
  Object.assign(el.style, { left: `${c.ox + x0 * c.s}px`, top: `${c.oy + y0 * c.s}px`, width: `${(x1 - x0) * c.s}px`, height: `${(y1 - y0) * c.s}px` });
  el.hidden = false;
}
function layout() {
  if (!photo.naturalWidth) return;
  if (S.product?.bbox && !$("lab-bbox").hidden) place($("lab-bbox"), ...S.product.bbox);
  if (S.cursor) {
    const hidden = $("lab-cursor").hidden;
    place($("lab-cursor"), S.cursor.x, S.cursor.y, S.cursor.x, S.cursor.y);
    $("lab-cursor").hidden = hidden;
  }
}
new ResizeObserver(layout).observe(stage);

function clearOverlay() {
  for (const id of ["lab-mask", "lab-bbox", "lab-drag", "lab-verdict"]) $(id).hidden = true;
}

function loadImage(url) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error(`Could not load ${file(url)}.`));
    img.src = url;
  });
}

async function showMask(p) {
  const url = `${base()}/products/${p.pid}/mask.png`;
  await loadImage(url);
  $("lab-mask").style.setProperty("--mask", `url("${url}")`);
  $("lab-mask").hidden = false;
  $("lab-bbox").hidden = false;
  layout();
  $("lab-verdict").hidden = false;
}

async function segment(body) {
  if (S.pending) return;
  S.token++;
  clearOverlay();
  setPending(true);
  status("Finding your product… this takes a few seconds.", { busy: true });
  try {
    const p = await api("/products", postJSON(body));
    S.product = p; S.pid = p.pid; S.vid = null;
    writeHash();
    await showMask(p);
    status(`Found a product${Number.isFinite(p.score) ? ` (confidence ${p.score.toFixed(2)})` : ""}. Does the highlight match it?`);
    loadProducts().catch(fail);
  } catch (e) { fail(e); }
  finally { setPending(false); }
  if (!$("lab-verdict").hidden) $("lab-yes").focus();
}

let drag = null;
stage.addEventListener("pointerdown", (e) => {
  if (S.pending || !photo.naturalWidth || e.button !== 0) return;
  stage.setPointerCapture(e.pointerId);
  drag = { x: e.clientX, y: e.clientY, moved: false };
});
stage.addEventListener("pointermove", (e) => {
  if (!drag) return;
  if (Math.hypot(e.clientX - drag.x, e.clientY - drag.y) > 6) drag.moved = true;
  if (!drag.moved) return;
  const [a, b] = [toSource(drag.x, drag.y), toSource(e.clientX, e.clientY)];
  place($("lab-drag"), Math.min(a.x, b.x), Math.min(a.y, b.y), Math.max(a.x, b.x), Math.max(a.y, b.y));
});
stage.addEventListener("pointerup", (e) => {
  if (!drag) return;
  const d = drag;
  drag = null;
  $("lab-drag").hidden = true;
  const a = toSource(d.x, d.y), b = toSource(e.clientX, e.clientY);
  if (d.moved) {
    const box = { x0: Math.floor(Math.min(a.x, b.x)), y0: Math.floor(Math.min(a.y, b.y)), x1: Math.ceil(Math.max(a.x, b.x)), y1: Math.ceil(Math.max(a.y, b.y)) };
    if (box.x1 - box.x0 >= 4 && box.y1 - box.y0 >= 4) return segment({ box });
  }
  if (!b.inside) return status("Click on the photo itself, not the letterbox around it.", { error: true });
  segment({ point: { x: Math.round(b.x), y: Math.round(b.y) } });
});
stage.addEventListener("pointercancel", () => { drag = null; $("lab-drag").hidden = true; });

function toSource(clientX, clientY) {
  const c = contentRect();
  const x = (clientX - c.left) / c.s, y = (clientY - c.top) / c.s;
  return { x: clamp(x, 0, c.nw - 1), y: clamp(y, 0, c.nh - 1), inside: x >= 0 && y >= 0 && x < c.nw && y < c.nh };
}

stage.addEventListener("keydown", (e) => {
  if (S.pending || !photo.naturalWidth) return;
  const nw = photo.naturalWidth, nh = photo.naturalHeight;
  S.cursor ??= { x: nw / 2, y: nh / 2 };
  const step = (e.shiftKey ? 0.1 : 0.02) * Math.max(nw, nh);
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[e.key]) {
    S.cursor = { x: clamp(S.cursor.x + moves[e.key][0], 0, nw - 1), y: clamp(S.cursor.y + moves[e.key][1], 0, nh - 1) };
    layout();
    $("lab-cursor").hidden = false;
  } else if (e.key === "Enter" || e.key === " ") {
    segment({ point: { x: Math.round(S.cursor.x), y: Math.round(S.cursor.y) } });
  } else return;
  e.preventDefault();
});
stage.addEventListener("focus", () => { if (S.cursor) $("lab-cursor").hidden = false; });
stage.addEventListener("blur", () => { $("lab-cursor").hidden = true; });

function startPick() {
  S.token++;
  S.product = null; S.pid = null; S.vid = null;
  clearOverlay();
  for (const btn of $("lab-product-list").querySelectorAll(".lab-product, .lab-set")) btn.setAttribute("aria-current", "false");
  showStep("pick");
  status("Click your product, or drag a box around it.");
  stage.focus({ preventScroll: true });
}

$("lab-new").onclick = startPick;
$("lab-retry").onclick = startPick;
$("lab-reselect").onclick = startPick;
$("lab-yes").onclick = () => {
  showStep("confirm");
  const f = $("lab-confirm").elements;
  f.namedItem("name").value = S.product.name || "";
  f.namedItem("category").value = S.product.category || "";
  status("Name your product to continue.");
  f.namedItem("name").focus();
};

for (const input of $("lab-confirm").querySelectorAll('input[type="file"]')) {
  input.addEventListener("change", () => {
    const preview = dialog.querySelector(`[data-preview="${input.name}"]`);
    const f = input.files[0];
    if (preview.src) URL.revokeObjectURL(preview.src);
    preview.hidden = true;
    preview.removeAttribute("src");
    if (!f) return;
    if (!f.type.startsWith("image/") || f.size > MAX_BYTES) {
      input.value = "";
      return status(`The ${input.name} photo must be an image no larger than 20 MB.`, { error: true });
    }
    preview.src = URL.createObjectURL(f);
    preview.hidden = false;
  });
}

$("lab-confirm").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (S.pending) return;
  const f = e.target.elements, body = new FormData();
  const name = f.namedItem("name").value.trim(), category = f.namedItem("category").value.trim();
  if (!name) return f.namedItem("name").focus();
  body.append("name", name);
  body.append("category", category);
  for (const key of ["side", "back"]) if (f.namedItem(key).files[0]) body.append(key, f.namedItem(key).files[0]);
  setPending(true);
  status("Saving product…", { busy: true });
  try {
    const res = await api(`/products/${S.pid}/confirm`, { method: "POST", body });
    Object.assign(S.product, typeof res === "object" && res ? res : {}, { name, category });
    toBrief();
    loadProducts().catch(fail);
  } catch (err) { fail(err); }
  finally { setPending(false); }
});

function toBrief() {
  showStep("brief");
  status("Describe who the new packaging is for.");
  $("lab-audience").focus();
}

for (const chip of dialog.querySelectorAll(".lab-chip")) chip.onclick = () => { $("lab-audience").value = chip.textContent; };

$("lab-brief").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (S.pending) return;
  const data = Object.fromEntries(new FormData(e.target));
  const brief = { ...data, product_name: S.product.name, category: S.product.category || "", count: clamp(Math.round(Number(data.count)) || 2, 1, 4), quality: "high" };
  setPending(true);
  status("Starting generation…", { busy: true });
  try {
    const res = await api(`/products/${S.pid}/variants`, postJSON(brief));
    S.vid = res.variant_set_id;
    rememberSet(S.pid, S.vid);
    await showResults();
  } catch (err) { fail(err); }
  finally { setPending(false); }
});

const MODELS = { "gpt-image-2.5-sunburst": "GPT-Image-2.5 Sunburst", "nano-banana-pro": "Nano Banana Pro" };
const PLACEMENTS = { edit: "Edited into shelf", composite: "Composited" };
const setsKey = () => `shelfproof:sets:${job()}`;
function knownSets() {
  try { return JSON.parse(localStorage.getItem(setsKey())) || {}; } catch { return {}; }
}
function rememberSet(pid, vid) {
  const sets = knownSets();
  if (sets[pid]?.includes(vid)) return;
  sets[pid] = [...(sets[pid] || []), vid];
  try { localStorage.setItem(setsKey(), JSON.stringify(sets)); } catch { return; }
  loadProducts().catch(fail);
}

async function showResults() {
  const token = ++S.token;
  S.filesKey = "";
  S.compareK = null;
  $("lab-grid").replaceChildren();
  $("lab-summary").hidden = true;
  $("lab-compare").hidden = true;
  showStep("results");
  status("Loading concepts…", { busy: true });
  pollVariants(token).catch((e) => { if (token === S.token) fail(e); });
}

async function pollVariants(token) {
  const path = `/products/${S.pid}/variants/${S.vid}`;
  for (;;) {
    const v = await api(path);
    if (token !== S.token) return;
    rememberSet(S.pid, S.vid);
    renderResults(v, path);
    const n = v.total ?? "?";
    if (v.state === "done") return status(`Done · ${n} concept${n === 1 ? "" : "s"}.`);
    if (v.state === "failed") throw new Error(v.error || "Generation failed.");
    status(`Generating packaging concepts… ${v.done_count ?? 0}/${n} done. Each concept takes two image calls (design, then shelf placement), about 30–70 s in total. Keep this tab open.`, { busy: true });
    await sleep(2500);
    if (token !== S.token) return;
  }
}

function renderResults(v, path) {
  const names = Array.isArray(v.files) ? v.files.map(file) : [];
  const has = (name) => names.includes(name);
  const total = Math.max(Number(v.total) || 0, ...names.map((n) => Number(n.match(/_(\d)\.png$/)?.[1]) || 0));
  const running = v.state === "running";
  const summary = [v.model && (MODELS[v.model] || v.model), Number.isFinite(v.cost) && `total cost $${v.cost.toFixed(2)}`].filter(Boolean).join(" · ");
  $("lab-summary").textContent = summary;
  $("lab-summary").hidden = !summary;
  const key = JSON.stringify([names, total, running, v.placements, v.prompts]);
  if (key === S.filesKey) return;
  S.filesKey = key;
  const url = (name) => `${base()}${path}/${name}`;
  const focused = document.activeElement?.closest?.("#lab-grid [data-action]");
  const refocus = focused && `[data-action="${focused.dataset.action}"][data-k="${focused.dataset.k}"]`;
  const cards = [];
  for (let k = 1; k <= total; k++) {
    const pack = `variant_${k}.png`, shelf = `shelf_${k}.png`;
    const placement = PLACEMENTS[v.placements?.[k] ?? v.placements?.[String(k)]];
    if (!has(pack) && !has(shelf)) {
      if (running) cards.push(`<article class="lab-card lab-pending" aria-busy="true"><h4>Concept ${k}</h4><p class="lab-hint">Generating…</p></article>`);
      continue;
    }
    cards.push(`
    <article class="lab-card" aria-labelledby="lab-card-${k}">
      <div class="lab-card-head"><h4 id="lab-card-${k}">Concept ${k}</h4>${placement ? `<span class="lab-tag">${placement}</span>` : ""}</div>
      ${has(pack) ? `<figure><img class="lab-packshot" src="${esc(url(pack))}" alt="Concept ${k} packshot" loading="lazy"><figcaption>Packshot</figcaption></figure>` : ""}
      ${has(shelf) ? `<figure><img src="${esc(url(shelf))}" alt="Concept ${k} on the shelf" loading="lazy"><figcaption>On shelf</figcaption></figure>` : `<p class="lab-hint">${running ? "Placing on shelf…" : "No shelf image."}</p>`}
      ${v.prompts?.[k - 1] ? `<details><summary>Prompt</summary><p>${esc(v.prompts[k - 1])}</p></details>` : ""}
      ${has(shelf) ? `<div class="lab-row">
        <button type="button" class="lab-view3d" data-action="view3d" data-k="${k}">View on 3D shelf</button>
        <button type="button" class="lab-compare-btn" data-action="compare" data-k="${k}" aria-pressed="false">Compare with original</button>
      </div>` : ""}
      <p class="lab-row lab-downloads">
        ${has(pack) ? `<a href="${esc(url(pack))}" download="concept_${k}_packshot.png">Download packshot</a>` : ""}
        ${has(shelf) ? `<a href="${esc(url(shelf))}" download="concept_${k}_shelf.png">Download shelf</a>` : ""}
      </p>
    </article>`);
  }
  $("lab-grid").innerHTML = cards.join("") || (running ? "" : `<p class="lab-hint">No concepts were produced.</p>`);
  for (const btn of $("lab-grid").querySelectorAll("[data-action]")) {
    const k = Number(btn.dataset.k), shelfUrl = url(`shelf_${k}.png`);
    btn.onclick = btn.dataset.action === "compare" ? () => compare(k, shelfUrl) : () => viewOnShelf(k, shelfUrl);
    btn.disabled = S.pending;
  }
  if (refocus) $("lab-grid").querySelector(refocus)?.focus();
  const firstShelf = [...Array(total).keys()].map((i) => i + 1).find((k) => has(`shelf_${k}.png`));
  if (S.compareK && has(`shelf_${S.compareK}.png`)) compare(S.compareK, url(`shelf_${S.compareK}.png`));
  else if (firstShelf) compare(firstShelf, url(`shelf_${firstShelf}.png`));
}

async function viewOnShelf(k, shelfUrl) {
  if (!window.shelfproof?.showTexture) return status("The 3D viewer is not available in this browser.", { error: true });
  S.keepHash = true;
  dialog.close();
  await window.shelfproof.showTexture(shelfUrl, `Concept ${k} on shelf`);
}

function compare(k, shelfUrl) {
  S.compareK = k;
  for (const btn of $("lab-grid").querySelectorAll(".lab-compare-btn")) btn.setAttribute("aria-pressed", String(Number(btn.dataset.k) === k));
  const src = `${base()}/source.png`;
  for (const id of ["lab-cmp-a", "lab-sl-a"]) if ($(id).getAttribute("src") !== src) $(id).src = src;
  for (const id of ["lab-cmp-b", "lab-sl-b"]) if ($(id).getAttribute("src") !== shelfUrl) $(id).src = shelfUrl;
  $("lab-cmp-b").alt = $("lab-sl-b").alt = `Concept ${k} on the shelf (after)`;
  $("lab-cmp-b-cap").textContent = `Concept ${k} on shelf`;
  $("lab-compare-h").textContent = `Original shelf vs. concept ${k}`;
  $("lab-compare").hidden = false;
}
$("lab-range").addEventListener("input", (e) => $("lab-slider").style.setProperty("--pos", `${e.target.value}%`));

async function loadProducts() {
  const list = await api("/products");
  S.products = Array.isArray(list) ? list : [];
  const known = knownSets();
  $("lab-product-list").innerHTML = S.products.length ? S.products.map((p) => {
    const listed = (p.variant_sets || []).map((s) => typeof s === "string" ? s : s?.variant_set_id);
    const sets = [...new Set([...listed, ...(known[p.pid] || [])])].filter((s) => typeof s === "string" && HEX.test(s));
    return `<li>
      <button type="button" class="lab-product" data-pid="${esc(p.pid)}" aria-current="${p.pid === S.pid}">
        <img src="${esc(`${base()}/products/${p.pid}/crop.png`)}" alt="" loading="lazy">
        <span>${esc(p.name || "Unconfirmed selection")}</span>
      </button>
      ${sets.map((vid, i) => `<button type="button" class="lab-set" data-pid="${esc(p.pid)}" data-vid="${esc(vid)}" aria-current="${vid === S.vid}" aria-label="Concept set ${i + 1} for ${esc(p.name || "this selection")}">Concepts ${i + 1}</button>`).join("")}
    </li>`;
  }).join("") : "<li class=\"lab-hint\">None yet.</li>";
  for (const btn of $("lab-product-list").querySelectorAll("button")) {
    btn.onclick = () => selectProduct(btn.dataset.pid, btn.dataset.vid);
    btn.disabled = S.pending;
  }
}

async function selectProduct(pid, vid) {
  if (S.pending) return;
  const p = S.products.find((x) => x.pid === pid);
  if (!p) return status("That product is no longer available for this job.", { error: true });
  S.token++;
  S.product = p; S.pid = pid; S.vid = vid || null;
  for (const btn of $("lab-product-list").querySelectorAll(".lab-product, .lab-set")) {
    btn.setAttribute("aria-current", String(btn.dataset.pid === pid && (!btn.dataset.vid || btn.dataset.vid === S.vid)));
  }
  if (vid) return showResults();
  if (p.name) return toBrief();
  clearOverlay();
  showStep("pick");
  try {
    await showMask(p);
    status("Does the highlight match your product?");
  } catch (e) { fail(e); }
}

async function open(restore = []) {
  if (!job() || !HEX.test(job())) return;
  if (!dialog.open) dialog.showModal();
  S.token++;
  S.product = null; S.pid = null; S.vid = null;
  clearOverlay();
  showStep("pick");
  status("Loading original photo…", { busy: true });
  const src = `${base()}/source.png`;
  if (photo.getAttribute("src") !== src) photo.src = src;
  try {
    await photo.decode();
    stage.style.aspectRatio = `${photo.naturalWidth} / ${photo.naturalHeight}`;
    status("Click your product, or drag a box around it.");
  } catch {
    status("Could not load the original photo for this job. Phase 2 needs a job with a stored source photo.", { error: true });
  }
  try {
    await loadProducts();
    const [pid, vid] = restore;
    if (pid && HEX.test(pid)) await selectProduct(pid, vid && HEX.test(vid) ? vid : undefined);
  } catch (e) { fail(e); }
}

$("lab-close").onclick = () => dialog.close();
dialog.addEventListener("close", () => {
  S.token++;
  if (!S.keepHash) history.replaceState(null, "", `${location.pathname}${location.search}`);
  S.keepHash = false;
  document.getElementById("packaging-lab")?.focus();
});

const labButton = document.getElementById("packaging-lab");
const modes = document.getElementById("modes");
if (labButton) {
  labButton.onclick = () => {
    const [tag, pid, vid] = location.hash.slice(1).split("/");
    open(tag === "lab" ? [pid, vid] : []);
  };
  const sync = () => { labButton.hidden = !job() || !!modes?.hidden; };
  if (modes) new MutationObserver(sync).observe(modes, { attributes: true, attributeFilter: ["hidden"] });
  sync();
}

const [tag, ...restore] = initialHash.slice(1).split("/");
if (tag === "lab") open(restore);
document.addEventListener("DOMContentLoaded", writeHash);
