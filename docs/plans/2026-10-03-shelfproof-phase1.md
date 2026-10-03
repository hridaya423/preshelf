# ShelfProof Phase 1 Implementation Plan: shelf video to navigable 3D

> **Pivoted 2026-10-03: input is a single photo; Nerfstudio/video path removed.**

**New architecture:** the Modal GPU worker runs Depth-Anything-V2-Small on one uploaded photo and `shelfproof/splat.py` unprojects the pixels into a one-Gaussian-per-pixel PLY; the web endpoint and Spark viewer are unchanged.

> **For the executor:** use the `executing-plans` skill and work through the tasks in order. Tasks 1 and 2 are gates: if one fails, stop and fix it before building anything on top.

**Goal:** Upload a phone video of one shelf bay, reconstruct it on a cloud GPU, and orbit the resulting Gaussian splat in the browser, with reset and download.

**Architecture:** One Modal app (`shelfproof/app.py`) with two functions. The first is a GPU worker that runs Nerfstudio: `ns-process-data video` (FFmpeg frames + COLMAP poses), then `ns-train splatfacto`, then `ns-export gaussian-splat`. The second is a small FastAPI web endpoint that accepts the upload, starts the worker, reports job status, and serves the PLY and a single HTML page. That page renders the PLY with Spark and Three.js. A Modal Volume stores each job's input, frames, camera poses, and result, so phases 2–4 can reuse them.

**Tech stack:** Python 3.11, uv, Modal, the Nerfstudio Docker image (COLMAP + Splatfacto), FastAPI, Spark 2.3.1 with Three.js 0.180 (loaded from a CDN, no build step), and pytest.

**Background:** `docs/plans/2026-10-03-shelfproof-research.md` explains why this route was chosen and covers the behavioral and market research behind phases 2–4.

---

## Out of scope for phase 1

- Single-photo input. One photo can't show the hidden faces of products, so reconstructing from it would mean inventing geometry.
- Real-world scale and measurements. Scene units stay arbitrary until a known measurement is added; that work belongs to phase 2's "does it fit" check.
- Packaging edits, market data, and shopper simulation (phases 2–4).
- Auth, multiple users, and a job list. A job is identified by its ID in the URL.

## Phase 1 is done when

1. A clip uploaded in the browser produces its own splat, which you can orbit, reset, and download as a PLY.
2. Two different inputs each reconstruct end to end: the SLAM&Render clip and one real shelf sweep. Inspect each from several nearby viewpoints; labels should be readable at roughly the distance they were filmed from.
3. An unusable clip (for example, a static shot or a 2-second clip) shows a readable failure message, not an endless spinner.
4. Opening `/?job=<id>` for a finished job reloads its result. That gives the presentation a reliable fallback, and the fallback is still a real run from this pipeline.
5. `uv run pytest` passes.

---

### Task 0: Project setup

**Files:** Create `pyproject.toml` (via uv), `shelfproof/__init__.py`, `.gitignore`

**Step 1:** Initialise the project.

```bash
cd /Users/hridyaagrawal/Honey/eathack
git init
uv init --no-workspace --python 3.11 --name shelfproof
rm -f main.py hello.py
uv add modal
uv add --dev pytest
mkdir -p shelfproof/static tests scripts out
touch shelfproof/__init__.py
printf "out/\ndata/\n.venv/\n__pycache__/\n*.mp4\n*.ply\n" > .gitignore
```

**Step 2:** Authenticate with Modal (opens a browser).

```bash
uv run modal token new
uv run modal profile current
```

Expected: your Modal workspace name is printed.

**Step 3:** Commit: `git add -A && git commit -m "Scaffold ShelfProof phase 1"`

---

### Task 1 (gate): Test footage

**Files:** Create `scripts/make_test_clip.sh`

Clip requirements for any input: one uninterrupted take, the camera moving *sideways* along the shelf (not just turning on the spot), plenty of overlap between frames, slow movement, few people walking through, and readable packaging. Aim for 30–60 s at 1080p.

**Step 1:** Write the script that downloads the SLAM&Render setup-3 capture (CC BY 4.0) and encodes its RGB frames as a video. The pipeline must recover camera poses itself, so the dataset's ground-truth poses are deliberately ignored.

