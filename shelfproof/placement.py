import json
import math
import re
import time
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

DISCLAIMER = "Model estimate under stated assumptions; not measured shopper behaviour."
FORMULA = (
    "A(x,y) ∝ [ S(x,y)^a · E(y) · C(x) ]^γ, normalised to sum to 1. "
    "S = DeepGaze IIE saliency density of the scene (uniform centre bias, blurred for viewing distance). "
    "E = 0.3 + 0.7·eye-level band: Gaussian over estimated shelf height h(y), centre = eye height − d·tan15° − "
    "mission offset, σ = d·tan15° (d = viewing distance). C = 0.5 + 0.5·horizontal centre bias: Gaussian around the "
    "bay centre, σ = mission centre_sigma × image width. The floors (0.3, 0.5) are assumptions that keep off-band "
    "shelves visible rather than invisible. a = mission saliency exponent, γ = time-pressure sharpening. "
    "Final share = Σ A inside the product mask; saliency share = Σ S inside the mask; position factor = final / saliency. "
    "Overall slot score = mean final share over personas (equal weights)."
)
MISSIONS = {
    "browse": {
        "label": "Browsing the category", "saliency_exp": 1.0, "centre_sigma": 0.30, "band_offset_cm": 0,
        "rationale": "Unplanned browsing is driven by what stands out (saliency exponent 1) with a strong horizontal "
                     "centre bias (central gaze cascade, Atalay et al. 2012; Chandon et al. 2009). Assumed weights.",
    },
    "brand_search": {
        "label": "Looking for a named brand", "saliency_exp": 0.5, "centre_sigma": 0.50, "band_offset_cm": 0,
        "rationale": "Goal-directed search relies less on bottom-up saliency (exponent 0.5) and sweeps wider "
                     "(weaker centre bias). Assumed, not calibrated.",
    },
    "cheapest": {
        "label": "Looking for the cheapest option", "saliency_exp": 0.75, "centre_sigma": 0.45, "band_offset_cm": 20,
        "rationale": "Price-seekers scan price labels and lower shelves, where value ranges are conventionally "
                     "merchandised: eye-level band shifted 20 cm lower. Merchandising convention, not measured.",
    },
}
TIME_PRESSURE = {
    "low": {"gamma": 1.0, "rationale": "No sharpening."},
    "high": {"gamma": 1.5, "rationale": "Under time pressure shoppers make fewer fixations concentrated on the most "
                                        "prominent central items (Reutskaja et al. 2011); modelled as γ = 1.5."},
}
PRESETS = [
    {"name": "Child (about 8)", "eye_height_cm": 115, "distance_m": 0.8, "mission": "browse", "time_pressure": "low"},
    {"name": "Average adult", "eye_height_cm": 158, "distance_m": 1.2, "mission": "browse", "time_pressure": "low"},
    {"name": "Tall adult in a hurry", "eye_height_cm": 178, "distance_m": 1.5, "mission": "brand_search",
     "time_pressure": "high"},
    {"name": "Budget shopper", "eye_height_cm": 150, "distance_m": 1.0, "mission": "cheapest", "time_pressure": "low"},
    {"name": "Wheelchair user", "eye_height_cm": 120, "distance_m": 1.0, "mission": "browse", "time_pressure": "low"},
]
ASSUMPTIONS = {"shelf_top_cm": 190, "shelf_bottom_cm": 15, "photo_distance_m": 2.0}
TAN15 = math.tan(math.radians(15))
E_FLOOR, C_FLOOR = 0.3, 0.5
STOPS = np.array([[0, 0, 4], [87, 16, 110], [188, 55, 84], [249, 142, 9], [252, 255, 164]], np.float32)


def _num(d, key, lo, hi):
    v = d.get(key)
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not lo <= v <= hi:
        raise ValueError(f"{key} must be a number from {lo} to {hi}")
    return float(v)


def validate_persona(p) -> dict:
    if not isinstance(p, dict):
        raise ValueError("Each persona must be an object")
    name = re.sub(r"[\x00-\x1f\x7f]+", " ", str(p.get("name") or "")).strip()
    if not 1 <= len(name) <= 40:
        raise ValueError("Persona name must be 1-40 characters")
    if p.get("mission") not in MISSIONS or p.get("time_pressure") not in TIME_PRESSURE:
        raise ValueError(f"mission must be one of {', '.join(MISSIONS)}; time_pressure low or high")
    return {"name": name, "eye_height_cm": _num(p, "eye_height_cm", 80, 200), "distance_m": _num(p, "distance_m", 0.3, 5),
            "mission": p["mission"], "time_pressure": p["time_pressure"]}


