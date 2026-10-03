import json
import re
import time
import uuid
from pathlib import Path

import modal

app = modal.App("shelfproof")
jobs = modal.Volume.from_name("shelfproof-jobs", create_if_missing=True)
JOBS = Path("/jobs")
JOB_ID = re.compile(r"^[0-9a-f]{12}$")
MAX_UPLOAD = 20 * 1024 * 1024
DEFAULT_JOB = "38c17fd769fe"
DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"
DEPTH_REVISION = "5426e4f0f36572d16453bbda7a8389317b1bef99"
MESH_MODEL = "Ruicheng/moge-2-vitl-normal"
MESH_REVISION = "b135031bae30b5ac2ae141a0e68717795ce38340"
MOGE_COMMIT = "07444410f1e33f402353b99d6ccd26bd31e469e8"
UTILS3D_COMMIT = "3fab839f0be9931dac7c8488eb0e1600c236e183"


def _download_models():
    from moge.model.v2 import MoGeModel
    from transformers import pipeline

    pipeline("depth-estimation", model=DEPTH_MODEL, revision=DEPTH_REVISION)
    MoGeModel.from_pretrained(MESH_MODEL, revision=MESH_REVISION)


recon_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "torch==2.7.1", "torchvision==0.22.1", "transformers==4.51.3",
        "pillow==11.2.1", "numpy==2.2.5", "scipy==1.15.3",
        "opencv-python-headless==4.11.0.86", "huggingface-hub==0.31.4",
        "trimesh==4.6.10", "setuptools==80.9.0", "wheel==0.45.1",
    )
    .run_commands(
        "python -m pip install --no-deps --no-build-isolation "
        f"git+https://github.com/EasternJournalist/utils3d.git@{UTILS3D_COMMIT} "
        f"git+https://github.com/microsoft/MoGe.git@{MOGE_COMMIT}"
    )
    .run_function(_download_models)
    .add_local_python_source("shelfproof")
)


@app.function(image=recon_image, gpu="L4", volumes={str(JOBS): jobs}, timeout=600, max_containers=1)
def image_to_3d(job_id: str) -> None:
    import numpy as np
    import torch
    import torch.nn.functional as F
    import trimesh
    from moge.model.v2 import MoGeModel
    from PIL import Image, ImageOps
    from transformers import pipeline

    from shelfproof.mesh import build_mesh
    from shelfproof.splat import image_to_splat_ply

    if not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid job ID")
    jobs.reload()
    job = JOBS / job_id
    started = time.perf_counter()

    try:
        (job / "pipeline").write_text("textured-mesh")
        source = next(p for p in job.iterdir() if p.name.startswith("input."))
        if not 0 < source.stat().st_size <= MAX_UPLOAD:
            raise ValueError("Upload a nonempty image no larger than 20 MB")
        with Image.open(source) as uploaded:
            if min(uploaded.size) < 2 or uploaded.width * uploaded.height > 20_000_000:
                raise ValueError("Use an image at least 2 pixels across and no larger than 20 megapixels.")
            original = ImageOps.exif_transpose(uploaded).convert("RGB")
        original.save(job / "source.png")
        img = original.copy()
        img.thumbnail((1024, 1024))
        w, h = img.size
        print(f"job {job_id}: source {original.size}, geometry {img.size}, GPU {torch.cuda.get_device_name()}")
        pipe = pipeline("depth-estimation", model=DEPTH_MODEL, revision=DEPTH_REVISION, device=0)
        depth = pipe(img)["predicted_depth"]
        depth = F.interpolate(
            depth[None, None].float(), size=(h, w), mode="bilinear", align_corners=False
        )[0, 0].cpu().numpy()
        ply = image_to_splat_ply(np.asarray(img), depth)
        disp8 = ((depth - depth.min()) / (depth.max() - depth.min() + 1e-8) * 255).astype(np.uint8)
        Image.fromarray(disp8).save(job / "depth.png")
        (job / "scene.ply").write_bytes(ply)
        jobs.commit()
        del pipe
        torch.cuda.empty_cache()

        model = MoGeModel.from_pretrained(MESH_MODEL, revision=MESH_REVISION).to("cuda").eval()
        model.enable_pytorch_native_sdpa()
        rgb = torch.from_numpy(np.asarray(img).copy()).to(device="cuda", dtype=torch.float32).permute(2, 0, 1) / 255
        torch.cuda.synchronize()
        inference_started = time.perf_counter()
        output = model.infer(rgb, resolution_level=9, use_fp16=True)
        torch.cuda.synchronize()
        inference_seconds = time.perf_counter() - inference_started
        mesh = build_mesh(
            output["points"].float().cpu().numpy(),
            output["mask"].bool().cpu().numpy(),
            output["intrinsics"].float().cpu().numpy(),
            source_size=original.size,
        )
        glb = trimesh.Trimesh(
            vertices=mesh["vertices"], faces=mesh["faces"],
            visual=trimesh.visual.texture.TextureVisuals(uv=mesh["uvs"], image=original),
            process=False,
        ).export(file_type="glb")
        metadata = {
            **mesh["metadata"], "representation": "textured-mesh", "model": MESH_MODEL,
            "model_revision": MESH_REVISION, "code_revision": MOGE_COMMIT,
            "resolution_level": 9, "inference_seconds": round(inference_seconds, 3),
            "runtime_seconds": round(time.perf_counter() - started, 3),
        }
        (job / "scene.json").write_text(json.dumps(metadata, allow_nan=False))
        jobs.commit()
        (job / "mesh.tmp").write_bytes(glb)
        (job / "mesh.tmp").replace(job / "mesh.glb")
        jobs.commit()
        print(f"job {job_id}: done {json.dumps(metadata)}, GLB {len(glb)} bytes")
    except Exception as exc:
        (job / "error.txt").write_text(f"Could not build 3D from this image: {exc}")
        jobs.commit()
        raise


