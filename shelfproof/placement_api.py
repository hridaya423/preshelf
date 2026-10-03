"""Phase 3 shelf-position routes. IDs: job 12 hex, pid 8 hex, run id (rid) 8 hex. Errors: {"detail": str} 4xx/5xx.
All coordinates are source.png pixels; bbox = [x0, y0, x1, y1] with exclusive x1/y1. Row 0 is the top shelf.
Every number is a model estimate under stated assumptions, not measured shopper behaviour.

POST /api/jobs/{job}/placement/layout
    Start SAM 2.1 shelf-layout detection unless it is already running or done. -> Layout
GET  /api/jobs/{job}/placement/layout -> Layout
    Layout = {"state": "missing"|"running"|"done"|"failed", "error": str|null, "source_size": [w, h],
              "detections": [{"id": int >= 1, "bbox", "row": int, "score": float}],
              "rows": [{"row", "y0", "y1", "median_height", "count"}]}
GET  /api/jobs/{job}/placement/candidates?pid=P -> {"product_row": int, "product_det": int|null, "slots": [Slot]}
POST /api/jobs/{job}/placement/slot  JSON {"pid", "x", "y"} -> Slot for a user click
    (click on a detected product = swap with it; click on empty shelf = place at x on the nearest row).
    Slot = {"id": str, "label": str, "kind": "current"|"swap"|"place", "target": det id|null,
            "x": number|null, "row": int, "rect": [x0, y0, x1, y1] (approximate footprint of the moved product)}
GET  /api/jobs/{job}/placement/personas
    -> {"presets": [Persona], "missions": {name: {"saliency_exp", "centre_sigma", "band_offset_cm", "label",
        "rationale"}}, "time_pressure": {"low"|"high": {"gamma", "rationale"}}, "assumptions": Assumptions,
        "formula": str, "disclaimer": str}
    Persona = {"name": str <= 40, "eye_height_cm": 80-200, "distance_m": 0.3-5, "mission": "browse"|"brand_search"|
               "cheapest", "time_pressure": "low"|"high"}
    Assumptions = {"shelf_top_cm": top of the top row, "shelf_bottom_cm": bottom of the bottom row,
                   "photo_distance_m": camera distance the photo was taken from}
POST /api/jobs/{job}/placement/runs
    JSON {"pid", "slots": [Slot] (1-8; the "current" slot is added if missing), "personas": [Persona] (1-6),
          "assumptions": Assumptions?, "packaging": {"vid": 8 hex, "concept": 1-4}|null?} -> {"run_id"}
    packaging defaults to the original; a concept uses its shelf image inside the original product mask only.
    Results.packaging records the selected design. Current-position baseline uses that same design.
    Renders one scene per slot, then fans out DeepGaze IIE over slots x personas on GPU.
GET  /api/jobs/{job}/placement/runs/{rid}
    -> {"run_id", "state": "running"|"done"|"failed", "stage": str, "done_count", "total", "error": str|null,
        "request": {...normalised request...}, "timings": {...seconds...}, "results": Results|null}
    Results = {"slots": [{**Slot, "scene": "scene_I.png", "mean_final_share", "mean_rank",
                          "per_persona": [{"persona": P, "saliency_share", "position_factor", "final_share",
                                           "rank", "n_products", "heatmap": "heat_I_P.png",
                                           "saliency_heatmap": "sal_I_P.png"}]}],
               "ranking": [slot indices, best first], "recommendation": {"slot": I, "reasons": [str]},
               "personas": [Persona], "formula": str, "disclaimer": str, "model": {...}}
    Shares are fractions 0-1 of modelled attention inside the product mask; rank 1 = most attention of all products.
GET  /api/jobs/{job}/placement/runs/{rid}/{scene_I.png|heat_I_P.png|sal_I_P.png}
    scene_I: RGB, source size, shelf with the product moved to slot I. heat/sal: RGBA overlays, source size.

Packaging attention (DeepGaze IIE on the phase-2 concepts, same photo/viewpoint/position):
GET  /api/jobs/{job}/placement/packaging/{pid} -> [{"vid", "state", "files": [shelf_K.png], "created", "brief"}]
POST /api/jobs/{job}/placement/packaging/{pid}/{vid} -> Attention (starts scoring unless running/done)
GET  /api/jobs/{job}/placement/packaging/{pid}/{vid} -> Attention
    Attention = {"state": "missing"|"running"|"done"|"failed", "done_count", "total", "error",
                 "results": {"rows": [{"key": "original"|"K", "label", "image": path under /api/jobs/{job}/
                 (source.png or products/{pid}/variants/{vid}/shelf_K.png), "heatmap", "saliency_share", "rank",
                 "n_products", "delta_pp", "ratio"}], "best": key, "reasons": [str], "disclaimer"}|null}
GET  /api/jobs/{job}/placement/packaging/{pid}/{vid}/{sal_original.png|sal_K.png} -> RGBA overlay, source size
"""
import json
import re
import time
import uuid
from pathlib import Path