def validate_assumptions(a) -> dict:
    a = {**ASSUMPTIONS, **(a or {})}
    out = {"shelf_top_cm": _num(a, "shelf_top_cm", 50, 300), "shelf_bottom_cm": _num(a, "shelf_bottom_cm", 0, 150),
           "photo_distance_m": _num(a, "photo_distance_m", 0.3, 10)}
    if out["shelf_top_cm"] <= out["shelf_bottom_cm"] + 20:
        raise ValueError("shelf_top_cm must be at least 20 cm above shelf_bottom_cm")
    return out


def group_rows(dets: list[dict]) -> list[dict]:
    """Assign det["row"] (0 = top) by clustering bottom edges; return row stats."""
    if not dets:
        return []
    med = float(np.median([d["bbox"][3] - d["bbox"][1] for d in dets]))
    tol = 0.25 * med
    clusters = []
    for d in sorted(dets, key=lambda d: d["bbox"][3]):
        if clusters and d["bbox"][3] - clusters[-1][-1]["bbox"][3] <= tol:
            clusters[-1].append(d)
        else:
            clusters.append([d])
    big = [c for c in clusters if len(c) >= max(3, 0.05 * len(dets))] or clusters
    anchors = [float(np.median([d["bbox"][3] for d in c])) for c in big]
    groups = [[] for _ in anchors]
    for d in dets:
        groups[next((i for i, a in enumerate(anchors) if a >= d["bbox"][3] - tol), len(anchors) - 1)].append(d)
    rows = []
    for r, members in enumerate(g for g in groups if g):
        for d in members:
            d["row"] = r
        rows.append({"row": r, "y0": int(min(d["bbox"][1] for d in members)), "y1": int(max(d["bbox"][3] for d in members)),
                     "base_y": int(np.median([d["bbox"][3] for d in members])),
                     "median_height": float(np.median([d["bbox"][3] - d["bbox"][1] for d in members])), "count": len(members)})
    return rows


def height_cm(y, rows, size, assumptions):
    top, bottom = (rows[0]["y0"], rows[-1]["y1"]) if rows else (0, size[1])
    a = assumptions
    return a["shelf_top_cm"] + (np.asarray(y, float) - top) * (a["shelf_bottom_cm"] - a["shelf_top_cm"]) / max(1, bottom - top)


def row_name(r: int, n: int) -> str:
    return "Top shelf" if r == 0 else "Bottom shelf" if r == n - 1 else f"Shelf {r + 1} of {n}"


def build_context(layout: dict, product: dict, labels: np.ndarray, product_mask: np.ndarray) -> dict:
    dets = {d["id"]: d for d in layout["detections"]}
    rows = layout["rows"]
    overlap = np.bincount(labels[product_mask].ravel(), minlength=max(dets, default=0) + 1)
    product_det = next((i for i in np.argsort(overlap)[::-1] if i and overlap[i] >= 0.5 * min(
        product_mask.sum(), (labels == i).sum())), None)
    bbox = product["bbox"]
    product_row = (dets[int(product_det)]["row"] if product_det is not None else
                   min(range(len(rows)), key=lambda r: abs(rows[r]["base_y"] - bbox[3])) if rows else 0)
    return {"size": tuple(layout["source_size"]), "dets": dets, "rows": rows, "product_bbox": bbox,
            "product_det": None if product_det is None else int(product_det), "product_row": product_row}


def _scale(ctx, row: int) -> float:
    rows = ctx["rows"]
    if not rows:
        return 1.0
    return rows[row]["median_height"] / rows[ctx["product_row"]]["median_height"]


def _rect(ctx, cx: float, base: float, s: float):
    x0, y0, x1, y1 = ctx["product_bbox"]
    w, h = (x1 - x0) * s, (y1 - y0) * s
    return [round(cx - w / 2), round(base - h), round(cx + w / 2), round(base)]