SAM_MODEL = "facebook/sam2.1-hiera-large"
SAM_REVISION = "665f8e2ad61cf5f53d65644ff27c8ee525124610"
RUNWARE_MODEL = "runware:108@22"


def _download_sam():
    from transformers import Sam2Model, Sam2Processor

    Sam2Model.from_pretrained(SAM_MODEL, revision=SAM_REVISION)
    Sam2Processor.from_pretrained(SAM_MODEL, revision=SAM_REVISION)


sam_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install(
        "torch==2.7.1", "torchvision==0.22.1", "transformers==4.57.6", "huggingface-hub==0.36.2",
        "pillow==11.2.1", "numpy==2.2.5", "scipy==1.15.3",
    )
    .run_function(_download_sam)
    .add_local_python_source("shelfproof")
)


@app.function(image=sam_image, gpu="T4", volumes={str(JOBS): jobs}, timeout=300, max_containers=1, scaledown_window=300)
def segment_product(job_id: str, prompt: dict) -> dict:
    import numpy as np
    import torch
    from PIL import Image
    from scipy import ndimage
    from transformers import Sam2Model, Sam2Processor

    from shelfproof.packaging import load_source, mask_bbox, pad_bbox

    if not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid job ID")
    jobs.reload()
    job = JOBS / job_id
    img = load_source(job)
    w, h = img.size
    processor = Sam2Processor.from_pretrained(SAM_MODEL, revision=SAM_REVISION)
    model = Sam2Model.from_pretrained(SAM_MODEL, revision=SAM_REVISION).to("cuda").eval()
    if "point" in prompt:
        x, y = float(prompt["point"]["x"]), float(prompt["point"]["y"])
        if not (0 <= x < w and 0 <= y < h):
            raise ValueError("Point outside the source image")
        inputs = processor(images=img, input_points=[[[[x, y]]]], input_labels=[[[1]]], return_tensors="pt")
    else:
        b = prompt["box"]
        if not (0 <= b["x0"] < b["x1"] <= w and 0 <= b["y0"] < b["y1"] <= h):
            raise ValueError("Box outside the source image")
        inputs = processor(images=img, input_boxes=[[[b["x0"], b["y0"], b["x1"], b["y1"]]]], return_tensors="pt")
    with torch.no_grad():
        outputs = model(**inputs.to("cuda"), multimask_output=True)
    masks = processor.post_process_masks(outputs.pred_masks.cpu(), inputs["original_sizes"].cpu())[0][0].numpy()
    scores = outputs.iou_scores[0, 0].float().cpu().numpy()
    best = int(scores.argmax())
    labels, count = ndimage.label(masks[best] > 0)
    if not count:
        raise ValueError("No object found at that location; try another point or a box")
    keep = labels[min(int(y), h - 1), min(int(x), w - 1)] if "point" in prompt else 0
    if not keep:
        keep = int(np.bincount(labels.ravel())[1:].argmax()) + 1
    mask = ndimage.binary_fill_holes(labels == keep)
    bbox = mask_bbox(mask)
    crop_box = pad_bbox(bbox, 0.08, w, h)
    pid = uuid.uuid4().hex[:8]
    out = job / "products" / pid
    out.mkdir(parents=True)
    mask_img = Image.fromarray(mask.astype(np.uint8) * 255)
    mask_img.save(out / "mask.png")
    cutout = img.crop(bbox).convert("RGBA")
    cutout.putalpha(mask_img.crop(bbox))
    cutout.save(out / "cutout.png")
    img.crop(crop_box).save(out / "crop.png")
    product = {
        "pid": pid, "prompt": prompt, "bbox": list(bbox), "crop_box": list(crop_box), "source_size": [w, h],
        "area_px": int(mask.sum()), "score": round(float(scores[best]), 4), "created": time.time(),
        "model": SAM_MODEL, "model_revision": SAM_REVISION,
    }
    (out / "product.json").write_text(json.dumps(product))
    jobs.commit()
    print(f"job {job_id}: product {pid} bbox {bbox} score {product['score']}")
    return product


