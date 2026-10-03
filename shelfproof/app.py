import re
import uuid
from pathlib import Path

import modal

app = modal.App("shelfproof")
jobs = modal.Volume.from_name("shelfproof-jobs", create_if_missing=True)
JOBS = Path("/jobs")
JOB_ID = re.compile(r"^[0-9a-f]{12}$")

DEPTH_MODEL = "depth-anything/Depth-Anything-V2-Small-hf"


def _download_depth_model():
    from transformers import pipeline

    pipeline("depth-estimation", model=DEPTH_MODEL)


recon_image = (
    modal.Image.debian_slim(python_version="3.11")
    .pip_install("torch", "transformers", "pillow", "numpy")
    .run_function(_download_depth_model)
    .add_local_python_source("shelfproof")
)


@app.function(image=recon_image, gpu="T4", volumes={str(JOBS): jobs}, timeout=30 * 60)
def image_to_3d(job_id: str) -> None:
    import numpy as np
    import torch.nn.functional as F
    from PIL import Image
    from transformers import pipeline

    from shelfproof.splat import image_to_splat_ply

    job = JOBS / job_id

    def fail(msg: str):
        (job / "error.txt").write_text(msg)
        jobs.commit()
        raise RuntimeError(msg)

    inputs = [p for p in job.iterdir() if p.name.startswith("input.")]
    if not inputs:
        fail("No input image found for this job.")
    try:
        img = Image.open(inputs[0]).convert("RGB")
    except Exception:
        fail("Could not read the uploaded file as an image.")
    if max(img.size) > 1024:
        img.thumbnail((1024, 1024))
    w, h = img.size

    try:
        pipe = pipeline("depth-estimation", model=DEPTH_MODEL, device=0)
        depth = pipe(img)["predicted_depth"]
        depth = F.interpolate(
            depth[None, None].float(), size=(h, w), mode="bilinear", align_corners=False
        )[0, 0].cpu().numpy()
    except Exception as e:
        fail(f"Depth estimation failed: {e}")

    disp8 = ((depth - depth.min()) / (depth.max() - depth.min() + 1e-8) * 255).astype(np.uint8)
    Image.fromarray(disp8).save(job / "depth.png")

    (job / "scene.ply").write_bytes(image_to_splat_ply(np.asarray(img), depth))
    jobs.commit()


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
    def create(image: UploadFile):
        if not (image.content_type or "").startswith("image/"):
            raise HTTPException(400, "Expected an image upload")
        ext = Path(image.filename or "").suffix or ".png"
        job_id = uuid.uuid4().hex[:12]
        job = JOBS / job_id
        job.mkdir(parents=True)
        with (job / f"input{ext}").open("wb") as f:
            f.write(image.file.read())
        jobs.commit()
        (job / "call_id").write_text(image_to_3d.spawn(job_id).object_id)
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


@app.local_entrypoint()
def main(image: str):
    job_id = uuid.uuid4().hex[:12]
    ext = Path(image).suffix or ".png"
    with jobs.batch_upload() as batch:
        batch.put_file(image, f"/{job_id}/input{ext}")
    print(f"job {job_id}: building 3D")
    image_to_3d.remote(job_id)
    out = Path("out") / f"{job_id}.ply"
    with out.open("wb") as f:
        for chunk in jobs.read_file(f"{job_id}/scene.ply"):
            f.write(chunk)
    print(f"wrote {out}")
