import numpy as np
import pytest
from PIL import Image

from shelfproof.placement import (
    PRESETS, build_context, colorize, distance_blur, fill_holes, group_rows, make_slot, propose_slots, render_scene,
    score_scene, slot_for_click, summarise, validate_assumptions, validate_persona,
)

W, H = 300, 240
COLOURS = [(200, 30, 30), (30, 200, 30), (30, 30, 200), (200, 200, 30), (200, 30, 200), (30, 200, 200)]


def shelf():
    """3 rows x 4 products; product (pid) is row 2, column 1 = detection 10."""
    src = np.full((H, W, 3), 90, np.uint8)
    labels = np.zeros((H, W), np.int32)
    dets = []
    for r, base in enumerate((70, 150, 230)):
        for c in range(4):
            i = r * 4 + c + 1
            x0, y0 = 20 + c * 70, base - 50
            src[y0:base, x0:x0 + 40] = COLOURS[(i - 1) % 6]
            labels[y0:base, x0:x0 + 40] = i
            dets.append({"id": i, "bbox": [x0, y0, x0 + 40, base], "score": 0.9})
    rows = group_rows(dets)
    layout = {"source_size": [W, H], "detections": dets, "rows": rows}
    mask = labels == 10
    product = {"bbox": [90, 180, 130, 230]}
    return src, labels, mask, build_context(layout, product, labels, mask)


def test_rows_and_context():
    _, _, _, ctx = shelf()
    assert [r["count"] for r in ctx["rows"]] == [4, 4, 4]
    assert [r["base_y"] for r in ctx["rows"]] == [70, 150, 230]
    assert ctx["product_det"] == 10 and ctx["product_row"] == 2


def test_proposals_are_unique_and_exclude_product():
    _, _, _, ctx = shelf()
    slots = propose_slots(ctx, n=7)
    assert slots[0]["kind"] == "current" and len(slots) == 7
    targets = [s["target"] for s in slots[1:]]
    assert len(set(targets)) == len(targets) and 10 not in targets
    assert {s["row"] for s in slots} == {0, 1, 2}
    with pytest.raises(ValueError):
        make_slot(ctx, "swap", 10)


def test_click_resolves_swap_place_current():
    src, labels, mask, ctx = shelf()
    assert slot_for_click(ctx, labels, mask, 30, 40)["target"] == 1
    assert slot_for_click(ctx, labels, mask, 100, 200)["kind"] == "current"
    gap = slot_for_click(ctx, labels, mask, 75, 120)
    assert gap["kind"] == "place" and gap["row"] == 1


def test_swap_moves_product_and_displaced():
    src, labels, mask, ctx = shelf()
    scene, out, P = render_scene(src, labels, mask, ctx, make_slot(ctx, "swap", 2))
    assert tuple(scene[45, 110]) == COLOURS[3]
    assert tuple(scene[205, 110]) == COLOURS[1]
    assert (out == P).sum() == mask.sum() and out[45, 110] == P and out[205, 110] == 2
    assert tuple(scene[45, 240]) == tuple(src[45, 240]) and (out == 1).sum() == (labels == 1).sum()


def test_fill_holes_uses_surroundings():
    img = np.zeros((20, 20, 3), np.float32)
    img[:] = (10, 20, 30)
    hole = np.zeros((20, 20), bool)
    hole[5:15, 5:15] = True
    img[hole] = 255
    out = fill_holes(img, hole)
    assert np.allclose(out[10, 10], (10, 20, 30))


