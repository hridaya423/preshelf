const PID = /^[0-9a-f]{8}$/;
const MAX_SLOTS = 8;
const DISCLAIMER = "Model estimate under stated assumptions; not measured shopper behaviour.";
const KINDS = { current: "current position", swap: "swap with product", place: "place on shelf" };
const ASSUME = { shelf_top_cm: "Shelf top (cm)", shelf_bottom_cm: "Shelf bottom (cm)", photo_distance_m: "Photo distance (m)" };
const initialHash = location.hash;
const job = () => new URLSearchParams(location.search).get("job");
const base = () => `/api/jobs/${job()}`;
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => `&#${c.charCodeAt(0)};`);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const file = (name) => String(name).split("/").pop();
const num = (v, d) => (Number.isFinite(v) ? (Number.isInteger(v) ? String(v) : v.toFixed(d)) : "–");
const pct = (v) => (Number.isFinite(v) ? `${(v * 100).toFixed(1)}%` : "–");
const parseHash = (h) => { const [tag, pid, rid] = h.slice(1).split(/[:/]/); return tag === "placement" ? [pid, rid] : null; };

const dialog = document.createElement("dialog");
dialog.id = "placement";
dialog.setAttribute("aria-labelledby", "pl-title");
dialog.innerHTML = `
<header class="pl-head">
  <strong class="pl-brand">PreShelf</strong>
  <h2 id="pl-title">Placement test</h2>
  <div class="pl-head-actions"><button type="button" id="pl-theme">Switch theme</button><button type="button" id="pl-close">Back to shelf</button></div>
</header>
<div class="pl-body">
  <div class="pl-workbar">
    <details class="pl-products" id="pl-products" open>
      <summary>Product <strong id="pl-product-name">Choose a selection</strong></summary>
      <ul id="pl-product-list"></ul>
    </details>
    <details id="pl-history"><summary>Run history</summary><div class="pl-history-body"><p class="pl-hint">Runs opened in this browser. To revisit an older run, paste its eight-character run ID or open its saved link.</p><ul id="pl-history-list"></ul><form id="pl-open-run"><label>Run ID<input name="rid" pattern="[0-9a-f]{8}" maxlength="8" required placeholder="e.g. a1b2c3d4"></label><button>Open run</button></form></div></details>
    <nav class="pl-nav" aria-label="Placement workspace"><button type="button" id="pl-show-setup" aria-pressed="true">Slots & shoppers</button><button type="button" id="pl-show-results" aria-pressed="false" disabled>Results</button></nav>
  </div>
  <p class="pl-disclaimer">${DISCLAIMER} <span id="pl-server-disclaimer"></span></p>
  <form id="pl-setup" class="pl-workspace" hidden>
    <section class="pl-canvas" aria-labelledby="pl-slots-h">
      <div class="pl-section-head"><h3 id="pl-slots-h">Compare shelf positions</h3><span class="pl-hint" id="pl-slot-count"></span></div>
      <div class="pl-canvas-bed"><div id="pl-stage" tabindex="0" role="application" aria-label="Shelf photo for adding slots" aria-describedby="pl-instr">
        <img id="pl-photo" alt="Original shelf photo" draggable="false">
        <div id="pl-mask" hidden></div><div id="pl-boxes"></div><div id="pl-cursor" hidden></div>
      </div></div>
      <p id="pl-instr" class="pl-hint">Click a product to swap, or empty shelf to place. Keyboard: focus the photo, use arrow keys (Shift for bigger steps), then Enter to add. Compare up to ${MAX_SLOTS} slots, including the current position.</p>
    </section>
    <aside class="pl-inspector" aria-label="Placement settings">
      <div class="pl-section-head"><h3>Test settings</h3><button id="pl-run" type="submit">Run placement test</button></div>
      <details open class="pl-settings"><summary>Slots & optional costs</summary>
        <p class="pl-hint">Tick slots to include. The current position stays as your baseline.</p>
        <ol id="pl-slot-list"></ol>
        <p class="pl-hint">Costs are optional and <strong>user-entered</strong>, such as a known slotting fee. They stay in this browser and only calculate attention share per £100.</p>
      </details>
      <details class="pl-settings" id="pl-shopper-settings"><summary>Shopper personas <span id="pl-persona-count"></span></summary>
        <p class="pl-hint">Compare eye heights, shopping missions and time pressure.</p>
        <div id="pl-personas" class="pl-cards"></div><button type="button" id="pl-add-persona">Add persona</button>
      </details>
      <details class="pl-settings"><summary>Assumptions & score formula</summary>
        <p class="pl-formula">Score: <code id="pl-formula"></code></p>
        <fieldset class="pl-assume"><legend>Shelf & camera assumptions</legend>
          ${Object.entries(ASSUME).map(([k, l]) => `<label>${l}<input type="number" name="${k}" min="0" step="any" required></label>`).join("")}
        </fieldset><div id="pl-rationale" class="pl-hint"></div>
      </details>
    </aside>
  </form>
  <section id="pl-results" hidden aria-labelledby="pl-results-h">
    <div class="pl-workspace">
      <section class="pl-canvas" aria-labelledby="pl-results-h">
        <div class="pl-section-head"><h3 id="pl-results-h">Attention heatmap</h3><span class="pl-hint">Model estimate</span></div>
        <div class="pl-canvas-bed"><div class="pl-heat pl-big"><img id="pl-v-scene" alt=""><img id="pl-v-heat" class="pl-over" alt=""></div></div>
        <p id="pl-v-cap" class="pl-hint"></p>
      </section>
      <aside class="pl-inspector" aria-label="Result selection">
        <article id="pl-rec" class="pl-rec"></article>
        <div class="pl-view-controls">
          <label>Inspect slot<select id="pl-v-slot"></select></label>
          <fieldset><legend>Shopper persona</legend><div role="group" aria-label="Persona" id="pl-v-personas"></div></fieldset>
          <label class="pl-inline"><input type="checkbox" id="pl-v-sal"> Saliency only (no persona priors)</label>
          <label>Overlay opacity<input type="range" id="pl-v-op" min="0" max="100" value="80"></label>
          <button type="button" id="pl-v-3d">View in 3D</button>
        </div>
        <details class="pl-settings"><summary>Result assumptions & formula</summary><p class="pl-hint" id="pl-r-formula"></p><dl id="pl-r-assumptions"></dl></details>
      </aside>
    </div>
    <details class="pl-result-detail" open><summary>All slots at a glance</summary><div id="pl-multi" class="pl-multi"></div></details>
    <details class="pl-result-detail" open><summary>Ranked results & score breakdowns</summary><div class="pl-scroll" tabindex="0" role="region" aria-label="Ranked placement results"><table id="pl-table"></table></div></details>
  </section>
</div>
<footer class="pl-statusbar"><p id="pl-status" role="status" aria-live="polite"></p></footer>`;
document.body.append(dialog);