variant_image = modal.Image.debian_slim(python_version="3.11").pip_install(
    "httpx==0.28.1", "pillow==11.2.1", "numpy==2.2.5",
).add_local_python_source("shelfproof")


@app.function(
    image=variant_image, volumes={str(JOBS): jobs}, timeout=900, max_containers=2,
    secrets=[modal.Secret.from_dotenv(Path(__file__).parent.parent)],
)
def generate_variants(job_id: str, pid: str, vid: str) -> None:
    import base64
    import io
    import os
    import threading
    from concurrent.futures import ThreadPoolExecutor

    import httpx
    from PIL import Image

    from shelfproof.packaging import (
        DEFAULT_MODEL, MODELS, PLACEMENT_PROMPT, banana_size, composite_into_shelf, edit_inputs, facing_aspect,
        load_source, pad_bbox, paste_masked, sunburst_size, upscale,
    )

    if not (JOB_ID.fullmatch(job_id) and re.fullmatch(r"[0-9a-f]{8}", pid) and re.fullmatch(r"[0-9a-f]{8}", vid)):
        raise ValueError("Invalid ID")
    jobs.reload()
    product_dir = JOBS / job_id / "products" / pid
    out = product_dir / "variants" / vid
    meta = json.loads((out / "prompt.json").read_text())
    brief = meta["brief"]
    model_key = brief.get("model") or DEFAULT_MODEL
    sunburst = MODELS["gpt-image-2.5-sunburst"]
    quality = brief.get("quality") or "high"
    status = {"state": "running", "done_count": 0, "total": len(meta["prompts"]), "error": None,
              "model": model_key, "placements": {}, "cost": 0.0}
    lock = threading.Lock()

    def save_status():
        (out / "status.json").write_text(json.dumps(status))
        jobs.commit()

    def data_uri(img):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return "data:image/png;base64," + base64.b64encode(buf.getvalue()).decode()

    def on_grey(img):
        img = img.convert("RGBA")
        bg = Image.new("RGB", img.size, (235, 235, 235))
        bg.paste(img, mask=img.getchannel("A"))
        return bg

    try:
        key = os.environ.get("RUNWARE_API_KEY", "").strip()
        if not key:
            raise RuntimeError("RUNWARE_API_KEY is not configured in .env")

        def runware(client, task):
            task_uuid = str(uuid.uuid4())
            task = {"taskType": "imageInference", "taskUUID": task_uuid, "outputType": "base64Data",
                    "outputFormat": "PNG", "numberResults": 1, "includeCost": True, **task}
            r = client.post("https://api.runware.ai/v1", json=[task], headers={"Authorization": f"Bearer {key}"})
            try:
                body = r.json()
            except ValueError:
                raise RuntimeError(f"Runware returned HTTP {r.status_code} with a non-JSON body")
            errors = body.get("errors") or ([body["error"]] if body.get("error") else [])
            if errors or r.status_code >= 400:
                first = errors[0] if errors else {}
                msg = first.get("message", str(first)) if isinstance(first, dict) else str(first)
                raise RuntimeError(f"Runware error (HTTP {r.status_code}): {msg or 'unknown error'}")
            result = next((d for d in body.get("data", []) if d.get("taskUUID") == task_uuid), None)
            if not result or not result.get("imageBase64Data"):
                raise RuntimeError("Runware response contained no image")
            img = Image.open(io.BytesIO(base64.b64decode(result["imageBase64Data"])))
            img.load()
            return img, float(result.get("cost") or 0)

        product = json.loads((product_dir / "product.json").read_text())
        bbox = product["bbox"]
        shelf = load_source(JOBS / job_id)
        mask = Image.open(product_dir / "mask.png").convert("L")
        Image.open(product_dir / "crop.png").convert("RGB").save(out / "original.png")
        front = upscale(on_grey(Image.open(product_dir / "cutout.png")))
        views = [Image.open(p).convert("RGB") for p in (product_dir / "references" / "side.png",
                 product_dir / "references" / "back.png") if p.is_file()]
        for view in views:
            view.thumbnail((1024, 1024))
        context = upscale(shelf.crop(pad_bbox(bbox, 1.0, shelf.width, shelf.height)))
        ref_uris = [data_uri(r) for r in [front, *views, context]]
        aspect = facing_aspect(bbox)
        transparent = model_key == "gpt-image-2.5-sunburst"
        width, height = sunburst_size(aspect, 1536) if transparent else banana_size(aspect)
        edit_box, edit_crop, edit_mask = edit_inputs(shelf, mask, bbox)
        edit_refs = [data_uri(edit_crop)]
        edit_mask_uri = data_uri(edit_mask.convert("RGB"))
        meta.update(negative_prompt=None, width=width, height=height, model=model_key, model_id=MODELS[model_key],
                    placement_model=sunburst, placement_prompt=PLACEMENT_PROMPT, quality=quality,
                    reference_count=len(ref_uris), edit_box=list(edit_box), edit_size=list(edit_crop.size))
        (out / "prompt.json").write_text(json.dumps(meta))
        save_status()

        def packshot_task(prompt):
            task = {"model": MODELS[model_key], "positivePrompt": prompt, "width": width, "height": height,
                    "inputs": {"referenceImages": ref_uris}}
            if transparent:
                task["settings"] = {"quality": quality, "background": "transparent"}
            return task

        def run(client, k, prompt):
            pack, cost = runware(client, packshot_task(prompt))
            pack = pack.convert("RGBA") if transparent else pack.convert("RGB")
            pack.save(out / f"variant_{k}.png")
            with lock:
                status["cost"] = round(status["cost"] + cost, 4)
                save_status()
            ref = on_grey(pack)
            ref.thumbnail((1024, 1024))
            try:
                edited, edit_cost = runware(client, {
                    "model": sunburst, "positivePrompt": PLACEMENT_PROMPT,
                    "width": edit_crop.width, "height": edit_crop.height,
                    "inputs": {"referenceImages": [*edit_refs, data_uri(ref)], "maskImage": edit_mask_uri},
                    "settings": {"quality": quality, "background": "opaque"},
                })
                placed, method = paste_masked(shelf, mask, edit_box, edited), "edit"
            except Exception as exc:
                print(f"job {job_id}: variant set {vid} {k} shelf edit failed, compositing: {exc}")
                placed, method, edit_cost = composite_into_shelf(shelf, mask, bbox, pack), "composite", 0.0
            placed.save(out / f"shelf_{k}.png")
            with lock:
                status["cost"] = round(status["cost"] + edit_cost, 4)
                status["placements"][str(k)] = method
                status["done_count"] += 1
                save_status()
            print(f"job {job_id}: variant set {vid} {k}/{status['total']} placement {method} cost {cost + edit_cost:.4f}")

        errors = []
        with httpx.Client(timeout=httpx.Timeout(240, connect=20)) as client, ThreadPoolExecutor(4) as pool:
            futures = {k: pool.submit(run, client, k, p) for k, p in enumerate(meta["prompts"], start=1)}
            for k, fut in futures.items():
                try:
                    fut.result()
                except Exception as exc:
                    errors.append(f"concept {k}: {exc}")
        with lock:
            if errors and not status["done_count"]:
                raise RuntimeError("; ".join(errors))
            status.update(state="done", error="; ".join(errors) or None)
            save_status()
    except Exception as exc:
        status.update(state="failed", error=f"Variant generation failed: {exc}")
        save_status()
        raise


