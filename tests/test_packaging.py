import numpy as np
import pytest
from PIL import Image, ImageFilter

from shelfproof.packaging import (
    BANANA_SIZES, MODELS, banana_size, build_variant_prompts, composite_into_shelf, edit_inputs, facing_aspect,
    mask_bbox, pad_bbox, paste_masked, sunburst_size, trim_background, validate_brief,
)

BRIEF = {"product_name": "Crunchy Oats", "category": "cereal", "target_audience": "health-conscious 25-34 urban",
         "price_tier": "premium", "keep": "logo"}


def test_prompts_count_distinct_and_keep_brand():
    prompts = build_variant_prompts(BRIEF)
    assert len(prompts) == 3 and len(set(prompts)) == 3
    assert all('"Crunchy Oats"' in p and "health-conscious" in p and "straight-on front view" in p
               and "transparent background" in p and "Must keep: logo" in p for p in prompts)
    assert "minimal premium" in prompts[0]
    assert len(build_variant_prompts({**BRIEF, "count": 4})) == 4
    assert len(build_variant_prompts({**BRIEF, "count": 1})) == 1
    banana = build_variant_prompts({**BRIEF, "model": "nano-banana-pro"}, extra_views=2)
    assert all("light grey" in p and "transparent" not in p and "Image 4 shows how" in p for p in banana)


@pytest.mark.parametrize("bad", [
    {}, {"product_name": ""}, {"product_name": "x" * 81}, {"product_name": "A", "price_tier": "luxury"},
    {"product_name": "A", "count": 5}, {"product_name": "A", "count": 0}, {"product_name": "A", "count": True},
    {"product_name": "A", "notes": 3}, "not a dict", {"product_name": "A", "model": "dall-e"},
    {"product_name": "A", "quality": "ultra"}, {"product_name": "A", "model": "openai:gpt-image@2.5-sunburst"},
])
def test_brief_validation_rejects(bad):
    with pytest.raises(ValueError):
        validate_brief(bad)


def test_brief_defaults_and_sanitises():
    b = validate_brief({"product_name": " Oats\n\x00 ", "price_tier": "VALUE"})
    assert b["product_name"] == "Oats" and b["price_tier"] == "value" and b["count"] == 3
    assert b["model"] == "gpt-image-2.5-sunburst" and b["quality"] == "high"
    assert MODELS[validate_brief({"product_name": "A", "model": "nano-banana-pro"})["model"]] == "google:4@2"


def test_bbox_helpers():
    m = np.zeros((50, 40), bool)
    m[10:20, 5:15] = True
    assert mask_bbox(m) == (5, 10, 15, 20)
    assert pad_bbox((5, 10, 15, 20), 0.5, 18, 40) == (0, 5, 18, 25)
    with pytest.raises(ValueError):
        mask_bbox(np.zeros((3, 3), bool))


def test_sizes():
    assert sunburst_size(0.5, 1536) == (768, 1536)
    w, h = sunburst_size(4 / 3)
    assert w == 1024 and h % 16 == 0 and abs(h - 768) <= 16
    assert banana_size(0.67) == (848, 1264) and banana_size(1.0) == (1024, 1024) and banana_size(9) in BANANA_SIZES
    assert facing_aspect((0, 0, 80, 60)) == pytest.approx(80 / 60 / 2)
    assert facing_aspect((0, 0, 40, 60)) == pytest.approx(40 / 60)
    assert facing_aspect((0, 0, 10, 100)) == 0.5


def test_edit_inputs_crop_and_mask():
    shelf = Image.new("RGB", (686, 446), (10, 20, 30))
    mask = np.zeros((446, 686), np.uint8)
    mask[335:395, 205:285] = 255
    box, crop, m = edit_inputs(shelf, Image.fromarray(mask), (205, 335, 285, 395))
    assert box == (85, 245, 405, 446)
    assert crop.size == m.size and max(crop.size) == 1024 and crop.width % 16 == 0 and crop.height % 16 == 0
    a = np.asarray(m)
    assert set(np.unique(a)) <= {0, 255}
    sx, sy = crop.width / 320, crop.height / 201
    assert a[round(120 * sy), round(160 * sx)] == 255 and a[5, 5] == 0
    ys, xs = np.nonzero(a)
    assert xs.min() < 120 * sx and xs.max() > 200 * sx
    box2, _, _ = edit_inputs(shelf, Image.fromarray(mask), (0, 0, 40, 40))
    assert box2[:2] == (0, 0)


def test_paste_masked_only_changes_dilated_mask():
    rng = np.random.default_rng(1)
    shelf = Image.fromarray(rng.integers(0, 255, (150, 200, 3), dtype=np.uint8))
    mask = np.zeros((150, 200), np.uint8)
    mask[60:100, 80:120] = 255
    box = (40, 30, 160, 130)
    patch = Image.new("RGB", (960, 800), (0, 255, 0))
    out = paste_masked(shelf, Image.fromarray(mask), box, patch, dilate=2, feather=2)
    assert out.size == shelf.size
    changed = np.any(np.asarray(out) != np.asarray(shelf), axis=2)
    allowed = np.asarray(Image.fromarray(mask).filter(ImageFilter.MaxFilter(9))) > 0
    assert changed.any() and not (changed & ~allowed).any()
    assert tuple(np.asarray(out)[80, 100]) == (0, 255, 0)


def test_trim_background_uses_alpha():
    img = Image.new("RGBA", (100, 80), (0, 0, 0, 0))
    img.paste((255, 0, 0, 255), (20, 10, 60, 70))
    assert trim_background(img).size == (40, 60)


def test_composite_changes_only_dilated_mask_region():
    rng = np.random.default_rng(0)
    shelf = Image.fromarray(rng.integers(0, 255, (120, 160, 3), dtype=np.uint8))
    mask = np.zeros((120, 160), np.uint8)
    mask[40:90, 60:100] = 255
    bbox = mask_bbox(mask > 0)
    variant = Image.new("RGB", (512, 640), (230, 230, 230))
    variant.paste((255, 0, 0), (80, 60, 432, 600))
    out = composite_into_shelf(shelf, Image.fromarray(mask), bbox, variant, dilate=3, feather=3)
    assert out.size == shelf.size
    changed = np.any(np.asarray(out) != np.asarray(shelf), axis=2)
    allowed = np.asarray(Image.fromarray(mask).filter(ImageFilter.MaxFilter(13))) > 0
    assert changed.any() and not (changed & ~allowed).any()
    centre = np.asarray(out)[65, 80]
    assert centre[0] > 200 and centre[1] < 50


def test_wide_selection_is_filled_with_repeated_facings():
    shelf = Image.new("RGB", (200, 100), (0, 0, 255))
    mask = np.zeros((100, 200), np.uint8)
    mask[20:80, 20:180] = 255
    variant = Image.new("RGB", (300, 600), (255, 0, 0))
    out = np.asarray(composite_into_shelf(shelf, Image.fromarray(mask), mask_bbox(mask > 0), variant))
    row = out[50, 25:175]
    assert (row[:, 0] > 200).mean() > 0.9