def make_slot(ctx, kind: str, target=None, x=None, row=None, label=None) -> dict:
    n = len(ctx["rows"])
    W = ctx["size"][0]
    if kind == "current":
        r = ctx["product_row"]
        return {"id": "current", "label": label or f"Current position ({row_name(r, n).lower()})", "kind": "current",
                "target": None, "x": None, "row": r, "rect": list(ctx["product_bbox"])}
    if kind == "swap":
        if target not in ctx["dets"] or target == ctx["product_det"]:
            raise ValueError("Swap target must be another detected product")
        d = ctx["dets"][target]
        x0, y0, x1, y1 = d["bbox"]
        rect = _rect(ctx, (x0 + x1) / 2, y1, _scale(ctx, d["row"]))
        return {"id": f"swap-{target}", "label": label or f"{row_name(d['row'], n)} · swap with product #{target}",
                "kind": "swap", "target": target, "x": None, "row": d["row"], "rect": rect}
    if kind == "place":
        if not n or not isinstance(row, int) or not 0 <= row < n or not isinstance(x, (int, float)) or not 0 <= x < W:
            raise ValueError("Place slot needs a valid row and x inside the image")
        rect = _rect(ctx, float(x), ctx["rows"][row]["base_y"], _scale(ctx, row))
        return {"id": f"place-{row}-{round(x)}", "label": label or f"{row_name(row, n)} · gap at x={round(x)}",
                "kind": "place", "target": None, "x": round(float(x), 1), "row": row, "rect": rect}
    raise ValueError("Slot kind must be current, swap or place")


def propose_slots(ctx, n: int = 7) -> list[dict]:
    rows, W = ctx["rows"], ctx["size"][0]
    slots = [make_slot(ctx, "current")]
    if not rows:
        return slots
    last, pr = len(rows) - 1, ctx["product_row"]
    mid = last // 2 if last // 2 != pr else max(0, pr - 1)
    by_row = {}
    for d in ctx["dets"].values():
        if d["id"] != ctx["product_det"] and _iou(d["bbox"], ctx["product_bbox"]) < 0.2:
            by_row.setdefault(d["row"], []).append(d)
    picks = {"centre": lambda ds: min(ds, key=lambda d: abs((d["bbox"][0] + d["bbox"][2]) / 2 - W / 2)),
             "left end": lambda ds: min(ds, key=lambda d: d["bbox"][0]),
             "right end": lambda ds: max(ds, key=lambda d: d["bbox"][2])}
    order = [(0, "centre"), (mid, "centre"), (last, "centre"), (pr, "left end"), (pr, "right end"),
             (mid, "left end"), (mid, "right end"), (0, "left end"), (last, "right end")]
    seen = set()
    for r, where in order:
        if len(slots) >= n or r not in by_row:
            continue
        d = picks[where](by_row[r])
        if d["id"] in seen:
            continue
        seen.add(d["id"])
        slots.append(make_slot(ctx, "swap", d["id"], label=f"{row_name(r, len(rows))} · {where} (swap with #{d['id']})"))
    return slots


def slot_for_click(ctx, labels: np.ndarray, product_mask: np.ndarray, x: float, y: float) -> dict:
    W, H = ctx["size"]
    if not (0 <= x < W and 0 <= y < H):
        raise ValueError("Click must be inside the image")
    xi, yi = int(x), int(y)
    if product_mask[yi, xi]:
        return make_slot(ctx, "current")
    t = int(labels[yi, xi])
    if t and t != ctx["product_det"]:
        return make_slot(ctx, "swap", t)
    rows = ctx["rows"]
    if not rows:
        raise ValueError("No shelf rows detected to place on")
    row = next((r["row"] for r in rows if r["y0"] <= y <= r["y1"]), None)
    if row is None:
        row = min(rows, key=lambda r: abs(r["base_y"] - y))["row"]
    return make_slot(ctx, "place", x=x, row=row)