```bash
#!/usr/bin/env bash
set -euo pipefail
mkdir -p data out
cd data
[ -f 3-natural-tr.zip ] || curl -L -o 3-natural-tr.zip "https://zenodo.org/api/records/15000694/files/3-natural-tr.zip/content"
[ -d 3-natural-tr ] || unzip -q 3-natural-tr.zip -d 3-natural-tr
RGB_DIR="${1:?usage: make_test_clip.sh <path to RGB frame folder inside data/3-natural-tr>}"
ffmpeg -y -framerate 30 -pattern_type glob -i "$RGB_DIR/*.png" -vf "scale=-2:1080" -c:v libx264 -pix_fmt yuv420p ../out/slamrender.mp4
```

**Step 2:** Run the download, then find the RGB folder (it is not documented reliably, so look):

```bash
chmod +x scripts/make_test_clip.sh
bash scripts/make_test_clip.sh || true
find data/3-natural-tr -maxdepth 3 -type d | head -30
```

Pick the folder of colour frames from a single camera. Ignore depth folders. If the frames are `.jpg`, change `*.png` in the script.

**Step 3:** Encode the clip and watch it.

```bash
bash scripts/make_test_clip.sh data/3-natural-tr/<rgb-folder>
open out/slamrender.mp4
```

Expected: a smooth moving shot of supermarket goods. If the shot is mostly rotation or jumps around, take a shorter contiguous section (`ffmpeg -ss 0 -t 40 -i ...`).

**Step 4:** Find a real shelf clip. Film a shelf if you can; if you can't, use a clip you have permission to use that meets the requirements above. Save it as `out/shelf.mp4`. Do not use CCTV, edited store tours, or videos of existing splats.

**Step 5:** Commit: `git add scripts && git commit -m "Add test clip script"`

---

### Task 2: Pure checks (test first)

**Files:** Create `shelfproof/checks.py`, `tests/test_checks.py`

These are the only pieces of logic that can be tested without a GPU. One decides whether camera alignment worked well enough to continue; the other finds the training config Nerfstudio wrote.

**Step 1:** Write the failing tests.

```python
from pathlib import Path

import pytest

from shelfproof.checks import find_config, registration_error


def test_no_frames_is_an_error():
    assert "No frames" in registration_error(0, 0)


def test_low_registration_is_an_error():
    msg = registration_error(300, 120)
    assert "120 of 300" in msg


def test_good_registration_passes():
    assert registration_error(300, 290) is None


def test_find_config_returns_single_match(tmp_path: Path):
    cfg = tmp_path / "data" / "splatfacto" / "2026-10-03_120000" / "config.yml"
    cfg.parent.mkdir(parents=True)
    cfg.write_text("x")
    assert find_config(tmp_path) == cfg


def test_find_config_requires_exactly_one(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        find_config(tmp_path)
```

**Step 2:** `uv run pytest tests/test_checks.py -v`. Expected: FAIL with `ModuleNotFoundError: No module named 'shelfproof.checks'`.

**Step 3:** Implement.

```python
from pathlib import Path

MIN_POSED_RATIO = 0.6


def registration_error(n_images: int, n_posed: int) -> str | None:
    if n_images == 0:
        return "No frames could be extracted from the video."
    if n_posed / n_images < MIN_POSED_RATIO:
        return (
            f"Camera alignment placed only {n_posed} of {n_images} frames. "
            "Re-film moving slowly sideways along the shelf, keeping it in view the whole time."
        )
    return None


def find_config(out_dir: Path) -> Path:
    configs = sorted(out_dir.glob("**/config.yml"))
    if len(configs) != 1:
        raise FileNotFoundError(f"Expected one config.yml under {out_dir}, found {len(configs)}")
    return configs[0]
```

**Step 4:** `uv run pytest -v`. Expected: 5 passed.

**Step 5:** Commit: `git add -A && git commit -m "Add registration and config checks"`

---

### Task 3 (gate): GPU reconstruction from the command line

**Files:** Create `shelfproof/app.py`

Get the worker running before building any UI. This task carries most of the project's technical risk.

**Step 1:** Write the worker and a local entrypoint. (The web endpoint is added to this same file in Task 4.)

