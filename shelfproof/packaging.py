import re
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter, ImageOps

PRICE_TIERS = ("value", "mid", "premium")
BRIEF_LIMITS = {
    "product_name": 80, "category": 60, "target_audience": 200, "price_tier": 10,
    "brand_tone": 100, "keep": 200, "avoid": 200, "notes": 500,
}
DIRECTIONS = {
    "minimal premium": "minimal premium: restrained palette, generous negative space, refined typography, subtle metallic or matte finish cues",
    "bold value": "bold value: high-contrast saturated colours, large confident brand name, clear benefit callout, strong shelf stand-out",
    "natural organic": "natural and organic: earthy tones, kraft or paper textures, hand-drawn ingredient illustration, calm honest feel",
    "playful": "playful: bright cheerful colours, rounded friendly shapes, a simple character or pattern, energetic but tidy layout",
}
TIER_ORDER = {
    "premium": ("minimal premium", "natural organic", "playful", "bold value"),
    "mid": ("natural organic", "minimal premium", "bold value", "playful"),
    "value": ("bold value", "playful", "natural organic", "minimal premium"),
}
MODELS = {"gpt-image-2.5-sunburst": "openai:gpt-image@2.5-sunburst", "nano-banana-pro": "google:4@2"}
DEFAULT_MODEL = "gpt-image-2.5-sunburst"
QUALITIES = ("auto", "max", "xhigh", "high", "medium", "low")
BANANA_SIZES = ((1024, 1024), (1264, 848), (848, 1264), (1200, 896), (896, 1200), (928, 1152), (1152, 928),
                (768, 1376), (1376, 768), (1548, 672))
PLACEMENT_PROMPT = (
    "Edit the first image, a photo of a real supermarket shelf. Replace the product package(s) in the masked area "
    "with the new package design shown in the second image, printed on the same physical pack. Keep the same number "
    "of facings, their positions, size, perspective, slight creases and curvature, shelf lighting, colour "
    "temperature, shadows, reflections, camera grain and sharpness, so it looks like an unedited photo of the shelf "
    "restocked with the new design. Do not change anything outside the mask: neighbouring products, price labels, "
    "shelf edges and background must stay identical."
)


def validate_brief(brief) -> dict:
    if not isinstance(brief, dict):
        raise ValueError("Brief must be a JSON object")
    out = {}
    for key, limit in BRIEF_LIMITS.items():
        value = brief.get(key) or ""
        if not isinstance(value, str):
            raise ValueError(f"{key} must be a string")
        value = re.sub(r"[\x00-\x1f\x7f]+", " ", value).strip()
        if len(value) > limit:
            raise ValueError(f"{key} must be at most {limit} characters")
        out[key] = value
    if not out["product_name"]:
        raise ValueError("product_name is required")
    out["price_tier"] = out["price_tier"].lower() or "mid"
    if out["price_tier"] not in PRICE_TIERS:
        raise ValueError(f"price_tier must be one of {', '.join(PRICE_TIERS)}")
    count = brief.get("count", 3)
    if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= 4:
        raise ValueError("count must be an integer from 1 to 4")
    out["count"] = count
    model = brief.get("model") or DEFAULT_MODEL
    if model not in MODELS:
        raise ValueError(f"model must be one of {', '.join(MODELS)}")
    quality = brief.get("quality") or "high"
    if quality not in QUALITIES:
        raise ValueError(f"quality must be one of {', '.join(QUALITIES)}")
    out["model"], out["quality"] = model, quality
    return out