DEEPGAZE_COMMIT = "c7db17e2d1d7ea6468ffdee2cfaddf141095dcff"
CLIP_COMMIT = "d05afc436d78f1c48dc0dbf8e5980a9d471f35f6"
SALIENCY_LONG_SIDE = 1024
PLACEMENT_MODEL = {"layout": f"{SAM_MODEL}@{SAM_REVISION} (32x24 point grid)",
                   "saliency": f"DeepGaze IIE (matthias-k/DeepGaze@{DEEPGAZE_COMMIT[:12]}), uniform centre bias"}


def _download_deepgaze():
    import deepgaze_pytorch

    deepgaze_pytorch.DeepGazeIIE(pretrained=True)


saliency_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("git")
    .pip_install(
        "torch==2.7.1", "torchvision==0.22.1", "pillow==11.2.1", "numpy==2.2.5", "scipy==1.15.3",
        "boltons==25.0.0", "einops==0.8.1", "ftfy==6.3.1", "regex==2024.11.6", "tqdm==4.67.1", "packaging==25.0",
    )
    .run_commands(
        f"pip install --no-deps git+https://github.com/openai/CLIP.git@{CLIP_COMMIT}",
        f"pip install --no-deps git+https://github.com/matthias-k/DeepGaze.git@{DEEPGAZE_COMMIT}",
    )
    .env({"TORCH_HOME": "/root/torch_cache"})
    .run_function(_download_deepgaze)
    .add_local_python_source("shelfproof")
)