def _iou(a, b) -> float:
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(0, min(a[3], b[3]) - max(a[1], b[1]))
    return ix / ((a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix + 1e-9)


def fill_holes(img: np.ndarray, hole: np.ndarray) -> np.ndarray:
    """Pull-push fill of hole pixels from surrounding known pixels (float HxWxC)."""
    known = ~hole
    if known.all() or not known.any():
        return img
    h, w = known.shape
    if min(h, w) < 2:
        return np.where(known[..., None], img, img[known].mean(0))
    ph, pw = h % 2, w % 2
    im = np.pad(img, ((0, ph), (0, pw), (0, 0)), mode="edge")
    k = np.pad(known, ((0, ph), (0, pw))).astype(np.float32)
    im4 = im.reshape(im.shape[0] // 2, 2, im.shape[1] // 2, 2, -1)
    k4 = k.reshape(k.shape[0] // 2, 2, k.shape[1] // 2, 2)
    ws = k4.sum((1, 3))
    coarse = (im4 * k4[..., None]).sum((1, 3)) / np.maximum(ws, 1e-6)[..., None]
    coarse = fill_holes(coarse, ws == 0)
    up = np.repeat(np.repeat(coarse, 2, 0), 2, 1)[:h, :w]
    return np.where(known[..., None], img, up)


def _cutout(src: np.ndarray, mask: np.ndarray) -> Image.Image:
    ys, xs = np.nonzero(mask)
    y0, y1, x0, x1 = ys.min(), ys.max() + 1, xs.min(), xs.max() + 1
    rgba = np.dstack([src[y0:y1, x0:x1], mask[y0:y1, x0:x1].astype(np.uint8) * 255])
    return Image.fromarray(rgba, "RGBA")


def _paste(scene: np.ndarray, labels: np.ndarray, obj: Image.Image, cx: float, base: float, height: float, label: int):
    s = max(1.0, height) / obj.height
    obj = obj.resize((max(1, round(obj.width * s)), max(1, round(obj.height * s))), Image.LANCZOS)
    x0, y0 = round(cx - obj.width / 2), round(base - obj.height)
    H, W = labels.shape
    ox0, oy0, ox1, oy1 = max(0, -x0), max(0, -y0), min(obj.width, W - x0), min(obj.height, H - y0)
    if ox0 >= ox1 or oy0 >= oy1:
        return
    arr = np.asarray(obj, np.float32)[oy0:oy1, ox0:ox1]
    a = arr[..., 3:] / 255
    region = (slice(y0 + oy0, y0 + oy1), slice(x0 + ox0, x0 + ox1))
    scene[region] = arr[..., :3] * a + scene[region] * (1 - a)
    labels[region][a[..., 0] >= 0.5] = label


def render_scene(src: np.ndarray, labels: np.ndarray, product_mask: np.ndarray, ctx, slot: dict):
    """Return (scene uint8 HxWx3, scene labels int32, product label). The product label is max id + 1."""
    P = int(labels.max()) + 1
    out_labels = labels.astype(np.int32).copy()
    if ctx["product_det"] is not None:
        out_labels[out_labels == ctx["product_det"]] = 0
    if slot["kind"] == "current":
        out_labels[product_mask] = P
        return src.copy(), out_labels, P
    target = slot["target"] if slot["kind"] == "swap" else None
    hole = product_mask | (labels == target) if target else product_mask.copy()
    scene = src.astype(np.float32)
    filled = fill_holes(scene, hole)
    smooth = np.asarray(Image.fromarray(filled.round().astype(np.uint8)).filter(ImageFilter.GaussianBlur(2)), np.float32)
    scene = np.where(hole[..., None], smooth, scene)
    out_labels[hole] = 0
    x0, y0, x1, y1 = ctx["product_bbox"]
    product = _cutout(src, product_mask)
    if target:
        t = ctx["dets"][target]
        tx0, ty0, tx1, ty1 = t["bbox"]
        s = _scale(ctx, t["row"])
        _paste(scene, out_labels, _cutout(src, labels == target), (x0 + x1) / 2, y1, (ty1 - ty0) / s, target)
        _paste(scene, out_labels, product, (tx0 + tx1) / 2, ty1, (y1 - y0) * s, P)
    else:
        r = slot["row"]
        _paste(scene, out_labels, product, slot["x"], ctx["rows"][r]["base_y"], (y1 - y0) * _scale(ctx, r), P)
    return scene.round().clip(0, 255).astype(np.uint8), out_labels, P


def distance_blur(img: Image.Image, distance_m: float, photo_distance_m: float) -> Image.Image:
    """Viewing from further than the camera resolves fewer pixels per object: downsample then upsample."""
    r = distance_m / photo_distance_m
    if r <= 1.05:
        return img
    small = img.resize((max(8, round(img.width / r)), max(8, round(img.height / r))), Image.BOX)
    return small.resize(img.size, Image.BICUBIC)


def position_prior(size, rows, persona: dict, assumptions: dict):
    W, H = size
    m = MISSIONS[persona["mission"]]
    d_cm = persona["distance_m"] * 100
    centre = persona["eye_height_cm"] - d_cm * TAN15 - m["band_offset_cm"]
    sigma = max(10.0, d_cm * TAN15)
    e = np.exp(-0.5 * ((height_cm(np.arange(H) + 0.5, rows, size, assumptions) - centre) / sigma) ** 2)
    c = np.exp(-0.5 * ((np.arange(W) + 0.5 - W / 2) / (m["centre_sigma"] * W)) ** 2)
    return E_FLOOR + (1 - E_FLOOR) * e, C_FLOOR + (1 - C_FLOOR) * c


def score_scene(log_density: np.ndarray, labels: np.ndarray, product_label: int, rows, persona: dict,
                assumptions: dict):
    H, W = labels.shape
    s = np.exp(log_density.astype(np.float64) - log_density.max())
    s /= s.sum()
    e, c = position_prior((W, H), rows, persona, assumptions)
    a = MISSIONS[persona["mission"]]["saliency_exp"]
    g = TIME_PRESSURE[persona["time_pressure"]]["gamma"]
    att = (s ** a * e[:, None] * c[None, :]) ** g
    att /= att.sum()
    product = labels == product_label
    sal, final = float(s[product].sum()), float(att[product].sum())
    masses = np.bincount(labels.ravel(), weights=att.ravel(), minlength=product_label + 1)
    present = np.unique(labels)
    present = present[present > 0]
    others = masses[present[present != product_label]]
    return {"saliency_share": round(sal, 6), "position_factor": round(final / sal, 4) if sal > 0 else 0.0,
            "final_share": round(final, 6), "rank": int((others > masses[product_label]).sum()) + 1,
            "n_products": int(len(present))}, att, s


def colorize(m: np.ndarray, max_alpha: int = 200) -> Image.Image:
    v = np.clip(m / max(float(np.quantile(m, 0.995)), 1e-12), 0, 1)
    idx = v * (len(STOPS) - 1)
    lo = np.floor(idx).astype(int).clip(0, len(STOPS) - 2)
    t = (idx - lo)[..., None]
    rgb = STOPS[lo] * (1 - t) + STOPS[lo + 1] * t
    alpha = (v ** 0.6 * max_alpha)[..., None]
    return Image.fromarray(np.concatenate([rgb, alpha], -1).round().astype(np.uint8), "RGBA")


def summarise(slots: list[dict], personas: list[dict]) -> dict:
    """slots: [{label, kind, per_persona: [{final_share, saliency_share, position_factor, rank, n_products}]}]."""
    for s in slots:
        pp = s["per_persona"]
        s["mean_final_share"] = round(float(np.mean([p["final_share"] for p in pp])), 6)
        s["mean_rank"] = round(float(np.mean([p["rank"] for p in pp])), 2)
    ranking = sorted(range(len(slots)), key=lambda i: -slots[i]["mean_final_share"])
    b = ranking[0]
    best = slots[b]
    cur_i = next((i for i, s in enumerate(slots) if s["kind"] == "current"), b)
    cur = slots[cur_i]
    mean = lambda s, k: float(np.mean([p[k] for p in s["per_persona"]]))
    n_prod = best["per_persona"][0]["n_products"]
    reasons = []
    if b == cur_i:
        nxt = slots[ranking[1]] if len(ranking) > 1 else None
        reasons.append(f"The current position already scores highest: {best['mean_final_share']:.1%} mean modelled "
                       f"attention share across {len(personas)} personas"
                       + (f" (next best: {nxt['label']}, {nxt['mean_final_share']:.1%})." if nxt else "."))
    else:
        d = best["mean_final_share"] - cur["mean_final_share"]
        ratio = best["mean_final_share"] / cur["mean_final_share"] if cur["mean_final_share"] > 0 else float("inf")
        reasons.append(f"{best['label']}: {best['mean_final_share']:.1%} mean modelled attention share vs "
                       f"{cur['mean_final_share']:.1%} at the current position ({d * 100:+.1f} pp, {ratio:.1f}×) "
                       f"across {len(personas)} personas.")
        reasons.append(f"Mean rank among {n_prod} detected products: #{best['mean_rank']:g} vs #{cur['mean_rank']:g} now.")
        reasons.append(f"Image saliency alone gives {mean(best, 'saliency_share'):.1%} vs {mean(cur, 'saliency_share'):.1%}; "
                       f"persona position priors multiply that by {mean(best, 'position_factor'):.2f} vs "
                       f"{mean(cur, 'position_factor'):.2f}.")
    winners = [max(range(len(slots)), key=lambda i: slots[i]["per_persona"][p]["final_share"]) for p in range(len(personas))]
    disagree = [p for p, w in enumerate(winners) if w != b]
    if not disagree:
        reasons.append("Best slot for every persona tested.")
    for p in disagree:
        w = slots[winners[p]]
        reasons.append(f"{personas[p]['name']} would see it most at {w['label']} "
                       f"({w['per_persona'][p]['final_share']:.1%} vs {best['per_persona'][p]['final_share']:.1%} here).")
    weakest = min(range(len(personas)), key=lambda p: best["per_persona"][p]["final_share"])
    reasons.append(f"Weakest persona at this slot: {personas[weakest]['name']} "
                   f"({best['per_persona'][weakest]['final_share']:.1%}).")
    return {"ranking": ranking, "recommendation": {"slot": b, "reasons": reasons}}


def load_inputs(job: Path, pid: str):
    """Read layout + product for a job. Returns (src uint8, labels int32, product mask bool, ctx)."""
    layout = json.loads((job / "placement" / "layout" / "layout.json").read_text())
    product = json.loads((job / "products" / pid / "product.json").read_text())
    with Image.open(job / "source.png") as img:
        src = np.asarray(img.convert("RGB"))
    labels = np.asarray(Image.open(job / "placement" / "layout" / "labels.png")).astype(np.int32)
    mask = np.asarray(Image.open(job / "products" / pid / "mask.png").convert("L")) > 127
    return src, labels, mask, build_context(layout, product, labels, mask)


def packaging_path(job: Path, pid: str, packaging):
    if packaging is None:
        return None
    if not isinstance(packaging, dict):
        raise ValueError("packaging must be {vid, concept} or null for the original")
    vid, concept = packaging.get("vid"), packaging.get("concept")
    if not isinstance(vid, str) or not re.fullmatch(r"[0-9a-f]{8}", vid):
        raise ValueError("Invalid packaging variant set")
    if type(concept) is not int or not 1 <= concept <= 4:
        raise ValueError("Packaging concept must be 1-4")
    path = job / "products" / pid / "variants" / vid / f"shelf_{concept}.png"
    if not path.is_file():
        raise ValueError("Packaging concept is not ready for this product")
    return path


def execute_run(job: Path, rid: str, predict, commit=lambda: None) -> dict:
    """Render every slot, score slot x persona saliency maps from predict(calls) (an ordered iterator of
    log-density arrays for (job_id, rid, slot, distance_m, photo_distance_m) tuples) and write results."""
    run = job / "placement" / "runs" / rid
    req = json.loads((run / "request.json").read_text())
    slots, personas, assumptions = req["slots"], req["personas"], req["assumptions"]
    total = len(slots) * len(personas)
    status = {"state": "running", "stage": "rendering scenes", "done_count": 0, "total": total, "error": None,
              "timings": {}}
    started = time.perf_counter()

    def save():
        (run / "status.json").write_text(json.dumps(status))
        commit()

    try:
        save()
        src, labels, mask, ctx = load_inputs(job, req["pid"])
        concept = packaging_path(job, req["pid"], req.get("packaging"))
        if concept:
            with Image.open(concept) as img:
                if img.size != ctx["size"]:
                    raise ValueError("Packaging concept must match the source image size")
                src = np.where(mask[..., None], np.asarray(img.convert("RGB")), src)
        scenes = []
        for i, slot in enumerate(slots):
            scene, lab, P = render_scene(src, labels, mask, ctx, slot)
            Image.fromarray(scene).save(run / f"scene_{i}.png")
            scenes.append((lab, P))
        status["timings"]["render_s"] = round(time.perf_counter() - started, 2)
        status["stage"] = "predicting attention (DeepGaze IIE on GPU)"
        save()
        calls = [(job.name, rid, i, p["distance_m"], assumptions["photo_distance_m"])
                 for i in range(len(slots)) for p in personas]
        sal_started = time.perf_counter()
        out = [{**s, "scene": f"scene_{i}.png", "per_persona": [None] * len(personas)} for i, s in enumerate(slots)]
        for k, log_density in enumerate(predict(calls)):
            i, p = divmod(k, len(personas))
            lab, P = scenes[i]
            score, att, sal = score_scene(np.asarray(log_density), lab, P, ctx["rows"], personas[p], assumptions)
            colorize(att).save(run / f"heat_{i}_{p}.png")
            colorize(sal).save(run / f"sal_{i}_{p}.png")
            out[i]["per_persona"][p] = {"persona": p, **score, "heatmap": f"heat_{i}_{p}.png",
                                        "saliency_heatmap": f"sal_{i}_{p}.png"}
            status["done_count"] = k + 1
            save()
        if status["done_count"] != total:
            raise RuntimeError(f"Saliency returned {status['done_count']} of {total} maps")
        status["timings"]["saliency_wall_s"] = round(time.perf_counter() - sal_started, 2)
        results = {"slots": out, **summarise(out, personas), "personas": personas, "assumptions": assumptions,
                   "formula": FORMULA, "disclaimer": DISCLAIMER, "model": req.get("model", {}),
                   "packaging": req.get("packaging")}
        status["timings"]["total_s"] = round(time.perf_counter() - started, 2)
        (run / "results.json").write_text(json.dumps(results, allow_nan=False))
        status.update(state="done", stage="done")
        save()
        return results
    except Exception as exc:
        status.update(state="failed", error=f"Placement test failed: {exc}")
        save()
        raise


LAYOUT_PARAMS = dict(
    min_iou=0.80,
    min_area_frac=0.0008,
    max_area_frac=0.05,
    max_w_frac=0.25,
    max_h_frac=0.22,
    min_side=8,
    max_aspect=5.0,
    min_fill=0.55,
    max_border_frac=0.25,
    dup_iou=0.6,
    contain=0.6,
    parent_margin=0.03,
    min_keep_frac=0.6,
)


def _components(mask):
    h, w = mask.shape
    lab = np.where(mask, np.arange(h * w, dtype=np.int64).reshape(h, w), h * w)
    big = h * w
    while True:
        prev = lab
        p = np.pad(lab, 1, constant_values=big)
        m = np.minimum.reduce([lab, p[:-2, 1:-1], p[2:, 1:-1], p[1:-1, :-2], p[1:-1, 2:]])
        m = np.where(mask, m, big)
        flat = np.append(m.ravel(), big)
        for _ in range(4):
            flat[:-1] = flat[flat[:-1]]
        lab = flat[:-1].reshape(h, w)
        if np.array_equal(lab, prev):
            return lab


def _clean(full):
    x0, y0, x1, y1 = _bbox(full)
    out = np.zeros_like(full)
    out[y0:y1, x0:x1] = _clean_crop(full[y0:y1, x0:x1])
    return out


def _clean_crop(mask):
    lab = _components(mask)
    ids, counts = np.unique(lab[mask], return_counts=True)
    if not len(ids):
        return mask
    mask = lab == ids[counts.argmax()]
    bg = np.pad(~mask, 1, constant_values=True)
    outside = _components(bg)
    return ~(outside == outside[0, 0])[1:-1, 1:-1]


def _bbox(mask):
    ys, xs = np.nonzero(mask)
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def _geometry_ok(mask, h, w, p):
    area = int(mask.sum())
    if area < p["min_area_frac"] * h * w or area > p["max_area_frac"] * h * w:
        return None
    x0, y0, x1, y1 = _bbox(mask)
    bw, bh = x1 - x0, y1 - y0
    if bw > p["max_w_frac"] * w or bh > p["max_h_frac"] * h or min(bw, bh) < p["min_side"]:
        return None
    if max(bw / bh, bh / bw) > p["max_aspect"] or area / (bw * bh) < p["min_fill"]:
        return None
    border = mask[0].sum() + mask[-1].sum() + mask[:, 0].sum() + mask[:, -1].sum()
    if border > p["max_border_frac"] * 2 * (bw + bh):
        return None
    return x0, y0, x1, y1


def _overlap(a, b):
    ax0, ay0, ax1, ay1 = a["bbox"]
    bx0, by0, bx1, by1 = b["bbox"]
    x0, y0, x1, y1 = max(ax0, bx0), max(ay0, by0), min(ax1, bx1), min(ay1, by1)
    if x0 >= x1 or y0 >= y1:
        return 0
    ca = a["crop"][y0 - ay0:y1 - ay0, x0 - ax0:x1 - ax0]
    cb = b["crop"][y0 - by0:y1 - by0, x0 - bx0:x1 - bx0]
    return int((ca & cb).sum())


def masks_to_detections(masks, scores, **params):
    p = {**LAYOUT_PARAMS, **params}
    masks = np.asarray(masks, bool)
    scores = np.asarray(scores, np.float32)
    h, w = masks.shape[-2:]
    masks = masks.reshape(-1, h, w)
    scores = scores.reshape(-1)
    cands = []
    for i in np.argsort(-scores):
        area = masks[i].sum()
        if scores[i] < p["min_iou"] or not p["min_area_frac"] * h * w <= area <= 1.5 * p["max_area_frac"] * h * w:
            continue
        m = _clean(masks[i])
        box = _geometry_ok(m, h, w, p)
        if box is None:
            continue
        x0, y0, x1, y1 = box
        cands.append({"bbox": box, "crop": m[y0:y1, x0:x1], "area": int(m.sum()), "score": float(scores[i])})
    kept = []
    for c in cands:
        drop = False
        for j, k in enumerate(kept):
            inter = _overlap(c, k)
            if not inter:
                continue
            if inter / k["area"] > p["contain"] and c["area"] > k["area"] and c["score"] >= k["score"] - p["parent_margin"]:
                kept[j] = None
            elif inter / (c["area"] + k["area"] - inter) > p["dup_iou"] or inter / c["area"] > p["contain"]:
                drop = True
                break
        kept = [k for k in kept if k is not None]
        if not drop:
            kept.append(c)
    kept.sort(key=lambda k: -k["score"])
    labels = np.zeros((h, w), np.int32)
    dets = []
    for k in kept:
        x0, y0, x1, y1 = k["bbox"]
        free = k["crop"] & (labels[y0:y1, x0:x1] == 0)
        if free.sum() < p["min_keep_frac"] * k["area"]:
            continue
        i = len(dets) + 1
        labels[y0:y1, x0:x1][free] = i
        fx0, fy0, fx1, fy1 = _bbox(free)
        dets.append({"id": i, "bbox": [x0 + fx0, y0 + fy0, x0 + fx1, y0 + fy1], "score": round(k["score"], 4)})
    return labels, dets


SALIENCY_PATH = re.compile(r"^(source\.png|products/[0-9a-f]{8}/variants/[0-9a-f]{8}/shelf_[1-4]\.png|"
                           r"placement/runs/[0-9a-f]{8}/scene_[0-7]\.png)$")


def execute_attention(job: Path, pid: str, vid: str, predict, commit=lambda: None) -> dict:
    """Score the original shelf and every generated concept (shelf_K.png) with saliency inside the product mask."""
    out = job / "placement" / "packaging" / f"{pid}-{vid}"
    out.mkdir(parents=True, exist_ok=True)
    vdir = job / "products" / pid / "variants" / vid
    shelves = sorted(vdir.glob("shelf_[1-4].png"))
    names = [("original", "Original pack", "source.png")] + [
        (p.stem.split("_")[1], f"Concept {p.stem.split('_')[1]}", f"products/{pid}/variants/{vid}/{p.name}") for p in shelves]
    status = {"state": "running", "done_count": 0, "total": len(names), "error": None}

    def save():
        (out / "status.json").write_text(json.dumps(status))
        commit()

    try:
        if not shelves:
            raise ValueError("This variant set has no shelf images yet")
        save()
        mask = np.asarray(Image.open(job / "products" / pid / "mask.png").convert("L")) > 127
        if (job / "placement" / "layout" / "layout.json").is_file():
            src, labels, mask, ctx = load_inputs(job, pid)
            _, labels, P = render_scene(src, labels, mask, ctx, make_slot(ctx, "current"))
        else:
            labels, P = mask.astype(np.int32), 1
        rows = []
        for k, logd in enumerate(predict([(job.name, rel) for _, _, rel in names])):
            key, label, rel = names[k]
            s = np.exp(np.asarray(logd, np.float64) - np.max(logd))
            s /= s.sum()
            masses = np.bincount(labels.ravel(), weights=s.ravel(), minlength=P + 1)
            present = np.unique(labels)
            present = present[(present > 0) & (present != P)]
            colorize(s).save(out / f"sal_{key}.png")
            rows.append({"key": key, "label": label, "image": rel, "heatmap": f"sal_{key}.png",
                         "saliency_share": round(float(s[mask].sum()), 6),
                         "rank": int((masses[present] > masses[P]).sum()) + 1, "n_products": int(len(present)) + 1})
            status["done_count"] = k + 1
            save()
        base = rows[0]["saliency_share"]
        for r in rows:
            r["delta_pp"] = round((r["saliency_share"] - base) * 100, 2)
            r["ratio"] = round(r["saliency_share"] / base, 3) if base > 0 else None
        best = max(rows, key=lambda r: r["saliency_share"])
        reasons = [f"{best['label']} draws {best['saliency_share']:.1%} of predicted attention on the shelf vs "
                   f"{base:.1%} for the original ({best['delta_pp']:+.1f} pp)" + (
                       f", rank #{best['rank']} of {best['n_products']} products." if best is not rows[0] else ".")]
        if best is rows[0]:
            reasons = [f"The original pack draws the most predicted attention ({base:.1%}); no concept beats it."]
        reasons.append("Same photo, viewpoint and position for every pack, so differences come from the pack design. "
                       "Pure DeepGaze IIE saliency (no persona priors).")
        results = {"rows": rows, "best": best["key"], "reasons": reasons, "disclaimer": DISCLAIMER}
        (out / "results.json").write_text(json.dumps(results, allow_nan=False))
        status["state"] = "done"
        save()
        return results
    except Exception as exc:
        status.update(state="failed", error=f"Attention scoring failed: {exc}")
        save()
        raise