```python
import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import modal

from shelfproof.checks import find_config, registration_error

app = modal.App("shelfproof")
jobs = modal.Volume.from_name("shelfproof-jobs", create_if_missing=True)
JOBS = Path("/jobs")
JOB_ID = re.compile(r"^[0-9a-f]{12}$")

recon_image = (
    modal.Image.from_registry("ghcr.io/nerfstudio-project/nerfstudio:latest")
    .entrypoint([])
    .add_local_python_source("shelfproof")
)


@app.function(image=recon_image, gpu="L4", volumes={str(JOBS): jobs}, timeout=60 * 60)
def reconstruct(job_id: str) -> None:
    job = JOBS / job_id
    work = Path("/tmp/work")
    data = work / "data"

    def fail(msg: str):
        (job / "error.txt").write_text(msg)
        jobs.commit()
        raise RuntimeError(msg)

    try:
        subprocess.run(
            ["ns-process-data", "video", "--data", str(job / "input.mp4"), "--output-dir", str(data),
             "--num-frames-target", "300", "--matching-method", "sequential"],
            check=True,
        )
    except subprocess.CalledProcessError:
        fail("Frame extraction or camera alignment failed. Check the file is a video of a shelf filmed while moving.")

    transforms = data / "transforms.json"
    n_images = len(list((data / "images").glob("*")))
    n_posed = len(json.loads(transforms.read_text())["frames"]) if transforms.exists() else 0
    if err := registration_error(n_images, n_posed):
        fail(err)

    subprocess.run(
        ["ns-train", "splatfacto", "--data", str(data), "--output-dir", str(work / "out"),
         "--max-num-iterations", "15000", "--viewer.quit-on-train-completion", "True"],
        check=True,
    )
    subprocess.run(
        ["ns-export", "gaussian-splat", "--load-config", str(find_config(work / "out")),
         "--output-dir", str(work / "export")],
        check=True,
    )
    shutil.copytree(data / "images", job / "frames")
    shutil.copy(transforms, job / "transforms.json")
    shutil.copy(work / "export" / "splat.ply", job / "scene.ply")
    jobs.commit()


@app.local_entrypoint()
def main(video: str):
    job_id = uuid.uuid4().hex[:12]
    with jobs.batch_upload() as batch:
        batch.put_file(video, f"/{job_id}/input.mp4")
    print(f"job {job_id}: reconstructing")
    reconstruct.remote(job_id)
    out = Path("out") / f"{job_id}.ply"
    with out.open("wb") as f:
        for chunk in jobs.read_file(f"{job_id}/scene.ply"):
            f.write(chunk)
    print(f"wrote {out}")
```

**Step 2:** Run it on the SLAM&Render clip.

```bash
uv run modal run shelfproof/app.py --video out/slamrender.mp4
```

Expected: COLMAP, training, and export logs stream in, then `wrote out/<id>.ply`.

**Step 3:** Inspect the result. Drag `out/<id>.ply` onto https://sparkjs.dev/viewer/ (or SuperSplat). The products should be recognisable from several angles near the filmed path.

**If it fails, the likely causes and fixes are:**

| Symptom | Fix |
| --- | --- |
| Image won't start / `python` not found | Keep `.entrypoint([])`. If the image's Python isn't on PATH, add `add_python="3.11"` to `from_registry` |
| COLMAP crashes on SIFT with an OpenGL/display error | Add `"--no-gpu"` to the `ns-process-data` arguments (COLMAP runs on the CPU; slower but works headless) |
| gsplat CUDA error / "no kernel image" on L4 | Try `gpu="A10G"`. If that still fails, pin a Nerfstudio image tag built for your CUDA arch |
| Registration error message | The clip itself is the problem. Use a shorter, steadier section |
| CUDA out of memory | Lower `--num-frames-target` to 200 |

Once it works, replace `:latest` with the exact image digest that worked (`docker manifest inspect` or check the Modal build log) so the image stays reproducible.

**Step 4:** Run it on `out/shelf.mp4` as well. Write the runtime and GPU type of both runs into `AGENTS.md` so later phases know the baseline.

**Step 5:** Commit: `git add -A && git commit -m "Run Nerfstudio reconstruction on Modal"`

---

### Task 4: Web endpoint

**Files:** Modify `shelfproof/app.py` (append)

**Step 1:** Append the web image and the ASGI app. Job state comes from the Modal function call itself, so a crash, timeout, or OOM is reported as a failure instead of staying "running" forever.