@app.function(image=sam_image, gpu="T4", volumes={str(JOBS): jobs}, timeout=600, max_containers=1)
def detect_layout(job_id: str) -> None:
    import numpy as np
    import torch
    from PIL import Image
    from transformers import Sam2Model, Sam2Processor

    from shelfproof.packaging import load_source
    from shelfproof.placement import group_rows, masks_to_detections

    if not JOB_ID.fullmatch(job_id):
        raise ValueError("Invalid job ID")
    jobs.reload()
    out = JOBS / job_id / "placement" / "layout"
    started = time.perf_counter()
    try:
        img = load_source(JOBS / job_id)
        w, h = img.size
        processor = Sam2Processor.from_pretrained(SAM_MODEL, revision=SAM_REVISION)
        model = Sam2Model.from_pretrained(SAM_MODEL, revision=SAM_REVISION).to("cuda").eval()
        points = [[float((i + 0.5) * w / 32), float((j + 0.5) * h / 24)] for j in range(24) for i in range(32)]
        inputs = processor(images=img, input_points=[[[p] for p in points]], input_labels=[[[1]] * len(points)],
                           return_tensors="pt").to("cuda")
        masks, ious = [], []
        with torch.no_grad():
            emb = model.get_image_embeddings(inputs["pixel_values"])
            for i in range(0, len(points), 64):
                o = model(image_embeddings=emb, input_points=inputs["input_points"][:, i:i + 64],
                          input_labels=inputs["input_labels"][:, i:i + 64], multimask_output=True)
                masks.append(processor.post_process_masks(o.pred_masks, inputs["original_sizes"])[0].cpu().numpy() > 0)
                ious.append(o.iou_scores[0].float().cpu().numpy())
        gpu_s = time.perf_counter() - started
        labels, dets = masks_to_detections(np.concatenate(masks), np.concatenate(ious))
        rows = group_rows(dets)
        Image.fromarray(labels.astype(np.uint16)).save(out / "labels.png")
        layout = {"source_size": [w, h], "detections": dets, "rows": rows, "model": PLACEMENT_MODEL["layout"],
                  "timings": {"gpu_s": round(gpu_s, 2), "total_s": round(time.perf_counter() - started, 2)}}
        (out / "layout.json").write_text(json.dumps(layout))
        (out / "status.json").write_text(json.dumps({"state": "done", "error": None}))
        jobs.commit()
        print(f"job {job_id}: layout {len(dets)} detections, {len(rows)} rows, {layout['timings']}")
    except Exception as exc:
        (out / "status.json").write_text(json.dumps({"state": "failed", "error": f"Layout detection failed: {exc}"}))
        jobs.commit()
        raise