def test_score_prior_prefers_eye_level_and_ranks():
    src, labels, mask, ctx = shelf()
    a = validate_assumptions({"shelf_top_cm": 190, "shelf_bottom_cm": 10})
    adult = validate_persona(PRESETS[1])
    flat = np.full((H, W), -np.log(H * W))
    _, low, P = render_scene(src, labels, mask, ctx, make_slot(ctx, "current"))
    _, mid, P2 = render_scene(src, labels, mask, ctx, make_slot(ctx, "swap", 6))
    lo, att, sal = score_scene(flat, low, P, ctx["rows"], adult, a)
    hi, _, _ = score_scene(flat, mid, P2, ctx["rows"], adult, a)
    assert np.isclose(att.sum(), 1) and np.isclose(lo["saliency_share"], mask.mean(), atol=1e-4)
    assert hi["final_share"] > lo["final_share"] and hi["rank"] < lo["rank"] and lo["n_products"] == 12
    child = validate_persona(PRESETS[0])
    c_lo, _, _ = score_scene(flat, low, P, ctx["rows"], child, a)
    assert c_lo["final_share"] > lo["final_share"]
    hot = flat.copy()
    hot[mask] += 5
    boosted, _, _ = score_scene(hot, low, P, ctx["rows"], adult, a)
    assert boosted["saliency_share"] > 0.5 and boosted["rank"] == 1


def test_validation_rejects_bad_inputs():
    for bad in [{**PRESETS[0], "eye_height_cm": 500}, {**PRESETS[0], "mission": "x"}, {**PRESETS[0], "name": ""},
                {**PRESETS[0], "distance_m": True}, "x"]:
        with pytest.raises(ValueError):
            validate_persona(bad)
    with pytest.raises(ValueError):
        validate_assumptions({"shelf_top_cm": 50, "shelf_bottom_cm": 40})


def test_summary_reasons_follow_numbers():
    pp = lambda *v: [{"final_share": x, "saliency_share": x / 2, "position_factor": 2.0, "rank": 3, "n_products": 9}
                     for x in v]
    slots = [{"label": "Current", "kind": "current", "per_persona": pp(0.02, 0.03)},
             {"label": "Top centre", "kind": "swap", "per_persona": pp(0.06, 0.01)},
             {"label": "Middle", "kind": "swap", "per_persona": pp(0.05, 0.05)}]
    out = summarise(slots, [{"name": "A"}, {"name": "B"}])
    assert out["ranking"] == [2, 1, 0] and out["recommendation"]["slot"] == 2
    text = " ".join(out["recommendation"]["reasons"])
    assert "5.0%" in text and "2.5%" in text and "+2.5 pp" in text and "A would see it most at Top centre" in text


def test_distance_blur_and_colorize_shapes():
    img = Image.fromarray(np.random.default_rng(0).integers(0, 255, (40, 60, 3), dtype=np.uint8))
    assert distance_blur(img, 1.0, 2.0) is img
    far = distance_blur(img, 4.0, 1.0)
    assert far.size == img.size and np.asarray(far).std() < np.asarray(img).std()
    rgba = colorize(np.random.default_rng(1).random((40, 60)))
    assert rgba.mode == "RGBA" and rgba.size == (60, 40)