import modal
from fastapi import HTTPException
from fastapi.responses import FileResponse

PID = re.compile(r"^[0-9a-f]{8}$")
RUN_FILE = re.compile(r"^(scene_[0-7]|(heat|sal)_[0-7]_[0-5])\.png$")


def register_placement_routes(api, jobs, job_dir, detect_layout, run_placement, model_info=None, score_packaging=None):
    from shelfproof import placement as pl

    def read_json(path: Path) -> dict:
        return json.loads(path.read_text())

    def call_state(path: Path, status: dict, what: str) -> dict:
        if status["state"] != "running" or not (path / "call_id").is_file():
            return status
        try:
            modal.FunctionCall.from_id((path / "call_id").read_text()).get(timeout=0)
        except TimeoutError:
            return status
        except Exception:
            pass
        jobs.reload()
        status = read_json(path / "status.json")
        if status["state"] == "running":
            status.update(state="failed", error=f"{what} crashed, timed out or finished without results.")
        return status

    def layout_dir(job_id: str) -> Path:
        return job_dir(job_id) / "placement" / "layout"

    def layout_response(job_id: str) -> dict:
        path = layout_dir(job_id)
        if not (path / "status.json").is_file():
            return {"state": "missing", "error": None, "detections": [], "rows": [], "source_size": None}
        status = call_state(path, read_json(path / "status.json"), "Layout detection")
        layout = read_json(path / "layout.json") if status["state"] == "done" else {}
        return {"state": status["state"], "error": status.get("error"), "detections": layout.get("detections", []),
                "rows": layout.get("rows", []), "source_size": layout.get("source_size"),
                **{k: layout[k] for k in ("timings", "model") if k in layout}}

    @api.get("/api/jobs/{job_id}/placement/layout")
    def get_layout(job_id: str):
        jobs.reload()
        return layout_response(job_id)

    @api.post("/api/jobs/{job_id}/placement/layout")
    def start_layout(job_id: str):
        jobs.reload()
        current = layout_response(job_id)
        if current["state"] in ("running", "done"):
            return current
        if not (job_dir(job_id) / "source.png").is_file():
            raise HTTPException(409, "Job has no source image yet")
        path = layout_dir(job_id)
        path.mkdir(parents=True, exist_ok=True)
        (path / "status.json").write_text(json.dumps({"state": "running", "error": None, "started": time.time()}))
        jobs.commit()
        (path / "call_id").write_text(detect_layout.spawn(job_id).object_id)
        jobs.commit()
        return layout_response(job_id)

    def inputs(job_id: str, pid):
        if not isinstance(pid, str) or not PID.fullmatch(pid):
            raise HTTPException(400, "pid must be 8 lowercase hex characters")
        job = job_dir(job_id)
        if not (job / "products" / pid / "product.json").is_file():
            raise HTTPException(404, "Unknown product")
        if layout_response(job_id)["state"] != "done":
            raise HTTPException(409, "Shelf layout is not ready; POST /placement/layout first")
        return pl.load_inputs(job, pid)

    @api.get("/api/jobs/{job_id}/placement/candidates")
    def candidates(job_id: str, pid: str):
        jobs.reload()
        _, _, _, ctx = inputs(job_id, pid)
        return {"product_row": ctx["product_row"], "product_det": ctx["product_det"], "slots": pl.propose_slots(ctx)}

    @api.post("/api/jobs/{job_id}/placement/slot")
    def click_slot(job_id: str, body: dict):
        jobs.reload()
        _, labels, mask, ctx = inputs(job_id, body.get("pid"))
        x, y = body.get("x"), body.get("y")
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in (x, y)):
            raise HTTPException(400, "x and y must be numbers")
        try:
            return pl.slot_for_click(ctx, labels, mask, float(x), float(y))
        except ValueError as exc:
            raise HTTPException(400, str(exc))

    @api.get("/api/jobs/{job_id}/placement/personas")
    def personas(job_id: str):
        job_dir(job_id)
        return {"presets": pl.PRESETS, "missions": pl.MISSIONS, "time_pressure": pl.TIME_PRESSURE,
                "assumptions": pl.ASSUMPTIONS, "formula": pl.FORMULA, "disclaimer": pl.DISCLAIMER}

    @api.post("/api/jobs/{job_id}/placement/runs")
    def create_run(job_id: str, body: dict):
        jobs.reload()
        pid = body.get("pid")
        _, _, _, ctx = inputs(job_id, pid)
        raw_slots, raw_personas = body.get("slots"), body.get("personas")
        if not isinstance(raw_slots, list) or not 1 <= len(raw_slots) <= 8:
            raise HTTPException(400, "Send 1-8 slots")
        if not isinstance(raw_personas, list) or not 1 <= len(raw_personas) <= 6:
            raise HTTPException(400, "Send 1-6 personas")
        try:
            slots = [pl.make_slot(ctx, s.get("kind"), s.get("target"), s.get("x"), s.get("row"))
                     if isinstance(s, dict) else pl.make_slot(ctx, None) for s in raw_slots]
            people = [pl.validate_persona(p) for p in raw_personas]
            assumptions = pl.validate_assumptions(body.get("assumptions"))
            packaging = body.get("packaging")
            pl.packaging_path(job_dir(job_id), pid, packaging)
            if packaging is not None:
                packaging = {"vid": packaging["vid"], "concept": packaging["concept"]}
        except ValueError as exc:
            raise HTTPException(400, str(exc))
        labels = {s["id"]: s.get("label") for s in raw_slots if isinstance(s, dict) and isinstance(s.get("label"), str)}
        unique = {}
        for s in slots:
            if labels.get(s["id"]):
                s["label"] = re.sub(r"[\x00-\x1f\x7f]+", " ", labels[s["id"]]).strip()[:80] or s["label"]
            unique.setdefault(s["id"], s)
        if "current" not in unique:
            if len(unique) >= 8:
                raise HTTPException(400, "Send at most 7 slots besides the current position")
            unique = {"current": pl.make_slot(ctx, "current"), **unique}
        rid = uuid.uuid4().hex[:8]
        run = job_dir(job_id) / "placement" / "runs" / rid
        run.mkdir(parents=True)
        request = {"pid": pid, "slots": list(unique.values()), "personas": people, "assumptions": assumptions,
                   "created": time.time(), "model": model_info or {}, "packaging": packaging}
        (run / "request.json").write_text(json.dumps(request))
        total = len(unique) * len(people)
        (run / "status.json").write_text(json.dumps({"state": "running", "stage": "queued", "done_count": 0,
                                                     "total": total, "error": None, "timings": {}}))
        jobs.commit()
        (run / "call_id").write_text(run_placement.spawn(job_id, rid).object_id)
        jobs.commit()
        return {"run_id": rid}

    def run_dir(job_id: str, rid: str) -> Path:
        path = job_dir(job_id) / "placement" / "runs" / rid
        if not PID.fullmatch(rid) or not (path / "status.json").is_file():
            raise HTTPException(404, "Unknown run")
        return path

    @api.get("/api/jobs/{job_id}/placement/runs/{rid}")
    def run_status(job_id: str, rid: str):
        jobs.reload()
        path = run_dir(job_id, rid)
        status = call_state(path, read_json(path / "status.json"), "Placement run")
        results = read_json(path / "results.json") if status["state"] == "done" else None
        return {"run_id": rid, **status, "request": read_json(path / "request.json"), "results": results}

    @api.get("/api/jobs/{job_id}/placement/runs/{rid}/{name}")
    def run_file(job_id: str, rid: str, name: str):
        jobs.reload()
        path = run_dir(job_id, rid) / name
        if not RUN_FILE.fullmatch(name) or not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="image/png")

    def variant_set_dir(job_id: str, pid: str, vid: str) -> Path:
        path = job_dir(job_id) / "products" / pid / "variants" / vid
        if not (PID.fullmatch(pid) and PID.fullmatch(vid)) or not (path / "status.json").is_file():
            raise HTTPException(404, "Unknown variant set")
        return path

    @api.get("/api/jobs/{job_id}/placement/packaging/{pid}")
    def variant_sets(job_id: str, pid: str):
        jobs.reload()
        root = job_dir(job_id) / "products" / pid / "variants"
        if not PID.fullmatch(pid) or not root.is_dir():
            return []
        out = []
        for d in root.iterdir():
            if PID.fullmatch(d.name) and (d / "status.json").is_file() and (d / "prompt.json").is_file():
                meta = read_json(d / "prompt.json")
                out.append({"vid": d.name, "state": read_json(d / "status.json").get("state"),
                            "files": sorted(p.name for p in d.glob("shelf_[1-4].png")),
                            "created": meta.get("created", 0), "brief": meta.get("brief", {})})
        return sorted(out, key=lambda v: -v["created"])

    def attention_response(job_id: str, pid: str, vid: str) -> dict:
        variant_set_dir(job_id, pid, vid)
        path = job_dir(job_id) / "placement" / "packaging" / f"{pid}-{vid}"
        if not (path / "status.json").is_file():
            return {"state": "missing", "done_count": 0, "total": 0, "error": None, "results": None}
        status = call_state(path, read_json(path / "status.json"), "Attention scoring")
        return {**status, "results": read_json(path / "results.json") if status["state"] == "done" else None}

    @api.get("/api/jobs/{job_id}/placement/packaging/{pid}/{vid}")
    def get_attention(job_id: str, pid: str, vid: str):
        jobs.reload()
        return attention_response(job_id, pid, vid)

    @api.post("/api/jobs/{job_id}/placement/packaging/{pid}/{vid}")
    def start_attention(job_id: str, pid: str, vid: str):
        jobs.reload()
        current = attention_response(job_id, pid, vid)
        if current["state"] in ("running", "done"):
            return current
        if not any(variant_set_dir(job_id, pid, vid).glob("shelf_[1-4].png")):
            raise HTTPException(409, "This variant set has no shelf images yet")
        path = job_dir(job_id) / "placement" / "packaging" / f"{pid}-{vid}"
        path.mkdir(parents=True, exist_ok=True)
        (path / "status.json").write_text(json.dumps({"state": "running", "done_count": 0, "total": 0, "error": None}))
        jobs.commit()
        (path / "call_id").write_text(score_packaging.spawn(job_id, pid, vid).object_id)
        jobs.commit()
        return attention_response(job_id, pid, vid)

    @api.get("/api/jobs/{job_id}/placement/packaging/{pid}/{vid}/{name}")
    def attention_file(job_id: str, pid: str, vid: str, name: str):
        jobs.reload()
        variant_set_dir(job_id, pid, vid)
        path = job_dir(job_id) / "placement" / "packaging" / f"{pid}-{vid}" / name
        if not re.fullmatch(r"sal_(original|[1-4])\.png", name) or not path.is_file():
            raise HTTPException(404, "Not found")
        return FileResponse(path, media_type="image/png")
