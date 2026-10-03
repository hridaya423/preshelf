import subprocess
from pathlib import Path


def test_viewer_reuses_assets_and_releases_them_for_a_new_job():
    html = (Path(__file__).parents[1] / "shelfproof/static/index.html").read_text()
    script = r'''
import assert from "node:assert/strict";
import vm from "node:vm";
let html = "";
for await (const chunk of process.stdin) html += chunk;
const functions = html.slice(html.indexOf("  function meshMaterials()"), html.indexOf("  window.shelfproof"))
  + html.slice(html.indexOf("  function clearView("), html.indexOf("  function validateMetadata("));
let loads = 0, disposals = 0, textureDisposals = 0, photoLoads = 0, resolveMesh;
const texture = {isTexture: true, dispose() { textureDisposals++; }};
const mesh = {traverse(fn) { fn(this.child); }, child: {isMesh: true, material: {map: texture, dispose() {}}}};
const elements = new Map();
const $ = id => {
  if (!elements.has(id)) elements.set(id, {
    hidden: true, textContent: "", classList: {add() {}, remove() {}},
    getAttribute(name) { return this[name]; },
    removeAttribute(name) { if (name === "src") delete this.url; else delete this[name]; },
    set src(value) { this.url = value; photoLoads++; },
    get src() { return this.url; },
    async decode() {},
  });
  return elements.get(id);
};
const context = vm.createContext({
  $, console, modeButtons: [], renderer: {setAnimationLoop() {}}, controls: {},
  scene: {add() {}, remove() {}}, resize() {}, render() {}, resetView() {},
  disposeMesh() { disposals++; },
  MutationObserver: class { observe() {} },
  THREE: {MeshBasicMaterial: class { constructor(options) { Object.assign(this, options); } dispose() {} }},
  GLTFLoader: class { loadAsync() { loads++; return new Promise(resolve => { resolveMesh = resolve; }); } },
});
vm.runInContext(`let mode, object, cachedMesh, originalMap, sparkRenderer, swapToken = 0;
let currentJob = '38c17fd769fe', metadata = {};
${functions}`, context);
const run = code => vm.runInContext(code, context);
const firstLoad = run('show("mesh")');
await Promise.resolve();
assert.equal($("photo").hidden, false, "photo is visible while the model is loading");
resolveMesh({scene: mesh});
await firstLoad;
assert.equal($("photo").hidden, true);
assert.equal(loads, 1);
await run('show("photo")');
assert.equal(disposals, 0, "photo mode must retain the GPU mesh");
await run('show("mesh")');
await run('show("photo")');
await run('show("mesh")');
assert.equal(loads, 1, "switching modes must not download/parse the mesh again");
assert.equal(photoLoads, 1, "switching modes must not reset the photo source");
run('setMap({isTexture: true, dispose() { console.log("swap disposed"); }}); clearView()');
assert.equal(mesh.child.material.map, texture, "leaving a swapped view restores the original texture");
assert.equal(textureDisposals, 0);
run('clearView(true)');
assert.equal(disposals, 1, "changing jobs must release the retained mesh");
assert.equal(run('cachedMesh'), undefined);
assert.equal($("photo").src, undefined);
console.log(`mesh loads: ${loads}; photo loads: ${photoLoads}; released meshes: ${disposals}`);
'''
    result = subprocess.run(
        ["node", "--input-type=module", "-e", script], input=html, text=True, capture_output=True
    )
    assert result.returncode == 0, result.stdout + result.stderr