```python
web_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi[standard]")
    .add_local_python_source("shelfproof")
    .add_local_dir(Path(__file__).parent / "static", "/static")
)


@app.function(image=web_image, volumes={str(JOBS): jobs})
@modal.asgi_app()
def web():
    from fastapi import FastAPI, HTTPException, UploadFile
    from fastapi.responses import FileResponse

    api = FastAPI()

    def job_dir(job_id: str) -> Path:
        if not JOB_ID.match(job_id) or not (JOBS / job_id).is_dir():
            raise HTTPException(404, "Unknown job")
        return JOBS / job_id

    @api.get("/")
    def index():
        return FileResponse("/static/index.html")

    @api.post("/api/jobs")
    def create(video: UploadFile):
        job_id = uuid.uuid4().hex[:12]
        job = JOBS / job_id
        job.mkdir(parents=True)
        with (job / "input.mp4").open("wb") as f:
            shutil.copyfileobj(video.file, f)
        jobs.commit()
        (job / "call_id").write_text(reconstruct.spawn(job_id).object_id)
        jobs.commit()
        return {"job_id": job_id}

    @api.get("/api/jobs/{job_id}")
    def status(job_id: str):
        jobs.reload()
        job = job_dir(job_id)
        if (job / "scene.ply").exists():
            return {"state": "done"}
        try:
            modal.FunctionCall.from_id((job / "call_id").read_text()).get(timeout=0)
        except TimeoutError:
            return {"state": "running"}
        except Exception as e:
            err = job / "error.txt"
            return {"state": "failed", "error": err.read_text() if err.exists() else f"Reconstruction crashed: {e}"}
        return {"state": "failed", "error": "Finished without producing a scene."}

    @api.get("/api/jobs/{job_id}/scene.ply")
    def scene(job_id: str):
        ply = job_dir(job_id) / "scene.ply"
        if not ply.exists():
            raise HTTPException(404, "Scene not ready")
        return FileResponse(ply, filename=f"shelf-{job_id}.ply")

    return api
```

**Step 2:** Create a placeholder `shelfproof/static/index.html` containing `<h1>ShelfProof</h1>`, then run `uv run modal serve shelfproof/app.py`. Expected: a `https://...modal.run` URL is printed, and opening it shows the heading.

**Step 3:** Smoke test the API with curl in a second terminal:

```bash
URL=https://<printed-url>
curl -s -F video=@out/slamrender.mp4 $URL/api/jobs           # {"job_id":"..."}
curl -s $URL/api/jobs/<job_id>                                # {"state":"running"}, later {"state":"done"}
curl -s $URL/api/jobs/../etc                                  # 404
```

**Step 4:** Commit: `git add -A && git commit -m "Add upload and job status endpoints"`

---

### Task 5: Upload page and viewer

**Files:** Replace `shelfproof/static/index.html`

Nerfstudio rescales camera poses into roughly a unit cube around the origin by default, so a camera at `z = 2.5` facing the origin frames the scene without computing bounds. The scene can still come out upside down because COLMAP's orientation isn't guaranteed, which is why there is a Flip button.

**Step 1:** Write the page.