const $ = (id) => document.getElementById(id);
const photo = $("pl-photo"), stage = $("pl-stage");
const S = { job: null, token: 0, products: [], pid: null, rid: null, layout: null, meta: null, personas: [], slots: [], costs: {}, size: [1, 1], cursor: null, busy: false, running: false, R: null, sel: null };

function status(msg, { busy = false, error = false } = {}) {
  const el = $("pl-status");
  el.textContent = msg;
  el.classList.toggle("pl-busy", busy);
  el.classList.toggle("pl-error", error);
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

function writeHash() {
  if (dialog.open) history.replaceState(null, "", `${location.pathname}${location.search}#${["placement", S.pid, S.rid].filter(Boolean).join(":")}`);
}
const storeKey = () => `shelfproof:placement:${job()}`;

function showView(results) {
  $("pl-setup").hidden = results || !S.pid;
  $("pl-results").hidden = !results;
  $("pl-show-setup").setAttribute("aria-pressed", String(!results));
  $("pl-show-results").setAttribute("aria-pressed", String(results));
  $("pl-show-results").disabled = !S.R;
}
$("pl-show-setup").onclick = () => showView(false);
$("pl-show-results").onclick = () => { if (S.R) renderResults(S.R, true); };
$("pl-setup").addEventListener("invalid", (e) => {
  for (let p = e.target.parentElement; p && p !== dialog; p = p.parentElement) if (p.tagName === "DETAILS") p.open = true;
}, true);
function syncTheme() {
  $("pl-theme").textContent = `${document.documentElement.dataset.theme === "dark" ? "Light" : "Dark"} theme`;
}
$("pl-theme").onclick = () => $("theme")?.click();
new MutationObserver(syncTheme).observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
syncTheme();

function renderHistory(run) {
  let runs = [];
  try {
    const saved = JSON.parse(localStorage.getItem(`${storeKey()}:runs`) || "[]");
    runs = Array.isArray(saved) ? saved.filter((r) => PID.test(r.pid) && PID.test(r.rid)) : [];
    if (run) {
      runs = [run, ...runs.filter((r) => r.rid !== run.rid)].slice(0, 20);
      localStorage.setItem(`${storeKey()}:runs`, JSON.stringify(runs));
    }
  } catch { /* storage unavailable */ }
  $("pl-history-list").innerHTML = runs.length ? runs.map((r) => `<li><button type="button" data-pid="${r.pid}" data-rid="${r.rid}">${esc(r.name || "Placement run")} <span class="pl-hint">${r.rid}</span></button></li>`).join("") : '<li class="pl-hint">No runs opened here yet.</li>';
}
$("pl-history-list").onclick = (e) => {
  const b = e.target.closest("[data-rid]");
  if (b) { $("pl-history").open = false; selectProduct(b.dataset.pid, b.dataset.rid); }
};
$("pl-open-run").onsubmit = async (e) => {
  e.preventDefault();
  const rid = e.target.elements.rid.value;
  try {
    const run = await api(`/placement/runs/${rid}`);
    $("pl-history").open = false;
    await selectProduct(run.request.pid, rid);
  } catch (err) { fail(err); }
};

function renderProducts() {
  const selected = S.products.find((p) => p.pid === S.pid);
  $("pl-product-name").textContent = selected?.name || (selected ? "Unnamed selection" : "Choose a selection");
  $("pl-products").open = !selected;
  $("pl-product-list").innerHTML = S.products.length ? S.products.map((p) => `<li>
    <button type="button" class="pl-product" data-pid="${esc(p.pid)}" aria-current="${p.pid === S.pid}">
      <img src="${esc(`${base()}/products/${p.pid}/cutout.png`)}" alt="" loading="lazy"><span>${esc(p.name || "Unnamed selection")}</span>
    </button></li>`).join("")
    : `<li><p class="pl-hint">No products yet. Select your product in the Packaging lab first.</p><button type="button" id="pl-to-lab">Open Packaging lab</button></li>`;
  for (const b of $("pl-product-list").querySelectorAll("[data-pid]")) b.onclick = () => selectProduct(b.dataset.pid);
  const toLab = $("pl-to-lab");
  if (toLab) toLab.onclick = () => { dialog.close(); document.getElementById("packaging-lab")?.click(); };
}

const box = ([x0, y0, x1, y1]) => { const [w, h] = S.size; return `left:${x0 / w * 100}%;top:${y0 / h * 100}%;width:${(x1 - x0) / w * 100}%;height:${(y1 - y0) / h * 100}%`; };
const onCount = () => S.slots.filter((s) => s.on).length;

function renderSlots() {
  const full = onCount() >= MAX_SLOTS, det = S.cand?.product_det;
  $("pl-slot-count").textContent = `${onCount()} / ${MAX_SLOTS} slots included`;
  $("pl-boxes").innerHTML = (S.layout?.detections || []).map((d) => `<div class="pl-det${d.id === det ? " pl-prod" : ""}" style="${box(d.bbox)}"></div>`).join("")
    + S.slots.map((s, i) => `<div class="pl-rect${s.on ? " pl-on" : ""}" style="${box(s.rect)}"><button type="button" tabindex="-1" aria-hidden="true" data-chip="${i}">${i + 1}</button></div>`).join("");
  $("pl-slot-list").innerHTML = S.slots.map((s, i) => {
    const locked = s.kind === "current";
    return `<li class="pl-slot">
      <label class="pl-inline"><input type="checkbox" data-slot="${i}"${s.on ? " checked" : ""}${locked || (!s.on && full) ? " disabled" : ""}>
        <span class="pl-num" aria-hidden="true">${i + 1}</span><span>${esc(s.label)}<small class="pl-hint">${esc(KINDS[s.kind] || s.kind)}${locked ? " · always included" : ""}</small></span></label>
      <label class="pl-cost">Optional cost (£)<input type="number" min="0" step="any" inputmode="decimal" data-cost="${esc(s.id)}" value="${esc(S.costs[s.id] ?? "")}"></label>
      ${s.user ? `<button type="button" data-del="${i}" aria-label="Remove slot ${i + 1}: ${esc(s.label)}">Remove</button>` : ""}
    </li>`;
  }).join("");
}
$("pl-slot-list").addEventListener("change", (e) => {
  const i = e.target.dataset.slot;
  if (i === undefined) return;
  S.slots[i].on = e.target.checked;
  renderSlots();
  $("pl-slot-list").querySelector(`[data-slot="${i}"]`)?.focus();
});
$("pl-slot-list").addEventListener("input", (e) => { if (e.target.dataset.cost) S.costs[e.target.dataset.cost] = e.target.value; });
$("pl-slot-list").addEventListener("click", (e) => {
  const i = e.target.dataset.del;
  if (i === undefined) return;
  const [gone] = S.slots.splice(Number(i), 1);
  renderSlots();
  status(`Removed slot: ${gone.label}.`);
  $("pl-slot-list").querySelector("input")?.focus();
});

function toSource(cx, cy) {
  const r = photo.getBoundingClientRect(), [w, h] = S.size;
  return { x: clamp((cx - r.left) / r.width * w, 0, w - 1), y: clamp((cy - r.top) / r.height * h, 0, h - 1) };
}
async function addSlot({ x, y }) {
  if (S.busy || !S.pid) return;
  if (onCount() >= MAX_SLOTS) return status(`Up to ${MAX_SLOTS} slots: untick one before adding another.`, { error: true });
  S.busy = true;
  stage.setAttribute("aria-busy", "true");
  status("Adding slot…", { busy: true });
  try {
    const slot = await api("/placement/slot", postJSON({ pid: S.pid, x: Math.round(x), y: Math.round(y) }));
    const dup = S.slots.find((s) => s.id === slot.id);
    if (dup) dup.on = true; else S.slots.push({ ...slot, on: true, user: true });
    renderSlots();
    status(`${dup ? "Already listed" : "Added"}: ${slot.label}.`);
  } catch (e) { fail(e); }
  finally { S.busy = false; stage.setAttribute("aria-busy", "false"); }
}
stage.addEventListener("click", (e) => {
  const chip = e.target.closest("[data-chip]");
  if (!chip) return addSlot(toSource(e.clientX, e.clientY));
  const s = S.slots[chip.dataset.chip];
  if (s.kind === "current") return;
  if (!s.on && onCount() >= MAX_SLOTS) return status(`Up to ${MAX_SLOTS} slots: untick one first.`, { error: true });
  s.on = !s.on;
  renderSlots();
});
stage.addEventListener("keydown", (e) => {
  if (!S.pid) return;
  const [w, h] = S.size;
  S.cursor ??= { x: w / 2, y: h / 2 };
  const step = (e.shiftKey ? 0.1 : 0.02) * Math.max(w, h);
  const moves = { ArrowLeft: [-step, 0], ArrowRight: [step, 0], ArrowUp: [0, -step], ArrowDown: [0, step] };
  if (moves[e.key]) S.cursor = { x: clamp(S.cursor.x + moves[e.key][0], 0, w - 1), y: clamp(S.cursor.y + moves[e.key][1], 0, h - 1) };
  else if (e.key === "Enter" || e.key === " ") addSlot(S.cursor);
  else return;
  e.preventDefault();
  Object.assign($("pl-cursor").style, { left: `${S.cursor.x / w * 100}%`, top: `${S.cursor.y / h * 100}%` });
  $("pl-cursor").hidden = false;
});
stage.addEventListener("blur", () => { $("pl-cursor").hidden = true; });

function renderPersonas() {
  const { missions, time_pressure: tp } = S.meta, n = S.personas.length;
  const opts = (obj, v) => Object.entries(obj).map(([k, o]) => `<option value="${esc(k)}"${k === v ? " selected" : ""}>${esc(o.label || k)}</option>`).join("");
  $("pl-personas").innerHTML = S.personas.map((p, i) => `<fieldset class="pl-card"><legend>Persona ${i + 1}</legend>
    <label>Name<input data-i="${i}" data-k="name" maxlength="40" required value="${esc(p.name)}"></label>
    <label>Eye height (cm)<input type="number" data-i="${i}" data-k="eye_height_cm" min="80" max="200" step="any" required value="${esc(p.eye_height_cm)}"></label>
    <label>Viewing distance (m)<input type="number" data-i="${i}" data-k="distance_m" min="0.3" max="5" step="any" required value="${esc(p.distance_m)}"></label>
    <label>Mission<select data-i="${i}" data-k="mission">${opts(missions, p.mission)}</select></label>
    <label>Time pressure<select data-i="${i}" data-k="time_pressure">${opts(tp, p.time_pressure)}</select></label>
    <button type="button" data-remove="${i}"${n <= 1 ? " disabled" : ""}>Remove persona ${i + 1}</button>
  </fieldset>`).join("");
  $("pl-add-persona").disabled = n >= 6;
  $("pl-persona-count").textContent = `(${n})`;
}
$("pl-personas").addEventListener("input", (e) => { const { i, k } = e.target.dataset; if (k) S.personas[i][k] = e.target.value; });
$("pl-personas").addEventListener("click", (e) => {
  const i = e.target.dataset.remove;
  if (i === undefined || S.personas.length <= 1) return;
  S.personas.splice(Number(i), 1);
  renderPersonas();
  $("pl-add-persona").focus();
});
$("pl-add-persona").onclick = () => {
  if (S.personas.length >= 6) return;
  const presets = S.meta.presets;
  S.personas.push({ ...presets[S.personas.length % presets.length], name: `Persona ${S.personas.length + 1}` });
  renderPersonas();
  $("pl-personas").querySelector(".pl-card:last-child input")?.focus();
};

function initMeta(meta) {
  S.meta = meta;
  S.personas = (meta.presets || []).slice(0, 6).map((p) => ({ ...p }));
  $("pl-formula").textContent = meta.formula || "";
  $("pl-server-disclaimer").textContent = meta.disclaimer && meta.disclaimer !== DISCLAIMER ? meta.disclaimer : "";
  const f = $("pl-setup").elements;
  for (const k of Object.keys(ASSUME)) f.namedItem(k).value = meta.assumptions?.[k] ?? "";
  const line = (title, o) => `<li><strong>${esc(title)}:</strong> ${esc(o.rationale)}</li>`;
  $("pl-rationale").innerHTML = `<p>Why these settings matter:</p><ul>${Object.entries(meta.missions || {}).map(([k, m]) => line(m.label || k, m)).join("")}${Object.entries(meta.time_pressure || {}).map(([k, t]) => line(`${k} time pressure`, t)).join("")}</ul>`;
  renderPersonas();
}

async function loadLayout(token) {
  let L = await api("/placement/layout");
  if (L.state === "missing") L = await api("/placement/layout", { method: "POST" });
  while (L.state === "running") {
    status("Detecting shelf layout… first run can take ~1 min.", { busy: true });
    await sleep(2000);
    if (token !== S.token) return null;
    L = await api("/placement/layout");
  }
  if (L.state !== "done") throw new Error(L.error || "Shelf layout detection failed.");
  return L;
}

function sizeStage([w, h]) {
  S.size = [w, h];
  stage.style.aspectRatio = `${w} / ${h}`;
  stage.style.width = "100%";
}

async function selectProduct(pid, rid) {
  if (!PID.test(pid) || !S.products.some((p) => p.pid === pid)) return status("That product is not available for this job. Pick another.", { error: true });
  const token = ++S.token;
  setRunning(false);
  S.pid = pid; S.rid = null; S.cand = null; S.slots = []; S.R = null;
  pack.hidden = true;
  showView(false);
  try { localStorage.setItem(storeKey(), pid); } catch { /* storage unavailable */ }
  writeHash();
  renderProducts();
  renderSlots();
  $("pl-results").hidden = true;
  $("pl-setup").hidden = false;
  $("pl-mask").hidden = true;
  try {
    S.layout ??= await loadLayout(token);
    if (token !== S.token || !S.layout) return;
    sizeStage(S.layout.source_size || [photo.naturalWidth, photo.naturalHeight]);
    status("Finding candidate slots…", { busy: true });
    const cand = await api(`/placement/candidates?pid=${pid}`);
    if (token !== S.token) return;
    S.cand = cand;
    const slots = cand.slots || [];
    S.slots = [...slots.filter((s) => s.kind === "current"), ...slots.filter((s) => s.kind !== "current")].map((s, i) => ({ ...s, on: i < MAX_SLOTS, user: false }));
    $("pl-mask").style.setProperty("--mask", `url("${base()}/products/${pid}/mask.png")`);
    $("pl-mask").hidden = false;
    renderSlots();
    loadPackSets(pid).catch(fail);
    status("Pick slots and personas, then run the test.");
    if (rid && PID.test(rid)) await watchRun(rid, token);
  } catch (e) { if (token === S.token) fail(e); }
}

$("pl-setup").addEventListener("submit", async (e) => {
  e.preventDefault();
  if (S.running || !S.pid) return;
  const f = e.target.elements;
  const assumptions = Object.fromEntries(Object.keys(ASSUME).map((k) => [k, Number(f.namedItem(k).value)]));
  if (assumptions.shelf_top_cm <= assumptions.shelf_bottom_cm) return status("Shelf top must be higher than shelf bottom.", { error: true });
  const slots = S.slots.filter((s) => s.on).map(({ on, user, ...s }) => s);
  if (!slots.length) return status("Tick at least one slot.", { error: true });
  const personas = S.personas.map((p) => ({ ...p, name: p.name.trim(), eye_height_cm: Number(p.eye_height_cm), distance_m: Number(p.distance_m) }));
  const token = ++S.token;
  status("Starting run…", { busy: true });
  try {
    const { run_id } = await api("/placement/runs", postJSON({ pid: S.pid, slots, personas, assumptions }));
    await watchRun(run_id, token);
  } catch (err) { if (token === S.token) fail(err); }
});

async function watchRun(rid, token) {
  S.rid = rid;
  writeHash();
  setRunning(true);
  try {
    for (;;) {
      const r = await api(`/placement/runs/${rid}`);
      if (token !== S.token) return;
      if (r.state === "done" && r.results) {
        S.request = r.request;
        renderHistory({ pid: S.pid, rid, name: S.products.find((p) => p.pid === S.pid)?.name });
        renderResults(r.results);
        return status(`Done · ${r.results.slots.length} slots × ${r.results.personas.length} personas.`);
      }
      if (r.state === "failed") throw new Error(r.error || "Placement run failed.");
      status(`${r.stage || "Running"}… ${r.done_count ?? 0}/${r.total ?? "?"} done. Keep this tab open.`, { busy: true });
      await sleep(2000);
      if (token !== S.token) return;
    }
  } finally { if (token === S.token) setRunning(false); }
}
function setRunning(v) { S.running = v; $("pl-run").disabled = v; $("pl-run").textContent = v ? "Test running…" : "Run placement test"; }

const pp = (s, p) => s.per_persona.find((x) => x.persona === p) ?? s.per_persona[p];
const runFile = (name) => `${base()}/placement/runs/${S.rid}/${file(name)}`;
const cost = (s) => { const c = Number(S.costs[s.id]); return S.costs[s.id] && c > 0 ? c : null; };

function renderResults(R, preserveSelection = false) {
  S.R = R;
  if (!preserveSelection) S.sel = { slot: R.recommendation?.slot ?? R.ranking[0], p: 0, sal: false };
  $("pl-r-assumptions").innerHTML = Object.entries(S.request?.assumptions || {}).map(([k, v]) => `<dt>${esc(ASSUME[k] || k)}</dt><dd>${esc(v)}</dd>`).join("");
  $("pl-r-formula").innerHTML = `<strong>${esc(R.disclaimer || DISCLAIMER)}</strong>${R.formula ? ` Score: <code>${esc(R.formula)}</code>` : ""}`;
  const best = R.slots[R.recommendation?.slot];
  $("pl-rec").innerHTML = best ? `<h4>Recommended slot: ${esc(best.label)}</h4><ul>${(R.recommendation.reasons || []).map((r) => `<li>${esc(r)}</li>`).join("")}</ul>` : "<p>No recommendation returned.</p>";
  const cur = R.slots.find((s) => s.kind === "current"), anyCost = R.slots.some(cost);
  const cols = 5 + R.personas.length + (anyCost ? 1 : 0);
  $("pl-table").innerHTML = `<caption>Slots ranked by mean final attention share</caption>
    <thead><tr><th scope="col">Rank</th><th scope="col">Slot</th><th scope="col">Mean final share</th><th scope="col">Mean rank among products</th>
    ${R.personas.map((p) => `<th scope="col">${esc(p.name)}</th>`).join("")}<th scope="col">Δ vs current</th>${anyCost ? `<th scope="col">Share per £100 (your cost)</th>` : ""}</tr></thead>
    <tbody>${R.ranking.map((i, k) => {
      const s = R.slots[i], n = s.per_persona[0]?.n_products, c = cost(s);
      const d = cur && s !== cur ? (s.mean_final_share - cur.mean_final_share) * 100 : null;
      return `<tr${i === R.recommendation?.slot ? ' class="pl-best"' : ""}><td>${k + 1}</td><th scope="row">${esc(s.label)}</th><td>${pct(s.mean_final_share)}</td>
        <td>#${num(s.mean_rank, 1)} of ${esc(n ?? "?")}</td>
        ${R.personas.map((_, p) => `<td>${pct(pp(s, p)?.final_share)}</td>`).join("")}
        <td>${s === cur ? "current" : d === null ? "–" : `${d > 0 ? "+" : ""}${d.toFixed(1)} pp`}</td>
        ${anyCost ? `<td>${c ? `${(s.mean_final_share * 100 / c * 100).toFixed(2)}%` : "–"}</td>` : ""}</tr>
      <tr class="pl-break"><td colspan="${cols}"><details><summary>Score breakdown: ${esc(s.label)}</summary>
        <table><thead><tr><th scope="col">Persona</th><th scope="col">Saliency share</th><th scope="col">Position factor</th><th scope="col">Final share</th><th scope="col">Rank</th></tr></thead>
        <tbody>${R.personas.map((p, j) => { const x = pp(s, j) || {}; return `<tr><th scope="row">${esc(p.name)}</th><td>${pct(x.saliency_share)}</td><td>${num(x.position_factor, 3)}</td><td>${pct(x.final_share)}</td><td>#${esc(x.rank ?? "?")} of ${esc(x.n_products ?? "?")}</td></tr>`; }).join("")}</tbody></table>
      </details></td></tr>`;
    }).join("")}</tbody>`;
  $("pl-v-slot").innerHTML = R.ranking.map((i) => `<option value="${i}">${esc(R.slots[i].label)}</option>`).join("");
  $("pl-v-personas").innerHTML = R.personas.map((p, j) => `<button type="button" data-p="${j}" aria-pressed="false">${esc(p.name)}</button>`).join("");
  $("pl-v-sal").checked = S.sel.sal;
  $("pl-v-3d").disabled = !window.shelfproof?.showTexture;
  showView(true);
  updateViewer();
}

function heatFor(s, p) { const x = pp(s, p) || {}; return runFile(S.sel.sal ? x.saliency_heatmap : x.heatmap); }
function updateViewer() {
  const { R, sel } = S, s = R.slots[sel.slot], x = pp(s, sel.p) || {}, name = R.personas[sel.p]?.name;
  $("pl-v-slot").value = String(sel.slot);
  for (const b of $("pl-v-personas").children) b.setAttribute("aria-pressed", String(Number(b.dataset.p) === sel.p));
  $("pl-v-scene").src = runFile(s.scene);
  $("pl-v-scene").alt = `Shelf with the product at ${s.label}`;
  $("pl-v-heat").src = heatFor(s, sel.p);
  $("pl-v-heat").alt = `${sel.sal ? "Saliency" : "Attention"} heatmap for ${name}`;
  $("pl-v-cap").textContent = `${s.label} · ${name} · ${sel.sal ? "saliency only" : "with persona priors"} · final share ${pct(x.final_share)} · rank #${x.rank ?? "?"} of ${x.n_products ?? "?"}`;
  $("pl-multi").innerHTML = R.ranking.map((i) => {
    const t = R.slots[i];
    return `<button type="button" class="pl-thumb" data-slot="${i}" aria-pressed="${i === sel.slot}">
      <span class="pl-heat"><img src="${esc(runFile(t.scene))}" alt="" loading="lazy"><img class="pl-over" src="${esc(heatFor(t, sel.p))}" alt="" loading="lazy"></span>
      <span>${esc(t.label)} · ${pct(pp(t, sel.p)?.final_share)}</span></button>`;
  }).join("");
}
$("pl-v-slot").onchange = (e) => { S.sel.slot = Number(e.target.value); updateViewer(); };
$("pl-v-personas").onclick = (e) => { const p = e.target.closest("[data-p]"); if (p) { S.sel.p = Number(p.dataset.p); updateViewer(); } };
$("pl-v-sal").onchange = (e) => { S.sel.sal = e.target.checked; updateViewer(); };
$("pl-v-op").oninput = (e) => dialog.style.setProperty("--pl-op", e.target.value / 100);
$("pl-multi").onclick = (e) => {
  const t = e.target.closest("[data-slot]");
  if (!t) return;
  S.sel.slot = Number(t.dataset.slot);
  updateViewer();
  $("pl-multi").querySelector(`[data-slot="${t.dataset.slot}"]`)?.focus();
};
$("pl-v-3d").onclick = () => {
  const s = S.R.slots[S.sel.slot];
  if (!window.shelfproof?.showTexture) return status("The 3D viewer is not available in this browser.", { error: true });
  S.keepHash = true;
  dialog.close();
  window.shelfproof.showTexture(runFile(s.scene), `Placement: ${s.label}`);
};

async function open([pid, rid] = []) {
  if (!job() || !/^[0-9a-f]{12}$/.test(job())) return;
  if (!dialog.open) dialog.showModal();
  if (S.job !== job()) {
    Object.assign(S, { job: job(), layout: null, meta: null, pid: null, rid: null, costs: {}, R: null, cand: null });
    showView(false);
  }
  renderHistory();
  const token = ++S.token;
  status("Loading…", { busy: true });
  const src = `${base()}/source.png`;
  if (photo.getAttribute("src") !== src) photo.src = src;
  try {
    const [products, meta] = await Promise.all([api("/products"), S.meta || api("/placement/personas"), photo.decode()]);
    if (token !== S.token) return;
    if (!S.layout) sizeStage([photo.naturalWidth, photo.naturalHeight]);
    if (meta !== S.meta) initMeta(meta);
    S.products = (Array.isArray(products) ? products : []).filter((p) => PID.test(p.pid));
    let stored;
    try { stored = localStorage.getItem(storeKey()); } catch { /* storage unavailable */ }
    const choice = [pid, S.pid, stored].find((x) => x && S.products.some((p) => p.pid === x));
    renderProducts();
    if (choice && choice === S.pid && S.cand && !(pid && rid !== S.rid)) {
      writeHash();
      status("Pick slots and personas, then run the test.");
      return S.rid ? await watchRun(S.rid, token) : undefined;
    }
    if (choice) return selectProduct(choice, choice === pid ? rid : undefined);
    $("pl-setup").hidden = $("pl-results").hidden = true;
    status(S.products.length ? "Pick the product to test." : "No products yet. Select your product in the Packaging lab first.");
  } catch (e) { if (token === S.token) fail(e); }
}

$("pl-close").onclick = () => dialog.close();
dialog.addEventListener("close", () => {
  S.token++;
  setRunning(false);
  if (!S.keepHash) history.replaceState(null, "", `${location.pathname}${location.search}`);
  S.keepHash = false;
  document.getElementById("placement-test")?.focus();
});

const button = document.getElementById("placement-test");
const modes = document.getElementById("modes");
if (button) {
  button.onclick = () => open(parseHash(location.hash) || []);
  const sync = () => { button.hidden = !job() || !!modes?.hidden; };
  if (modes) new MutationObserver(sync).observe(modes, { attributes: true, attributeFilter: ["hidden"] });
  sync();
}
const restore = parseHash(initialHash);
if (restore) open(restore);

const pack = document.createElement("section");
pack.id = "pl-pack";
pack.hidden = true;
pack.setAttribute("aria-labelledby", "pl-pack-h");
pack.innerHTML = `<details><summary id="pl-pack-h">Pack design attention</summary>
<p class="pl-hint">Scores the original pack and each Packaging-lab concept with DeepGaze IIE in the same photo, viewpoint and shelf position, so differences come from the design. ${DISCLAIMER}</p>
<div class="pl-row"><label>Concept set<select id="pl-pack-set"></select></label><button type="button" id="pl-pack-run">Score pack attention</button></div>
<div id="pl-pack-out"></div></details>`;
$("pl-results").after(pack);

async function loadPackSets(pid) {
  const sets = (await api(`/placement/packaging/${pid}`)).filter((v) => v.files?.length);
  if (S.pid !== pid) return;
  pack.hidden = false;
  $("pl-pack-set").innerHTML = sets.map((v) => `<option value="${esc(v.vid)}">${esc(v.brief?.price_tier || "")} ${esc(v.brief?.brand_tone || "")} · ${v.files.length} concepts · ${esc(v.vid)}</option>`).join("");
  $("pl-pack-run").disabled = !sets.length;
  $("pl-pack-out").innerHTML = sets.length ? "" : `<p class="pl-hint">No concepts yet for this product. Generate some in the Packaging lab first.</p>`;
  if (sets.length) await showPack(pid, sets[0].vid, false);
}

async function showPack(pid, vid, start) {
  const url = `/placement/packaging/${pid}/${vid}`;
  let a = await api(url, start ? { method: "POST" } : undefined);
  while (a.state === "running") {
    $("pl-pack-out").innerHTML = `<p class="pl-hint" role="status">Scoring attention… ${a.done_count || 0}/${a.total || "?"} (first run warms up the GPU, up to ~1 min)</p>`;
    await sleep(2000);
    if (S.pid !== pid || $("pl-pack-set").value !== vid) return;
    a = await api(url);
  }
  if (S.pid !== pid || $("pl-pack-set").value !== vid) return;
  if (a.state === "failed") throw new Error(a.error || "Attention scoring failed.");
  if (a.state !== "done") { $("pl-pack-out").innerHTML = '<p class="pl-hint">No attention scores yet. Choose “Score pack attention” to evaluate this concept set.</p>'; return; }
  const R = a.results;
  $("pl-pack-out").innerHTML = `<article class="pl-rec"><strong>Most attention: ${esc(R.rows.find((r) => r.key === R.best)?.label)}</strong><ul>${R.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></article>
  <div class="pl-scroll"><table><thead><tr><th>Pack</th><th>Attention share</th><th>Δ vs original</th><th>× original</th><th>Rank among products</th></tr></thead><tbody>
  ${R.rows.map((r) => `<tr${r.key === R.best ? ' class="pl-best"' : ""}><td>${esc(r.label)}</td><td>${pct(r.saliency_share)}</td><td>${r.key === "original" ? "–" : `${r.delta_pp >= 0 ? "+" : ""}${num(r.delta_pp, 1)} pp`}</td><td>${r.ratio == null ? "–" : `${num(r.ratio, 2)}×`}</td><td>#${r.rank} of ${r.n_products}</td></tr>`).join("")}
  </tbody></table></div>
  <div class="pl-multi">${R.rows.map((r) => `<figure class="pl-heat" style="--pl-op:0.8;margin:0"><img src="${esc(`${base()}/${r.image}`)}" alt="${esc(r.label)} on the shelf"><img class="pl-over" src="${esc(`${base()}${url}/${file(r.heatmap)}`)}" alt=""><figcaption class="pl-hint">${esc(r.label)} · ${pct(r.saliency_share)}</figcaption></figure>`).join("")}</div>`;
}

$("pl-pack-run").onclick = () => showPack(S.pid, $("pl-pack-set").value, true).catch(fail);
$("pl-pack-set").onchange = () => showPack(S.pid, $("pl-pack-set").value, false).catch(fail);