@app.cls(image=saliency_image, gpu="L4", volumes={str(JOBS): jobs}, timeout=600, max_containers=4, scaledown_window=300)
class Saliency:
    @modal.enter()
    def load(self):
        import deepgaze_pytorch

        self.model = deepgaze_pytorch.DeepGazeIIE(pretrained=True).eval().to("cuda")

    @modal.method()
    def predict(self, job_id: str, rid: str, slot: int, distance_m: float, photo_distance_m: float):
        return self._predict(job_id, f"placement/runs/{rid}/scene_{int(slot)}.png", distance_m, photo_distance_m)

    @modal.method()
    def predict_path(self, job_id: str, rel: str):
        return self._predict(job_id, rel, 1.0, 1.0)

    def _predict(self, job_id: str, rel: str, distance_m: float, photo_distance_m: float):
        import numpy as np
        import torch
        import torch.nn.functional as F
        from PIL import Image

        from shelfproof.placement import SALIENCY_PATH, distance_blur

        if not (JOB_ID.fullmatch(job_id) and SALIENCY_PATH.fullmatch(rel)):
            raise ValueError("Invalid ID")
        jobs.reload()
        with Image.open(JOBS / job_id / rel) as img:
            rgb = np.asarray(distance_blur(img.convert("RGB"), distance_m, photo_distance_m))
        h, w = rgb.shape[:2]
        scale = SALIENCY_LONG_SIDE / max(h, w)
        sh, sw = round(h * scale), round(w * scale)
        x = torch.from_numpy(np.ascontiguousarray(rgb.transpose(2, 0, 1))).float()[None].to("cuda")
        x = F.interpolate(x, size=(sh, sw), mode="bicubic", align_corners=False, antialias=True).clamp(0, 255)
        centerbias = torch.full((1, sh, sw), -float(np.log(sh * sw)), device="cuda")
        with torch.inference_mode():
            dens = F.interpolate(self.model(x, centerbias)[:, 0].double().exp()[None], size=(h, w), mode="area")[0, 0]
            logd = dens.clamp_min(1e-30).log()
            logd = logd - logd.logsumexp(dim=(0, 1))
        return logd.float().cpu().numpy()


@app.function(image=variant_image, volumes={str(JOBS): jobs}, timeout=900, max_containers=4)
def run_placement(job_id: str, rid: str) -> None:
    from shelfproof.placement import execute_run

    if not (JOB_ID.fullmatch(job_id) and re.fullmatch(r"[0-9a-f]{8}", rid)):
        raise ValueError("Invalid ID")
    jobs.reload()
    execute_run(JOBS / job_id, rid, lambda calls: Saliency().predict.starmap(calls), jobs.commit)


@app.function(image=variant_image, volumes={str(JOBS): jobs}, timeout=600, max_containers=4)
def score_packaging(job_id: str, pid: str, vid: str) -> None:
    from shelfproof.placement import execute_attention

    if not (JOB_ID.fullmatch(job_id) and re.fullmatch(r"[0-9a-f]{8}", pid) and re.fullmatch(r"[0-9a-f]{8}", vid)):
        raise ValueError("Invalid ID")
    jobs.reload()
    execute_attention(JOBS / job_id, pid, vid, lambda calls: Saliency().predict_path.starmap(calls), jobs.commit)


web_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("fastapi[standard]", "pillow==11.2.1", "numpy==2.2.5")
    .add_local_python_source("shelfproof")
    .add_local_dir(Path(__file__).parent / "static", "/static")
)


