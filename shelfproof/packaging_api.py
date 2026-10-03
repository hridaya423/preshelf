"""Phase 2 packaging routes. All IDs are lowercase hex: job 12, pid 8, vid 8. Errors: {"detail": str} with 4xx/5xx.

POST /api/jobs/{job}/products
    JSON {"point": {"x", "y"}} or {"box": {"x0", "y0", "x1", "y1"}}, source.png pixel coords (numbers).
    Synchronous SAM 2.1 segmentation (cold start up to ~1 min). -> Product
GET  /api/jobs/{job}/products -> [Product, ...] oldest first
GET  /api/jobs/{job}/products/{pid} -> Product
GET  /api/jobs/{job}/products/{pid}/{mask.png|cutout.png|crop.png}
    mask.png: L, full source size, 255 = product. cutout.png: RGBA, tight bbox. crop.png: RGB, crop_box.
GET  /api/jobs/{job}/products/{pid}/references/{side.png|back.png}
POST /api/jobs/{job}/products/{pid}/confirm
    multipart: name (required, <=80), category (optional, <=60), side, back (optional image files <=20 MB).
    -> Product (confirmed true, references lists uploaded views)
POST /api/jobs/{job}/products/{pid}/variants
    JSON brief {product_name?, category?, target_audience?, price_tier? (value|mid|premium), brand_tone?, keep?,
    avoid?, notes?, count? (1-4, default 3), model? (gpt-image-2.5-sunburst (default)|nano-banana-pro),
    quality? (auto|max|xhigh|high|medium|low, default high; Sunburst only)}; product_name/category default to the
    confirmed product. Per concept: one packshot call (chosen model), then one Sunburst masked edit of the real
    shelf; all concepts run concurrently. -> {"variant_set_id": vid}
GET  /api/jobs/{job}/products/{pid}/variants/{vid}
    -> {"variant_set_id", "state": running|done|failed, "done_count", "total", "error": str|null,
        "model": "gpt-image-2.5-sunburst"|"nano-banana-pro", "placements": {"K": "edit"|"composite"},
        "cost": float USD (sum of Runware costs so far), "prompts": [str], "placement_prompt", "negative_prompt"
        (always null), "brief", "width", "height" (packshot size), "files": [names available now]}
    state is "done" if at least one concept finished; error then lists failed concepts.
GET  /api/jobs/{job}/products/{pid}/variants/{vid}/{original.png|variant_K.png|shelf_K.png}  (K = 1..total)
    original.png: product crop before redesign; variant_K: generated packshot (RGBA with transparent background for
    Sunburst, RGB on light grey for Nano Banana Pro); shelf_K: full shelf (exact source.png size) with the new pack:
    "edit" = Sunburst masked edit pasted back only inside the feathered product mask, "composite" = deterministic
    fallback paste of the packshot.

Product = {"pid", "prompt": {"point"|"box"}, "bbox": [x0, y0, x1, y1] (exclusive x1/y1), "crop_box": [...],
           "source_size": [w, h], "area_px", "score", "created", "name"?, "category"?, "confirmed"?, "references"?}
"""
import io
import json
import re
import time
import uuid
from pathlib import Path

import modal
from fastapi import File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse

PID = re.compile(r"^[0-9a-f]{8}$")
VARIANT_FILE = re.compile(r"^(original|(variant|shelf)_[1-4])\.png$")
PRODUCT_FILES = {"mask.png", "cutout.png", "crop.png"}
REFERENCE_FILES = {"side.png", "back.png"}
MAX_UPLOAD = 20 * 1024 * 1024