def test_execute_run_end_to_end(tmp_path):
    import json

    from shelfproof.placement import ASSUMPTIONS, execute_run

    src, labels, mask, ctx = shelf()
    job = tmp_path / "abcdefabcdef"
    (job / "placement" / "layout").mkdir(parents=True)
    (job / "products" / "8e2750fd").mkdir(parents=True)
    Image.fromarray(src).save(job / "source.png")
    Image.fromarray(labels.astype(np.uint16)).save(job / "placement" / "layout" / "labels.png")
    Image.fromarray(mask.astype(np.uint8) * 255).save(job / "products" / "8e2750fd" / "mask.png")
    dets = [{**d, "bbox": list(d["bbox"])} for d in ctx["dets"].values()]
    (job / "placement" / "layout" / "layout.json").write_text(json.dumps(
        {"source_size": [W, H], "detections": dets, "rows": ctx["rows"]}))
    (job / "products" / "8e2750fd" / "product.json").write_text(json.dumps({"bbox": [90, 180, 130, 230]}))
    slots = [make_slot(ctx, "current"), make_slot(ctx, "swap", 6), make_slot(ctx, "swap", 1)]
    personas = [validate_persona(p) for p in PRESETS[:3]]
    run = job / "placement" / "runs" / "0123abcd"
    run.mkdir(parents=True)
    (run / "request.json").write_text(json.dumps(
        {"pid": "8e2750fd", "slots": slots, "personas": personas, "assumptions": ASSUMPTIONS}))
    flat = np.full((H, W), -np.log(H * W))
    calls = []
    res = execute_run(job, "0123abcd", lambda c: (calls.extend(c), (flat for _ in c))[1])
    assert len(calls) == 9 and calls[0][:3] == ("abcdefabcdef", "0123abcd", 0)
    assert json.loads((run / "status.json").read_text())["state"] == "done"
    assert all((run / f"heat_{i}_{p}.png").is_file() for i in range(3) for p in range(3))
    assert res["recommendation"]["slot"] == res["ranking"][0] and res["slots"][0]["per_persona"][2]["rank"] >= 1
    variant = job / "products" / "8e2750fd" / "variants" / "11112222"
    variant.mkdir(parents=True)
    redesigned = src.copy()
    redesigned[mask] = (255, 120, 0)
    redesigned[0, 0] = 255
    Image.fromarray(redesigned).save(variant / "shelf_1.png")
    request = json.loads((run / "request.json").read_text())
    request["packaging"] = {"vid": "11112222", "concept": 1}
    (run / "request.json").write_text(json.dumps(request))
    res = execute_run(job, "0123abcd", lambda c: (flat for _ in c))
    current = np.asarray(Image.open(run / "scene_0.png"))
    moved = np.asarray(Image.open(run / "scene_1.png"))
    assert tuple(current[205, 110]) == (255, 120, 0)
    assert np.array_equal(current[~mask], src[~mask])
    assert tuple(moved[125, 110]) == (255, 120, 0)
    assert tuple(moved[205, 110]) == tuple(src[125, 110])
    assert res["packaging"] == request["packaging"]


def test_stacked_and_short_items_join_the_shelf_they_sit_on():
    d = lambda i, x, y0, y1: {"id": i, "bbox": [x, y0, x + 30, y1], "score": 0.9}
    dets = [d(i, i * 40, 60, 100) for i in range(1, 6)] + [d(i, i * 40, 160, 200) for i in range(6, 11)]
    dets += [d(11, 0, 140, 170), d(12, 300, 30, 75)]
    rows = group_rows(dets)
    assert len(rows) == 2 and dets[10]["row"] == 1 and dets[11]["row"] == 0


def test_position_prior_is_floored():
    from shelfproof.placement import position_prior
    _, _, _, ctx = shelf()
    e, c = position_prior((W, H), ctx["rows"], validate_persona(PRESETS[0]), validate_assumptions({}))
    assert e.min() >= 0.3 and c.min() >= 0.5 and e.max() <= 1 and np.isclose(c.max(), 1, atol=1e-3)


def test_packaging_attention_compares_concepts(tmp_path):
    from shelfproof.placement import execute_attention
    src, labels, mask, _ = shelf()
    job = tmp_path / "abcdefabcdef"
    v = job / "products" / "8e2750fd" / "variants" / "11112222"
    v.mkdir(parents=True)
    Image.fromarray(mask.astype(np.uint8) * 255).save(job / "products" / "8e2750fd" / "mask.png")
    for k in (1, 2):
        Image.fromarray(src).save(v / f"shelf_{k}.png")
    flat = np.full((H, W), -np.log(H * W))
    hot = flat.copy()
    hot[mask] += 3
    res = execute_attention(job, "8e2750fd", "11112222", lambda calls: iter([flat, hot, flat]))
    assert [r["key"] for r in res["rows"]] == ["original", "1", "2"] and res["best"] == "1"
    assert res["rows"][1]["delta_pp"] > 0 and res["rows"][2]["delta_pp"] == 0 and "Concept 1" in res["reasons"][0]