@app.function(image=web_image, volumes={str(JOBS): jobs}, max_containers=1)
@modal.asgi_app()
def web():
    from fastapi import FastAPI, HTTPException, UploadFile
    from fastapi.responses import FileResponse, RedirectResponse
    from fastapi.staticfiles import StaticFiles
    from starlette.middleware.gzip import GZipMiddleware

    api = FastAPI()
    api.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=3)
    api.mount("/static", StaticFiles(directory="/static"), name="static")

    def job_dir(job_id: str) -> Path:
        if not JOB_ID.fullmatch(job_id) or not (JOBS / job_id).is_dir():
            raise HTTPException(404, "Unknown job")
        return JOBS / job_id

    @api.get("/")
    def index(job: str | None = None):
        if job is None:
            return RedirectResponse(f"/?job={DEFAULT_JOB}")
        return FileResponse("/static/index.html")

    @api.post("/api/jobs")
    def create(image: UploadFile):
        if not (image.content_type or "").startswith("image/"):
            raise HTTPException(400, "Expected an image upload")
        contents = image.file.read(MAX_UPLOAD + 1)
        if not contents or len(contents) > MAX_UPLOAD:
            raise HTTPException(413, "Upload a nonempty image no larger than 20 MB")
        jobs.reload()
        job_id = uuid.uuid4().hex[:12]
        job = JOBS / job_id
        job.mkdir(parents=True)
        (job / "input.image").write_bytes(contents)
        (job / "pipeline").write_text("textured-mesh")
        jobs.commit()
        (job / "call_id").write_text(image_to_3d.spawn(job_id).object_id)
        jobs.commit()
        return {"job_id": job_id}

    @api.get("/api/jobs/{job_id}")
    def status(job_id: str):
        jobs.reload()
        job = job_dir(job_id)
        if (job / "error.txt").exists():
            return {"state": "failed", "error": (job / "error.txt").read_text()}
        if (job / "mesh.glb").exists() and (job / "scene.json").exists():
            metadata = json.loads((job / "scene.json").read_text())
            return {"state": "done", "representation": "textured-mesh", "model": metadata["model"], "metadata": metadata}
        if not (job / "pipeline").exists() and (job / "scene.ply").exists():
            return {"state": "done", "representation": "splat", "model": DEPTH_MODEL}
        if not (job / "call_id").exists():
            return {"state": "running"}
        try:
            modal.FunctionCall.from_id((job / "call_id").read_text()).get(timeout=0)
        except TimeoutError:
            return {"state": "running"}
        except Exception:
            return {"state": "failed", "error": "Image processing failed or timed out. Try another photo."}
        return {"state": "failed", "error": "Finished without producing a scene."}

    @api.get("/api/jobs/{job_id}/scene.ply")
    def scene(job_id: str):
        jobs.reload()
        ply = job_dir(job_id) / "scene.ply"
        if not ply.exists():
            raise HTTPException(404, "Scene not ready")
        return FileResponse(ply, filename=f"shelf-{job_id}.ply")

    def artifact(job_id: str, filename: str, media_type: str):
        jobs.reload()
        path = job_dir(job_id) / filename
        if not path.is_file():
            raise HTTPException(404, "Artifact not ready")
        return FileResponse(path, media_type=media_type, headers={"Cache-Control": "private, max-age=31536000, immutable"})

    @api.get("/api/jobs/{job_id}/source.png")
    def source(job_id: str):
        return artifact(job_id, "source.png", "image/png")

    @api.get("/api/jobs/{job_id}/mesh.glb")
    def mesh(job_id: str):
        return artifact(job_id, "mesh.glb", "model/gltf-binary")

    @api.get("/api/jobs/{job_id}/scene.json")
    def metadata(job_id: str):
        return artifact(job_id, "scene.json", "application/json")

    from shelfproof.packaging_api import register_packaging_routes

    register_packaging_routes(api, jobs, job_dir, segment_product, generate_variants)
    from shelfproof.placement_api import register_placement_routes

    register_placement_routes(api, jobs, job_dir, detect_layout, run_placement, PLACEMENT_MODEL, score_packaging)
    return api


@app.local_entrypoint()
def main(image: str):
    source = Path(image)
    if not source.is_file() or not 0 < source.stat().st_size <= MAX_UPLOAD:
        raise ValueError("Upload a nonempty image no larger than 20 MB")
    job_id = uuid.uuid4().hex[:12]
    with jobs.batch_upload() as batch:
        batch.put_file(image, f"/{job_id}/input.image")
    print(f"job {job_id}: building textured mesh")
    image_to_3d.remote(job_id)
    out = Path("out")
    out.mkdir(exist_ok=True)
    for remote_name, suffix in (("mesh.glb", "glb"), ("scene.json", "scene.json"), ("scene.ply", "ply")):
        destination = out / f"{job_id}.{suffix}"
        with destination.open("wb") as f:
            for chunk in jobs.read_file(f"{job_id}/{remote_name}"):
                f.write(chunk)
        print(f"wrote {destination}")