def build_variant_prompts(brief, extra_views: int = 0) -> list[str]:
    b = validate_brief(brief)
    category = b["category"] or "packaged food"
    refs = ["Image 1 is the front of the current pack, cut out from a low-resolution shelf photo."]
    refs += [f"Image {i + 2} shows another side of the same pack." for i in range(extra_views)]
    refs.append(f"Image {extra_views + 2} shows how the pack is displayed on the shelf (it sits at the centre).")
    context = [f"Target shoppers: {b['target_audience']}." if b["target_audience"] else "",
               f"Price positioning: {b['price_tier']}.",
               f"Brand tone: {b['brand_tone']}." if b["brand_tone"] else "",
               f"Must keep: {b['keep']}." if b["keep"] else "",
               f"Must avoid: {b['avoid']}." if b["avoid"] else "",
               f"Designer notes: {b['notes']}." if b["notes"] else ""]
    context = " ".join(c for c in context if c)
    background = ("Isolate the pack on a fully transparent background with a small transparent margin: no floor, "
                  "no cast shadow, no backdrop, no props." if b["model"] == "gpt-image-2.5-sunburst" else
                  "Place the pack on a plain seamless light grey (#ebebeb) studio background with a small margin: "
                  "no props, no hands, no shelf.")
    return [
        f"Create a finished, print-ready front-of-pack redesign for a {category} product known as "
        f"\"{b['product_name']}\", presented as a professional commercial packshot. {' '.join(refs)} "
        "Identify the brand from the logo on the current pack and reproduce the brand name exactly as it is spelled "
        "there, crisp and legible, as the dominant brand block; do not invent a different brand. "
        "Keep the same physical format as the current pack (if it is a pouch or bag keep a pouch or bag, a box stays "
        "a box, a jar stays a jar) with the same proportions, material and finish. "
        "Lay out a credible front-of-pack like a real retail product designed by a top branding agency: brand block, "
        "flavour or variant name, two or three short key benefit callouts, a net weight statement, and appetising "
        f"product or ingredient imagery where appropriate for {category}. All text must be real, correctly spelled "
        "words in clean typography with clear hierarchy; no placeholder or gibberish text, no fake barcodes. "
        f"Creative direction: {DIRECTIONS[d]}. {context} "
        "The design must still clearly belong to this brand and fit its category on a supermarket shelf. "
        "Show exactly one complete pack, straight-on front view, upright and centred, filling about 90% of the "
        "frame height, with soft even studio lighting and realistic material highlights. " + background
        for d in TIER_ORDER[b["price_tier"]][: b["count"]]
    ]


def facing_aspect(bbox) -> float:
    w, h = bbox[2] - bbox[0], bbox[3] - bbox[1]
    aspect = w / h
    facings = max(1, round(aspect / 0.8)) if aspect > 1.2 else 1
    return min(2.0, max(0.5, aspect / facings))


def sunburst_size(aspect: float, longest: int = 1024) -> tuple[int, int]:
    w, h = (longest, longest / aspect) if aspect >= 1 else (longest * aspect, longest)
    return max(16, round(w / 16) * 16), max(16, round(h / 16) * 16)


def banana_size(aspect: float) -> tuple[int, int]:
    return min(BANANA_SIZES, key=lambda s: abs(np.log(s[0] / s[1] / aspect)))


def upscale(img: Image.Image, longest: int = 1024) -> Image.Image:
    scale = longest / max(img.size)
    return img.resize((max(1, round(img.width * scale)), max(1, round(img.height * scale))), Image.LANCZOS)


def edit_inputs(shelf: Image.Image, mask: Image.Image, bbox, frac: float = 1.5, dilate: int = 3, longest: int = 1024):
    box = pad_bbox(bbox, frac, shelf.width, shelf.height)
    size = sunburst_size((box[2] - box[0]) / (box[3] - box[1]), longest)
    crop = shelf.convert("RGB").crop(box).resize(size, Image.LANCZOS)
    m = mask.convert("L").crop(box).filter(ImageFilter.MaxFilter(2 * dilate + 1))
    m = m.resize(size, Image.BILINEAR).point(lambda v: 255 if v >= 128 else 0)
    return box, crop, m