```html
<!doctype html>
<html lang="en">
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>ShelfProof</title>
<style>
  body { margin: 0; font: 14px system-ui, sans-serif; background: #111; color: #eee; }
  header { position: fixed; inset: 0 0 auto 0; display: flex; gap: 12px; align-items: center; padding: 12px; background: #111d; }
  canvas { display: block; }
  a { color: #8cf; }
</style>
<header>
  <form id="upload"><input type="file" name="video" accept="video/*" required> <button>Reconstruct</button></form>
  <span id="status" role="status"></span>
  <button id="reset" hidden>Reset view</button>
  <button id="flip" hidden>Flip</button>
  <a id="download" hidden download>Download PLY</a>
</header>
<script type="importmap">
  {
    "imports": {
      "three": "https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js",
      "three/addons/": "https://cdn.jsdelivr.net/npm/three@0.180.0/examples/jsm/",
      "@sparkjsdev/spark": "https://sparkjs.dev/releases/spark/2.3.1/spark.module.js"
    }
  }
</script>
<script type="module">
  import * as THREE from "three";
  import { OrbitControls } from "three/addons/controls/OrbitControls.js";
  import { SparkRenderer, SplatMesh } from "@sparkjsdev/spark";

  const $ = (id) => document.getElementById(id);
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(60, innerWidth / innerHeight, 0.01, 100);
  const renderer = new THREE.WebGLRenderer();
  renderer.setSize(innerWidth, innerHeight);
  document.body.appendChild(renderer.domElement);
  scene.add(new SparkRenderer({ renderer }));
  const controls = new OrbitControls(camera, renderer.domElement);
  const resetView = () => { camera.position.set(0, 0, 2.5); controls.target.set(0, 0, 0); controls.update(); };
  resetView();
  addEventListener("resize", () => {
    camera.aspect = innerWidth / innerHeight;
    camera.updateProjectionMatrix();
    renderer.setSize(innerWidth, innerHeight);
  });
  renderer.setAnimationLoop(() => { controls.update(); renderer.render(scene, camera); });

  let splat;
  function show(jobId) {
    const url = `/api/jobs/${jobId}/scene.ply`;
    if (splat) scene.remove(splat);
    splat = new SplatMesh({ url });
    scene.add(splat);
    $("download").href = url;
    for (const id of ["reset", "flip", "download"]) $(id).hidden = false;
    resetView();
  }

  async function poll(jobId) {
    history.replaceState(null, "", `?job=${jobId}`);
    for (;;) {
      const res = await fetch(`/api/jobs/${jobId}`);
      if (!res.ok) { $("status").textContent = `Unknown job ${jobId}`; return; }
      const job = await res.json();
      if (job.state === "done") { $("status").textContent = `Job ${jobId}`; return show(jobId); }
      if (job.state === "failed") { $("status").textContent = job.error; return; }
      $("status").textContent = `Reconstructing job ${jobId}. This takes several minutes.`;
      await new Promise((r) => setTimeout(r, 5000));
    }
  }

  $("upload").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("status").textContent = "Uploading…";
    const res = await fetch("/api/jobs", { method: "POST", body: new FormData(e.target) });
    if (!res.ok) { $("status").textContent = `Upload failed (${res.status})`; return; }
    poll((await res.json()).job_id);
  });
  $("reset").onclick = resetView;
  $("flip").onclick = () => splat?.rotateX(Math.PI);

  const initial = new URLSearchParams(location.search).get("job");
  if (initial) poll(initial);
</script>
</html>
```

**Step 2:** With `modal serve` still running (it hot-reloads), open the URL, upload `out/slamrender.mp4`, and wait. Expected: the status text updates, then the splat appears; you can orbit and zoom, Reset view and Flip work, and Download saves a PLY.

**Step 3:** Open `/?job=<id from Task 3 or 4>` in a fresh tab. Expected: the finished scene loads straight away.

**Step 4:** Commit: `git add -A && git commit -m "Add upload page and splat viewer"`

---

### Task 6: Acceptance run and deploy

**Step 1:** Deploy with `uv run modal deploy shelfproof/app.py` and note the stable URL.

**Step 2:** Go through the "done when" list at the top against the deployed URL:

- Upload `out/shelf.mp4` and inspect the result from several viewpoints.
- Make a bad clip: `ffmpeg -i out/shelf.mp4 -t 2 -vf "select=eq(n\,0)" -vsync vfr -frames:v 1 out/still.png && ffmpeg -loop 1 -i out/still.png -t 5 -pix_fmt yuv420p out/static.mp4`. Upload it. Expected: a readable failure message within minutes, not a spinner that never ends.
- Run `uv run pytest`.

**Step 3:** Record the demo job IDs (the good SLAM&Render run, the good shelf run) in `AGENTS.md` with the deployed URL, and add the commands: `uv run pytest`, `uv run modal serve shelfproof/app.py`, `uv run modal run shelfproof/app.py --video <clip>`.

**Step 4:** Commit: `git add -A && git commit -m "Phase 1 acceptance"`

---

## What phase 1 leaves behind for later phases

Each job folder on the `shelfproof-jobs` volume contains `input.mp4`, `frames/`, `transforms.json` (camera poses), and `scene.ply`.

- **Phase 2 (packaging):** render the same camera pose from `transforms.json` twice, once with each package variant on a box or cylinder placed over one chosen slot, and compare the renders side by side (then with a pretrained saliency overlay such as UNISAL). Don't try to erase the original product from the splat yet.
- **Phase 3 (market map):** one category, a sourced table (Open Food Facts + Open Prices + organizer data), and a price-per-unit vs attribute plot. Every fact has a source and date.
- **Phase 4 (shoppers):** shopping missions (named brand, cheapest option, browsing) as explicit scenario weights, a heatmap from the saliency model plus simple dwell/transition statistics from Standard's Day-in-the-Life data, and baseline vs changed placement on the same seeds. Demographic segments are labelled as user-set assumptions until there's data that links demographics to choices.

None of phases 1–3 need model fine-tuning. Phase 4 starts with counting and a conditional-logit baseline, not a trained neural shopper.