def register_packaging_routes(api, jobs, job_dir, segment_product, generate_variants):
    from PIL import Image, ImageOps

    from shelfproof.packaging import build_variant_prompts, load_source, validate_brief

    def product_dir(job_id: str, pid: str) -> Path:
        path = job_dir(job_id) / "products" / pid
        if not PID.fullmatch(pid) or not (path / "product.json").is_file():
            raise HTTPException(404, "Unknown product")
        return path

    def read_json(path: Path) -> dict:
        return json.loads(path.read_text())

    @api.post("/api/jobs/{job_id}/products")
    def create_product(job_id: str, body: dict):
        jobs.reload()
        job = job_dir(job_id)
        try:
            w, h = load_source(job).size
        except FileNotFoundError:
            raise HTTPException(409, "Job has no source image yet")
        prompt = _validate_prompt(body, w, h)
        try:
            return segment_product.remote(job_id, prompt)
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        except Exception as exc:
            raise HTTPException(502, f"Segmentation failed: {exc}")

    @api.get("/api/jobs/{job_id}/products")
    def list_products(job_id: str):
        jobs.reload()
        root = job_dir(job_id) / "products"
        items = [read_json(p) for p in root.glob("*/product.json")] if root.is_dir() else []
        return sorted(items, key=lambda p: p["created"])

    @api.get("/api/jobs/{job_id}/products/{pid}")
    def get_product(job_id: str, pid: str):
        jobs.reload()
        return read_json(product_dir(job_id, pid) / "product.json")

    @api.get("/api/jobs/{job_id}/products/{pid}/references/{name}")
    def reference_file(job_id: str, pid: str, name: str):
        jobs.reload()
        path = product_dir(job_id, pid) / "references" / name
        if name not in REFERENCE_FILES or not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="image/png")

    @api.get("/api/jobs/{job_id}/products/{pid}/{name}")
    def product_file(job_id: str, pid: str, name: str):
        jobs.reload()
        path = product_dir(job_id, pid) / name
        if name not in PRODUCT_FILES or not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="image/png")

    def reencode(upload: UploadFile | None, label: str):
        if upload is None or (not upload.filename and not upload.size):
            return None
        if not (upload.content_type or "").startswith("image/"):
            raise HTTPException(400, f"{label} must be an image")
        data = upload.file.read(MAX_UPLOAD + 1)
        if not data or len(data) > MAX_UPLOAD:
            raise HTTPException(413, f"{label} must be a nonempty image no larger than 20 MB")
        try:
            with Image.open(io.BytesIO(data)) as img:
                if img.width * img.height > 20_000_000:
                    raise HTTPException(413, f"{label} must be at most 20 megapixels")
                return ImageOps.exif_transpose(img).convert("RGB")
        except HTTPException:
            raise
        except Exception:
            raise HTTPException(400, f"{label} is not a readable image")

    @api.post("/api/jobs/{job_id}/products/{pid}/confirm")
    def confirm(job_id: str, pid: str, name: str = Form(...), category: str = Form(""),
                side: UploadFile | None = File(None), back: UploadFile | None = File(None)):
        jobs.reload()
        path = product_dir(job_id, pid)
        name, category = name.strip(), category.strip()
        if not 1 <= len(name) <= 80 or len(category) > 60:
            raise HTTPException(400, "name must be 1-80 characters and category at most 60")
        images = {"side": reencode(side, "side"), "back": reencode(back, "back")}
        product = read_json(path / "product.json")
        refs = path / "references"
        for view, img in images.items():
            if img is not None:
                refs.mkdir(exist_ok=True)
                img.save(refs / f"{view}.png")
        product.update(name=name, category=category, confirmed=True,
                       references=sorted(v for v in ("side", "back") if (refs / f"{v}.png").is_file()))
        (path / "product.json").write_text(json.dumps(product))
        jobs.commit()
        return product

    @api.post("/api/jobs/{job_id}/products/{pid}/variants")
    def create_variants(job_id: str, pid: str, body: dict):
        jobs.reload()
        path = product_dir(job_id, pid)
        product = read_json(path / "product.json")
        defaults = {"product_name": product.get("name", ""), "category": product.get("category", "")}
        try:
            brief = validate_brief({**defaults, **{k: v for k, v in body.items() if v not in (None, "")}})
            prompts = build_variant_prompts(brief, len(product.get("references") or []))
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        vid = uuid.uuid4().hex[:8]
        out = path / "variants" / vid
        out.mkdir(parents=True)
        (out / "prompt.json").write_text(json.dumps({"brief": brief, "prompts": prompts, "created": time.time()}))
        (out / "status.json").write_text(json.dumps(
            {"state": "running", "done_count": 0, "total": len(prompts), "error": None, "model": brief["model"],
             "placements": {}, "cost": 0.0}))
        jobs.commit()
        (out / "call_id").write_text(generate_variants.spawn(job_id, pid, vid).object_id)
        jobs.commit()
        return {"variant_set_id": vid}

    def variant_dir(job_id: str, pid: str, vid: str) -> Path:
        path = product_dir(job_id, pid) / "variants" / vid
        if not PID.fullmatch(vid) or not (path / "status.json").is_file():
            raise HTTPException(404, "Unknown variant set")
        return path

    @api.get("/api/jobs/{job_id}/products/{pid}/variants/{vid}")
    def variant_status(job_id: str, pid: str, vid: str):
        jobs.reload()
        path = variant_dir(job_id, pid, vid)
        status = read_json(path / "status.json")
        if status["state"] == "running" and (path / "call_id").is_file():
            try:
                modal.FunctionCall.from_id((path / "call_id").read_text()).get(timeout=0)
                jobs.reload()
                status = read_json(path / "status.json")
                if status["state"] == "running":
                    status.update(state="failed", error="Generation finished without producing results.")
            except TimeoutError:
                pass
            except Exception:
                jobs.reload()
                status = read_json(path / "status.json")
                if status["state"] == "running":
                    status.update(state="failed", error="Generation crashed or timed out.")
        meta = read_json(path / "prompt.json")
        files = sorted(p.name for p in path.iterdir() if VARIANT_FILE.fullmatch(p.name))
        return {"variant_set_id": vid, **status, "prompts": meta["prompts"], "brief": meta["brief"],
                "placement_prompt": meta.get("placement_prompt"), "negative_prompt": meta.get("negative_prompt"),
                "model": status.get("model") or meta["brief"].get("model"), "width": meta.get("width"),
                "height": meta.get("height"), "files": files}

    @api.get("/api/jobs/{job_id}/products/{pid}/variants/{vid}/{name}")
    def variant_file(job_id: str, pid: str, vid: str, name: str):
        jobs.reload()
        path = variant_dir(job_id, pid, vid) / name
        if not VARIANT_FILE.fullmatch(name) or not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="image/png")


def _validate_prompt(body, w: int, h: int) -> dict:
    def num(d, k):
        v = d.get(k) if isinstance(d, dict) else None
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise HTTPException(400, f"{k} must be a number")
        return round(float(v), 1)

    if not isinstance(body, dict) or ("point" in body) == ("box" in body):
        raise HTTPException(400, "Send exactly one of point {x, y} or box {x0, y0, x1, y1}")
    if "point" in body:
        x, y = num(body["point"], "x"), num(body["point"], "y")
        if not (0 <= x < w and 0 <= y < h):
            raise HTTPException(400, f"Point must lie inside the {w}x{h} source image")
        return {"point": {"x": x, "y": y}}
    b = {k: num(body["box"], k) for k in ("x0", "y0", "x1", "y1")}
    if not (0 <= b["x0"] < b["x1"] <= w and 0 <= b["y0"] < b["y1"] <= h) or min(b["x1"] - b["x0"], b["y1"] - b["y0"]) < 2:
        raise HTTPException(400, f"Box must be at least 2 px and lie inside the {w}x{h} source image")
    return {"box": b}