def paste_masked(shelf: Image.Image, mask: Image.Image, box, patch: Image.Image,
                 dilate: int = 2, feather: int = 2) -> Image.Image:
    patch = patch.convert("RGB").resize((box[2] - box[0], box[3] - box[1]), Image.LANCZOS)
    local = mask.convert("L").crop(box)
    hard = local.filter(ImageFilter.MaxFilter(2 * (dilate + feather) + 1))
    alpha = local.filter(ImageFilter.MaxFilter(2 * dilate + 1)).filter(ImageFilter.GaussianBlur(feather))
    a = np.minimum(np.asarray(alpha), np.asarray(hard)).astype(np.float32)[..., None] / 255
    base = np.asarray(shelf.convert("RGB").crop(box)).astype(np.float32)
    top = np.asarray(patch).astype(np.float32)
    out = shelf.convert("RGB")
    out.paste(Image.fromarray((top * a + base * (1 - a)).round().astype(np.uint8)), box[:2])
    return out


def load_source(job: Path) -> Image.Image:
    if (job / "source.png").is_file():
        with Image.open(job / "source.png") as img:
            return img.convert("RGB")
    source = next((p for p in sorted(job.iterdir()) if p.name.startswith("input.")), None)
    if source is None:
        raise FileNotFoundError("Job has no source image")
    with Image.open(source) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def mask_bbox(mask: np.ndarray) -> tuple[int, int, int, int]:
    ys, xs = np.nonzero(mask)
    if not len(xs):
        raise ValueError("Empty mask")
    return int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1


def pad_bbox(bbox, frac: float, width: int, height: int) -> tuple[int, int, int, int]:
    x0, y0, x1, y1 = bbox
    px, py = round((x1 - x0) * frac), round((y1 - y0) * frac)
    return max(0, x0 - px), max(0, y0 - py), min(width, x1 + px), min(height, y1 + py)


def trim_background(img: Image.Image, threshold: int = 30) -> Image.Image:
    if img.mode == "RGBA" and img.getchannel("A").getextrema()[0] < 255:
        alpha = np.asarray(img.getchannel("A")) > 16
        return img.crop(mask_bbox(alpha)) if alpha.any() else img
    rgb = np.asarray(img.convert("RGB")).astype(np.int16)
    border = np.concatenate([rgb[0], rgb[-1], rgb[:, 0], rgb[:, -1]])
    diff = np.abs(rgb - np.median(border, axis=0)).max(axis=2) > threshold
    if diff.sum() < 0.05 * diff.size:
        return img
    return img.crop(mask_bbox(diff))


def composite_into_shelf(shelf: Image.Image, mask: Image.Image, bbox, variant: Image.Image,
                         dilate: int = 3, feather: int = 3) -> Image.Image:
    x0, y0, x1, y1 = bbox
    bw, bh = x1 - x0, y1 - y0
    product = trim_background(variant).convert("RGBA")
    facings = max(1, round(bw / (product.width * bh / product.height)))
    scale = min(bw / (facings * product.width), bh / product.height)
    product = product.resize((max(1, round(product.width * scale)), max(1, round(product.height * scale))), Image.LANCZOS)
    gap = (bw - facings * product.width) / facings
    m = dilate + feather
    rx0, ry0 = max(0, x0 - m), max(0, y0 - m)
    rx1, ry1 = min(shelf.width, x1 + m), min(shelf.height, y1 + m)
    region = (rx0, ry0, rx1, ry1)
    local = mask.convert("L").crop(region)
    hard = local.filter(ImageFilter.MaxFilter(2 * m + 1))
    alpha = local.filter(ImageFilter.MaxFilter(2 * dilate + 1)).filter(ImageFilter.GaussianBlur(feather))
    layer = Image.new("RGBA", local.size, (0, 0, 0, 0))
    for i in range(facings):
        layer.paste(product, (x0 - rx0 + round(gap / 2 + i * (product.width + gap)), y1 - ry0 - product.height))
    a = np.minimum(np.asarray(alpha), np.asarray(hard)).astype(np.float32) / 255
    a *= np.asarray(layer)[..., 3].astype(np.float32) / 255
    base = np.asarray(shelf.convert("RGB").crop(region)).astype(np.float32)
    top = np.asarray(layer)[..., :3].astype(np.float32)
    blended = (top * a[..., None] + base * (1 - a[..., None])).round().astype(np.uint8)
    out = shelf.convert("RGB")
    out.paste(Image.fromarray(blended), region[:2])
    return out
