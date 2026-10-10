"""Put our generated labels into realistic photo scenes (bottle or can on a bar counter, shelf, in a hand, in a cooler)
without letting an image model touch the label text, so the right answer stays known.

How (per item):
  1. OUR code bends the front label onto a cylinder (bottle or can curve, curved top and bottom edges, shading and
     a highlight stripe), tilts it a few degrees, and draws a rough bottle or can around it on a plain canvas.
  2. A Stability inpaint model on Amazon Bedrock repaints everything EXCEPT the label (mask: white = repaint, the
     label area is black = keep): the bottle, the hand, the counter, the room.
  3. OUR code pastes the label pixels back over the model's output (so the model's pixels never sit inside the label),
     checks the label area is identical to our warped label, then adds camera effects to the whole picture (slight
     blur, grain, vignette, sometimes a glare spot) and saves a JPEG.
  4. The app's reader reads the scene picture alone; a scene where the brand is not found at all is dropped.

The back label (where the warning is) is copied flat and unchanged: the warning wording and type-size checks keep
their exact answers, and the scene tests reading the front from a photo.

Source items: only practice (dev) synthetic items, never held-out ones. Model outputs are cached in out/scenes_raw/
so a re-run does not pay again. Output: data/scenes/<id>__scene0/ (item.json in the data/synthetic schema),
data/scenes/_report.json (calls, checks, drops) and data/scenes/_contact_sheet.jpg.

Usage: python tools/make_scenes.py [--count 54] [--max-calls 70] [--only syn_spirits_00_none] [--no-model]
"""

import argparse
import base64
import hashlib
import io
import json
import math
import random
import re
import shutil
import sys
import time
from difflib import SequenceMatcher
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "scenes"
RAW = ROOT / "out" / "scenes_raw"
MODEL = "us.stability.stable-image-inpaint-v1:0"
HARD = False   # --final: harder photos (glare more often, a coloured light, never a straight-on shot)
PRICE_LOW, PRICE_HIGH = 0.04, 0.08    # USD per inpaint image; Bedrock's price list does not show this model, so a range
W, H = 1536, 2048

FRONT_DEFECTS = {"abv_wrong", "proof_wrong", "net_wrong", "class_wrong", "brand_extra_word", "net_metric_only"}
CLEAN_DEFECTS = {"none", "brand_case_only"}
QUOTA = {"clean": 6, "front": 8, "warning": 4}   # per product type

CONTAINER = {
    "spirits": [("bottle", "a glass whiskey bottle with amber whiskey inside", (120, 70, 30)),
                ("bottle", "a clear glass gin bottle", (170, 180, 175))],
    "wine": [("bottle", "a dark green glass wine bottle", (40, 70, 45)),
             ("bottle", "a dark glass red wine bottle", (55, 30, 40))],
    "malt": [("can", "an aluminium beer can", (175, 178, 182)),
             ("bottle", "a brown glass beer bottle", (90, 50, 20))],
}
SCENES = [
    ("bar", "standing on a dark wooden bar counter in a dimly lit cocktail bar, warm bokeh lights in the background"),
    ("shelf", "standing on a liquor store shelf, other plain bottles blurred around it, bright store lighting"),
    ("hand", "held in a person's hand in front of a kitchen, photographed with a phone"),
    ("cooler", "standing on a wire shelf inside an open beverage cooler in a convenience store, cold white light, other bottles behind it"),
    ("table", "standing on a rustic kitchen table by a window, soft daylight"),
]
NEGATIVE = ("text, letters, words, writing, numbers, logo, watermark, labels on other bottles, signage, "
            "second label, extra label, sticker, distorted label, cartoon, illustration")


def dev_items():
    dev = set(json.loads((DATA / "splits" / "split.json").read_text())["dev"])
    heldout = set(json.loads((DATA / "splits" / "split.json").read_text())["heldout"])
    for d in sorted((DATA / "synthetic").iterdir()):
        base = "_".join(d.name.split("_")[:3])
        if d.is_dir() and base in dev:
            assert base not in heldout
            yield d, json.loads((d / "item.json").read_text())


def group_of(item):
    defect = item["provenance"]["defect"]
    return "clean" if defect in CLEAN_DEFECTS else "front" if defect in FRONT_DEFECTS else "warning"


def choose(count):
    """A fixed, balanced pick: per product type, clean labels, front-label mistakes and warning mistakes."""
    by = {}
    for d, it in dev_items():
        by.setdefault((it["application"]["beverage_type"], group_of(it)), []).append((d, it))
    per_type = count // 3
    picked = []
    for btype in ("spirits", "wine", "malt"):
        rng = random.Random(f"pick-{btype}")
        take = []
        for g, q in QUOTA.items():
            pool = by.get((btype, g), [])
            rng.shuffle(pool)
            take += pool[:q]
        rest = [x for g in QUOTA for x in by.get((btype, g), []) if x not in take]
        take += rest[:max(0, per_type - len(take))]
        picked += take[:per_type]
    return sorted(picked, key=lambda x: x[0].name)


def warp_label(label, target_w, half_angle_deg, bow, tilt_deg, rng):
    """OUR geometric transform: scale, wrap onto a cylinder seen slightly from above, tilt. Returns RGBA (uint8)."""
    h0, w0 = label.shape[:2]
    s = target_w / w0
    img = cv2.resize(label, (target_w, int(round(h0 * s))), interpolation=cv2.INTER_AREA)
    h, w = img.shape[:2]
    phi = math.radians(half_angle_deg)
    r = w / (2 * phi)
    out_w = int(2 * r * math.sin(phi))
    xs = np.arange(out_w, dtype=np.float32) - out_w / 2
    angle = np.arcsin(np.clip(xs / r, -1, 1))
    drop = bow * r * (1 - np.cos(angle))          # seen from slightly above: the middle of each edge sits lower than the sides
    out_h = int(h + drop.max()) + 2
    map_x = np.tile((w / 2 + r * angle).astype(np.float32), (out_h, 1))
    map_y = (np.arange(out_h, dtype=np.float32)[:, None] - (drop.max() - drop)[None, :]).astype(np.float32)
    rgba = np.dstack([img, np.full((h, w), 255, np.uint8)])
    warped = cv2.remap(rgba, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
    shade = (np.cos(angle) ** 0.5)[None, :, None]
    center = rng.uniform(-0.45, 0.45) * out_w / 2
    stripe = np.exp(-((xs - center) ** 2) / (2 * (out_w * rng.uniform(0.02, 0.05)) ** 2))
    stripe = (stripe * rng.uniform(40, 110))[None, :, None]
    rgb = np.clip(warped[..., :3] * shade + stripe, 0, 255)
    out = np.dstack([rgb, warped[..., 3:]]).astype(np.uint8)
    # tilt, on a padded canvas so nothing is cut
    pad = int(0.05 * max(out.shape[:2]))
    out = cv2.copyMakeBorder(out, pad, pad, pad, pad, cv2.BORDER_CONSTANT, value=0)
    m = cv2.getRotationMatrix2D((out.shape[1] / 2, out.shape[0] / 2), tilt_deg, 1.0)
    out = cv2.warpAffine(out, m, (out.shape[1], out.shape[0]), flags=cv2.INTER_LINEAR, borderValue=0)
    ys, xs_ = np.where(out[..., 3] > 0)
    return out[ys.min():ys.max() + 1, xs_.min():xs_.max() + 1]


def guide_canvas(patch, kind, color, rng):
    """Plain canvas with a rough bottle or can drawn around the label.
    Returns (canvas RGB, label top-left, (body left, body right)). The model repaints all of it except the label."""
    ph, pw = patch.shape[:2]
    bg = tuple(int(c) for c in rng.choice([(90, 80, 70), (120, 115, 110), (60, 55, 50), (150, 150, 155)]))
    im = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(im)
    cx = W // 2 + int(rng.uniform(-0.06, 0.06) * W)
    top = int(0.82 * H) - ph  # low on the body, as on real bottles: no bare glass below for a second label
    body_w = int(pw * (1.10 if kind == "bottle" else 1.04))
    x0, x1 = cx - body_w // 2, cx + body_w // 2
    dark = tuple(max(0, c - 35) for c in color)
    if kind == "bottle":
        body_top, body_bot = top - int(0.05 * H), min(H - 60, top + ph + int(0.05 * H))
        neck_w = int(body_w * 0.32)
        shoulder = body_top - int(0.10 * H)
        d.rounded_rectangle([x0, body_top - int(0.04 * H), x1, body_bot], radius=int(body_w * 0.12), fill=color)
        d.polygon([(x0 + 4, body_top), (cx - neck_w // 2, shoulder), (cx + neck_w // 2, shoulder), (x1 - 4, body_top)],
                  fill=color)
        d.rectangle([cx - neck_w // 2, max(20, shoulder - int(0.13 * H)), cx + neck_w // 2, shoulder], fill=color)
        d.rectangle([cx - neck_w // 2 - 6, max(10, shoulder - int(0.18 * H)), cx + neck_w // 2 + 6,
                     max(20, shoulder - int(0.13 * H))], fill=dark)
    else:
        can_top, can_bot = top - int(0.04 * H), min(H - 60, top + ph + int(0.04 * H))
        d.rectangle([x0, can_top, x1, can_bot], fill=color)
        d.ellipse([x0, can_top - int(0.03 * H), x1, can_top + int(0.03 * H)], fill=dark)
        d.ellipse([x0, can_bot - int(0.02 * H), x1, can_bot + int(0.02 * H)], fill=color)
    # round shading across the body, so the strips of body we keep beside the label look like a curved surface
    arr = np.asarray(im).astype(np.float32)
    xs = np.arange(x0, x1)
    prof = 0.55 + 0.6 * np.cos(np.clip((xs - cx) / (body_w / 2), -1, 1) * math.pi / 2) ** 0.7
    band = arr[:, x0:x1]
    is_body = np.any(band != np.array(bg, np.float32), axis=2, keepdims=True)
    arr[:, x0:x1] = np.where(is_body, np.clip(band * prof[None, :, None], 0, 255), band)
    lx = cx - pw // 2
    return Image.fromarray(arr.astype(np.uint8)), (lx, top), (x0, x1)


def paste(base_rgb, patch, at):
    """Alpha-composite our label patch onto base at (x, y). Returns the new image and the 'fully label' mask."""
    out = base_rgb.astype(np.float32).copy()
    x, y = at
    ph, pw = patch.shape[:2]
    a = patch[..., 3:].astype(np.float32) / 255.0
    region = out[y:y + ph, x:x + pw]
    out[y:y + ph, x:x + pw] = patch[..., :3] * a + region * (1 - a)
    full = np.zeros(base_rgb.shape[:2], bool)
    full[y:y + ph, x:x + pw] = patch[..., 3] == 255
    return np.clip(np.rint(out), 0, 255).astype(np.uint8), full


def b64png(im):
    b = io.BytesIO()
    im.save(b, "PNG")
    return base64.b64encode(b.getvalue()).decode()


class Bedrock:
    def __init__(self, max_calls):
        import boto3
        self.c = boto3.client("bedrock-runtime", region_name="us-east-1")
        self.max_calls, self.calls, self.errors = max_calls, 0, []

    def inpaint(self, image, mask, prompt, seed):
        if self.calls >= self.max_calls:
            raise RuntimeError(f"call budget reached ({self.max_calls})")
        self.calls += 1
        body = {"prompt": prompt, "negative_prompt": NEGATIVE, "image": b64png(image), "mask": b64png(mask),
                "seed": seed, "output_format": "png"}
        r = self.c.invoke_model(modelId=MODEL, body=json.dumps(body))
        d = json.loads(r["body"].read())
        if d.get("finish_reasons") and d["finish_reasons"][0]:
            raise RuntimeError(f"model refused: {d['finish_reasons']}")
        return Image.open(io.BytesIO(base64.b64decode(d["images"][0]))).convert("RGB")


def camera(img, rng):
    """OUR photo effects over the whole picture: vignette, slight blur, grain, sometimes a glare spot."""
    f = img.astype(np.float32)
    h, w = f.shape[:2]
    yy, xx = np.mgrid[0:h, 0:w]
    r2 = ((xx - w / 2) / (w / 2)) ** 2 + ((yy - h / 2) / (h / 2)) ** 2
    f *= (1 - rng.uniform(0.10, 0.25) * np.clip(r2, 0, 1.5))[..., None]
    effects = ["vignette"]
    if HARD and rng.random() < 0.6:   # bar or shop lighting: a warm, cool or green cast over the whole picture
        tint = rng.choice([(1.12, 1.0, 0.82), (0.85, 0.95, 1.15), (0.92, 1.1, 0.9)])
        f *= np.float32(tint)
        effects.append("tint")
    if rng.random() < (0.6 if HARD else 0.35):
        m = np.zeros((h, w), np.float32)
        c = (int(rng.uniform(0.3, 0.7) * w), int(rng.uniform(0.3, 0.7) * h))
        ax = (int(rng.uniform(0.04, 0.09) * w), int(rng.uniform(0.03, 0.07) * h))
        cv2.ellipse(m, c, ax, rng.uniform(0, 180), 0, 360, 1.0, -1)
        m = cv2.GaussianBlur(m, (0, 0), sigmaX=max(ax) / 2)
        f = f + m[..., None] * rng.uniform(0.35, 0.6) * (255 - f)
        effects.append("glare")
    sigma = rng.choice([0, 0.6, 0.9])
    if sigma:
        f = cv2.GaussianBlur(f, (0, 0), sigmaX=sigma)
        effects.append(f"blur{sigma}")
    f += np.random.default_rng(rng.randrange(1 << 30)).normal(0, rng.uniform(2, 5), f.shape)
    effects.append("grain")
    return np.clip(f, 0, 255).astype(np.uint8), effects


def norm_words(s):
    return re.findall(r"[a-z0-9]+", s.lower())


def brand_found(brand, lines):
    """Every word of the brand appears somewhere in the reading (case-insensitive, 80% similar), or the brand appears
    with its spaces lost ("OLDOAK")."""
    words = [w for line in lines for w in norm_words(line)]
    if "".join(norm_words(brand)) in "".join(words):
        return True
    return all(any(SequenceMatcher(None, b, w).ratio() >= 0.8 for w in words) for b in norm_words(brand))


def brand_partly_found(brand, lines):
    """Real labels: the reader found the brand at least in part (half of its words, 80% similar), or whole with its
    spaces lost. Fancy brands on real labels are often read partly ("MEIST" for HEIST); none at all = dropped."""
    words = [w for line in lines for w in norm_words(line)]
    bw = [b for b in norm_words(brand) if len(b) >= 2] or norm_words(brand)
    if "".join(bw) in "".join(words):
        return True
    hits = sum(any(SequenceMatcher(None, b, w).ratio() >= 0.8 for w in words) for b in bw)
    return hits >= max(1, math.ceil(len(bw) / 2))


def contact_sheet(entries, path):
    tw, th, cols = 300, 400, 8
    rows = math.ceil(len(entries) / cols)
    sheet = Image.new("RGB", (cols * tw, rows * (th + 34)), (245, 245, 245))
    d = ImageDraw.Draw(sheet)
    try:
        font = ImageFont.truetype("/System/Library/Fonts/Helvetica.ttc", 13)
    except OSError:
        font = ImageFont.load_default()
    for i, (name, img_path, caption) in enumerate(entries):
        im = Image.open(img_path).convert("RGB")
        im.thumbnail((tw - 8, th - 8))
        x, y = (i % cols) * tw, (i // cols) * (th + 34)
        sheet.paste(im, (x + (tw - im.width) // 2, y + 4))
        d.text((x + 6, y + th + 2), name[:40], fill=(0, 0, 0), font=font)
        d.text((x + 6, y + th + 17), caption[:44], fill=(90, 90, 90), font=font)
    sheet.save(path, quality=85)


# ---------------------------------------------------------------------------------------------------------------
# --real: the same idea with REAL approved labels (the 78 extra practice labels, data/splits/practice_extra.json),
# every label picture of the item in its own scene (so the warning on a back label is read from a photo too), and a
# harder camera applied by OUR code after the model: perspective up to about 45 degrees, rotation 10-30 degrees,
# close-ups and crops at an edge (the label itself always stays whole). Malt beverages go on cans drawn by our code
# (the model only paints the room around the can), or beer bottles.
# Output: data/scenes_real/<ttb id>__scene0/ with scene_1.jpg, scene_2.jpg, ... in the order of the record's images.
# ---------------------------------------------------------------------------------------------------------------
REAL_OUT = DATA / "scenes_real"
# flat printer's artwork rather than a label that goes on a container: a carton die-line, a 4-panel box die-line,
# a printer's proof sheet with dimension marks, and a phone photo of a label sheet (already a photo)
REAL_SKIP = {"25325001000646", "25056001000852", "26209001000785", "25226001000401"}
HARD_WORDS = ("vertical", "rotated", "sideways", "curved", "arched", "slanted", "script", "white text", "on black",
              "on dark", "dark", "busy", "low contrast", "low-contrast", "blackletter", "decorative", "ornate",
              "swash", "letter-spaced", "can", "wrap", "tiny", "condensed", "tilted")
REAL_CONTAINER = {"spirits": ["a glass spirits bottle", "a clear glass whiskey bottle with amber whiskey inside",
                              "a clear glass vodka bottle"],
                  "wine": ["a dark green glass wine bottle", "a dark glass red wine bottle", "a clear glass white wine bottle"],
                  "malt": ["a brown glass beer bottle"]}


def real_ids():
    split = json.loads((DATA / "splits" / "split.json").read_text())
    blocked = set(split["dev"]) | set(split["heldout"])          # the 64 original practice labels and the final test
    for x in json.loads((DATA / "splits" / "practice_extra.json").read_text())["dev"]:
        assert x not in blocked, x
        yield x[5:]


def hardness(gt):
    text = " ".join(gt.get("hard_cases", [])).lower()
    score = sum(w in text for w in HARD_WORDS)
    if gt["warning"].get("orientation") in ("vertical", "other"):
        score += 4
    return score


def real_application(rec, gt):
    """The application in the data/synthetic schema, from the answer key, as tools/evaluate.py cola_items builds it."""
    imported = rec.get("source") == "imported"
    front = rec["images"][0]
    return {"beverage_type": rec["product_type"] or "spirits", "brand_name": gt["brand_name"],
            "class_type": gt.get("class_type"), "abv": gt.get("abv"), "proof": gt.get("proof"),
            "net_contents": gt.get("net_contents_text"), "source": rec.get("source", "domestic"),
            "country_of_origin": gt.get("country_of_origin_text") if imported else None,
            "name_address": gt.get("name_address_text"), "label_width_in": front.get("width_in")}


def real_printed(gt):
    w = gt["warning"]
    return {"brand_name": gt["brand_name"], "class_type": gt.get("class_type"), "abv": gt.get("abv"),
            "proof": gt.get("proof"), "net_contents": gt.get("net_contents_text"),
            "warning_text": w.get("text_as_printed"), "warning_heading_bold": w.get("heading_looks_bold"),
            "warning_orientation": w.get("orientation"), "warning_image": w.get("image_file")}


def load_rgb(path):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        im = Image.alpha_composite(Image.new("RGBA", im.size, "white"), im)
    return np.asarray(im.convert("RGB"))


def can_canvas(patch, rng):
    """OUR aluminium can around the label (the label wraps the can body); returns canvas, label top-left, keep mask."""
    ph, pw = patch.shape[:2]
    bg = tuple(int(c) for c in rng.choice([(90, 80, 70), (120, 115, 110), (60, 55, 50)]))
    im = Image.new("RGB", (W, H), bg)
    keep = Image.new("L", (W, H), 0)
    cx = W // 2 + int(rng.uniform(-0.05, 0.05) * W)
    top = int(0.80 * H) - ph
    x0, x1 = cx - pw // 2 - 2, cx + pw - pw // 2 + 2
    rim = int(0.035 * H)
    for d, fill in ((ImageDraw.Draw(im), (190, 192, 196)), (ImageDraw.Draw(keep), 255)):
        d.rectangle([x0 + 6, top - rim, x1 - 6, top + ph + rim], fill=fill)          # bare metal above and below
        d.ellipse([x0 + 6, top - 2 * rim, x1 - 6, top], fill=fill)                    # lid
        d.ellipse([x0 + 10, top + ph, x1 - 10, top + ph + 2 * rim], fill=fill)         # base
    arr = np.asarray(im).astype(np.float32)
    xs = np.arange(x0, x1)
    prof = 0.45 + 0.75 * np.cos(np.clip((xs - cx) / ((x1 - x0) / 2), -1, 1) * math.pi / 2) ** 0.8
    k = np.asarray(keep)[:, x0:x1, None] > 0
    arr[:, x0:x1] = np.where(k, np.clip(arr[:, x0:x1] * prof[None, :, None], 0, 255), arr[:, x0:x1])
    d = ImageDraw.Draw(img := Image.fromarray(arr.astype(np.uint8)))
    d.ellipse([cx - pw // 6, top - int(1.6 * rim), cx + pw // 6, top - int(0.6 * rim)], outline=(120, 122, 126), width=4)
    return img, (cx - pw // 2, top), np.asarray(keep) > 0


def hard_camera(img, label_alpha, rng):
    """OUR geometric camera: perspective (turned up to ~45 degrees), rotation, then a crop that keeps the label whole.
    Returns (image, label alpha in the new frame, description)."""
    h, w = img.shape[:2]
    mode = rng.choices(["straight", "rotate", "perspective", "rotate+perspective"], [0 if HARD else 2, 3, 3, 2])[0]
    m = np.eye(3)
    desc = {"mode": mode}
    if "perspective" in mode:
        yaw = rng.uniform(25, 45)
        k = math.cos(math.radians(yaw))                     # the far side gets narrower and shorter
        shrink = 1 - 0.45 * math.sin(math.radians(yaw)) * rng.uniform(0.6, 1.0)
        src = np.float32([[0, 0], [w, 0], [w, h], [0, h]])
        far = (h * (1 - shrink)) / 2
        if rng.random() < 0.5:
            dst = np.float32([[0, 0], [w * k, far], [w * k, h - far], [0, h]])
        else:
            dst = np.float32([[w * (1 - k), far], [w, 0], [w, h], [w * (1 - k), h - far]])
        m = cv2.getPerspectiveTransform(src, dst) @ m
        desc["yaw_deg"] = round(yaw, 1)
    if "rotate" in mode:
        ang = rng.choice([-1, 1]) * rng.uniform(10, 30)
        r = np.vstack([cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0), [0, 0, 1]])
        m = r @ m
        desc["rotation_deg"] = round(ang, 1)
    corners = cv2.perspectiveTransform(np.float32([[[0, 0], [w, 0], [w, h], [0, h]]]), m)[0]
    shift = np.array([[1, 0, -corners[:, 0].min()], [0, 1, -corners[:, 1].min()], [0, 0, 1]])
    m = shift @ m
    ow, oh = int(np.ceil(np.ptp(corners[:, 0]))), int(np.ceil(np.ptp(corners[:, 1])))
    out = cv2.warpPerspective(img, m, (ow, oh), flags=cv2.INTER_LINEAR, borderValue=0)
    alpha = cv2.warpPerspective(label_alpha, m, (ow, oh), flags=cv2.INTER_LINEAR, borderValue=0)
    valid = cv2.warpPerspective(np.full((h, w), 255, np.uint8), m, (ow, oh), flags=cv2.INTER_NEAREST) == 255
    # crop: start from the label box, grow each side while the strip is all real picture (no empty corners)
    ys, xs = np.where(alpha > 0)
    box = [xs.min(), ys.min(), xs.max() + 1, ys.max() + 1]
    lw, lh = box[2] - box[0], box[3] - box[1]
    framing = rng.choices(["wide", "closeup", "edge"], [5, 3, 2])[0]
    limit = {"wide": 0.6, "closeup": 0.08, "edge": 0.6}[framing]
    x0, y0, x1, y1 = [int(v) for v in box]
    step = max(4, int(0.01 * max(ow, oh)))
    grow = {"l": True, "t": True, "r": True, "b": True}
    if framing == "edge":   # one side cut tight to the label, as when the photo cuts off part of the bottle
        grow[rng.choice("lrtb")] = False
        side_pad = int(0.015 * max(lw, lh))
        x0, y0, x1, y1 = max(0, x0 - side_pad), max(0, y0 - side_pad), min(ow, x1 + side_pad), min(oh, y1 + side_pad)
    while any(grow.values()):
        for s_, (nx0, ny0, nx1, ny1) in {"l": (x0 - step, y0, x1, y1), "r": (x0, y0, x1 + step, y1),
                                          "t": (x0, y0 - step, x1, y1), "b": (x0, y0, x1, y1 + step)}.items():
            if not grow[s_]:
                continue
            too_far = (nx1 - nx0) > lw * (1 + 2 * limit) or (ny1 - ny0) > lh * (1 + 2 * limit)
            if nx0 < 0 or ny0 < 0 or nx1 > ow or ny1 > oh or too_far or not valid[ny0:ny1, nx0:nx1].all():
                grow[s_] = False
            else:
                x0, y0, x1, y1 = nx0, ny0, nx1, ny1
    desc["framing"] = framing
    return out[y0:y1, x0:x1], alpha[y0:y1, x0:x1], desc, (m, (x0, y0))


def real_scene(label, btype, key, rng, bed, prompt_extra=""):
    """One label picture -> (final picture, check record). The model never paints inside the label."""
    lh, lw = label.shape[:2]
    can = btype == "malt" and rng.random() < 0.6
    container = "can" if can else rng.choice(REAL_CONTAINER[btype])
    aspect = lw / lh
    phi = rng.uniform(25, 38) if aspect < 1.4 else rng.uniform(38, 50)    # a wide wraparound label bends more
    if can:
        phi = max(phi, 40)
    frac = 0.62 if aspect >= 1.4 else 0.40
    target_w = int(min(frac * W, 0.42 * H * aspect) * rng.uniform(0.92, 1.0))
    patch = warp_label(label, target_w, phi, rng.uniform(0.03, 0.08), rng.uniform(-2, 2), rng)
    if can:
        guide, at, keep = can_canvas(patch, rng)
        kind = "can"
    else:
        guide, at, _ = guide_canvas(patch, "bottle", (110, 90, 60), rng)
        keep = np.zeros((H, W), bool)
        kind = "bottle"
    guide_np, full = paste(np.asarray(guide), patch, at)
    scene_key, scene = SCENES[rng.randrange(len(SCENES))]
    if can:
        prompt = (f"realistic phone photo of a single aluminium drink can {scene}, the can is already in the picture, "
                  "sharp focus on the can, shallow depth of field")
    else:
        prompt = (f"realistic phone photo of a single {container.removeprefix('a ')} {scene}, the whole bottle visible, "
                  f"paper label on the bottle{prompt_extra}, sharp focus on the label, shallow depth of field")
    seed = rng.randrange(1, 4_000_000_000)
    lab_mask = np.zeros((H, W), bool)
    x, y = at
    ph, pw = patch.shape[:2]
    lab_mask[y:y + ph, x:x + pw] = patch[..., 3] > 0
    mask = np.where(lab_mask | keep, 0, 255).astype(np.uint8)
    hkey = hashlib.sha1(json.dumps([MODEL, prompt, NEGATIVE, seed, at, patch.shape, kind, "real1"]).encode()).hexdigest()[:8]
    raw_path = RAW / f"real_{key}_{hkey}.png"
    if bed is None:
        base = guide_np
    else:
        if not raw_path.exists():
            bed.inpaint(Image.fromarray(guide_np), Image.fromarray(mask).convert("RGB"), prompt, seed).save(raw_path)
        gen = Image.open(raw_path).convert("RGB")
        base = np.asarray(gen if gen.size == (W, H) else gen.resize((W, H), Image.LANCZOS))
    if can:   # our can too is put back exactly: the model only painted the room around it
        base = np.where(keep[..., None], guide_np, base)
    composite, full = paste(base, patch, at)
    inside = full[y:y + ph, x:x + pw]
    identical = bool(np.array_equal(composite[y:y + ph, x:x + pw][inside], patch[..., :3][inside]))
    # our harder camera; check again that, inside the label, the picture equals our label moved the same way
    alpha_full = np.zeros((H, W), np.uint8)
    alpha_full[y:y + ph, x:x + pw] = patch[..., 3]
    label_only = np.zeros_like(composite)
    label_only[y:y + ph, x:x + pw] = patch[..., :3]
    moved, alpha, desc, (m, (cx0, cy0)) = hard_camera(composite, alpha_full, rng)
    full_ref = cv2.warpPerspective(label_only, m, (moved.shape[1] + cx0 + 1, moved.shape[0] + cy0 + 1),
                                   flags=cv2.INTER_LINEAR, borderValue=0)[cy0:cy0 + moved.shape[0], cx0:cx0 + moved.shape[1]]
    core = cv2.erode((alpha == 255).astype(np.uint8), np.ones((5, 5), np.uint8)) > 0
    moved_identical = bool(np.array_equal(moved[core], full_ref[core]))
    final, effects = camera(moved, rng)
    rec = {"container": kind, "scene": scene_key, "prompt": prompt, "seed": seed, "half_angle": round(phi, 1),
           "camera": desc, "label_pixels_identical_before_camera_effects": identical,
           "label_pixels_identical_after_our_geometry": moved_identical, "camera_effects": effects,
           "size": [final.shape[1], final.shape[0]]}
    return final, rec


def main_real(args):
    REAL_OUT.mkdir(parents=True, exist_ok=True)
    RAW.mkdir(parents=True, exist_ok=True)
    bed = None if args.no_model else Bedrock(args.max_calls)
    sys.path.insert(0, str(ROOT))
    from app.ocr.reader import Reader
    reader = Reader(cpus=4)
    reader.warm_up()
    pool = []
    for i in real_ids():
        if i in REAL_SKIP:
            continue
        rec = json.loads((DATA / "cola_samples" / i / "record.json").read_text())
        gt = json.loads((DATA / "ground_truth" / f"{i}.json").read_text())
        pool.append((hardness(gt), i, rec, gt))
    pool.sort(key=lambda t: (-t[0], t[1]))
    if args.only:
        pool = [t for t in pool if t[1] == args.only]
    # the reader must find the brand on the flat label first; otherwise a scene could not be kept anyway
    picked, unreadable_flat = [], []
    for t in pool:
        if len(picked) >= args.count:
            break
        flat = reader.read([(im["file"], (DATA / "cola_samples" / t[1] / im["file"]).read_bytes())
                            for im in t[2]["images"]])
        (picked if brand_partly_found(t[3]["brand_name"], flat.lines()) else unreadable_flat).append(t)
    print(f"{len(picked)} picked; {len(unreadable_flat)} skipped (brand not found even on the flat label)", flush=True)
    report = {"model": None if args.no_model else MODEL, "items": [], "dropped": [],
              "skipped_brand_not_read_flat": [f"cola_{t[1]}" for t in unreadable_flat]}
    sheet = []
    for n, (score, i, rec, gt) in enumerate(picked):
        name = f"{i}__scene0"
        dest = REAL_OUT / name
        rng = random.Random(f"real-{i}")
        btype = rec["product_type"] or "spirits"
        images, recs, files = [], [], []
        try:
            k = 0
            for im in rec["images"]:
                label = load_rgb(DATA / "cola_samples" / i / im["file"])
                extra = " seen from the back" if "back" in im["image_type"].lower() else ""
                lw = label.shape[1]
                # a wide wraparound label cannot be seen whole from one side: two photos, left 60% and right 60%
                parts = [(0, lw, "")] if lw / label.shape[0] < 1.4 else \
                    [(0, int(0.6 * lw), " (left part)"), (int(0.4 * lw), lw, " (right part)")]
                for a, b, part in parts:
                    k += 1
                    final, r = real_scene(np.ascontiguousarray(label[:, a:b]), btype, f"{i}_{k}", rng, bed, extra)
                    r["source_image"] = im["file"] + (f" columns {a}-{b}" if part else "")
                    images.append((f"scene_{k}.jpg", final, {**im, "image_type": im["image_type"] + part}))
                    recs.append(r)
        except Exception as e:  # noqa: BLE001  (a refused or failed call drops the item, counted)
            report["dropped"].append({"id": name, "why": f"model call failed: {str(e)[:150]}"})
            print(f"[{n + 1}/{len(picked)}] {name} model error {e}", flush=True)
            continue
        if not all(r["label_pixels_identical_before_camera_effects"] and r["label_pixels_identical_after_our_geometry"]
                   for r in recs):
            raise SystemExit(f"{name}: label area changed; stopping")
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        for fname, final, _ in images:
            Image.fromarray(final).save(dest / fname, quality=90)
        reading = reader.read([(f, (dest / f).read_bytes()) for f, _, _ in images])
        ok = brand_partly_found(gt["brand_name"], reading.lines())
        entry = {"id": name, "base_item": f"cola_{i}", "hardness": score, "brand_found": ok, "pictures": recs,
                 "warning_orientation": gt["warning"].get("orientation")}
        if not ok:
            flat = reader.read([(im["file"], (DATA / "cola_samples" / i / im["file"]).read_bytes())
                                for im in rec["images"]])
            entry["brand_found_on_flat_originals"] = brand_partly_found(gt["brand_name"], flat.lines())
            entry["read"] = [l for l in reading.lines() if l][:15]
            shutil.rmtree(dest)
            report["dropped"].append(entry | {"why": "reader did not find the brand in the scene pictures"})
            print(f"[{n + 1}/{len(picked)}] {name} DROPPED (brand not read; flat originals: "
                  f"{entry['brand_found_on_flat_originals']})", flush=True)
            continue
        app = real_application(rec, gt)
        item = {
            "id": name,
            "images": [{"file": f, "image_type": im["image_type"]} for f, _, im in images],
            "source": {"type": "real label scene", "license": "public COLA registry label artwork; scene generated for this project"},
            "application": app,
            "printed": real_printed(gt),
            "expected": {"overall": "approved", "findings": [],
                         "warning_misprinted": not gt["warning"].get("matches_required_text", True),
                         "warning_present": gt["warning"].get("present")},
            "provenance": {"base_item": f"cola_{i}", "model": "composite" if args.no_model else MODEL,
                           "prompt": [r["prompt"] for r in recs], "seed": [r["seed"] for r in recs]},
        }
        (dest / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False))
        report["items"].append(entry)
        for (f, _, _), r in zip(images, recs):
            cam = r["camera"]
            sheet.append((f"{i} {f}", dest / f, f"{btype} {cam['mode']} {cam.get('rotation_deg', '')}"
                                                  f"{' yaw' + str(cam['yaw_deg']) if 'yaw_deg' in cam else ''} {cam['framing']}"))
        print(f"[{n + 1}/{len(picked)}] {name} ok {len(images)} pictures", flush=True)
    if bed:
        report.update(calls_this_run=bed.calls, est_cost_usd_this_run=[round(bed.calls * PRICE_LOW, 2),
                                                                         round(bed.calls * PRICE_HIGH, 2)],
                      paid_real_calls_all_runs=len(list(RAW.glob("real_*.png"))))
    if not args.only:
        (REAL_OUT / "_report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
        if sheet:
            contact_sheet(sheet, REAL_OUT / "_contact_sheet.jpg")
    print(f"kept {len(report['items'])}, dropped {len(report['dropped'])}, calls {bed.calls if bed else 0}")


# --final (added 2026-10-10): the same scenes for the final-test labels (data/splits/split.json "heldout" minus the six
# with a twin in practice), with HARD photos, into data/scenes_real_final/; and the planted-change final-test labels
# (data/tampered_final, tools/make_tampered.py --set final), one per label, into data/scenes_tampered_final/. Nothing
# is dropped and the reader is never run on them: tools/evaluate.py --final runs them once, with the final test.
def main_final(args):
    global HARD
    HARD = True
    RAW.mkdir(parents=True, exist_ok=True)
    bed = None if args.no_model else Bedrock(args.max_calls)
    split = json.loads((DATA / "splits" / "split.json").read_text())
    twins = set(json.loads((DATA / "splits" / "heldout_twins.json").read_text())["heldout"])
    ids = sorted(x[5:] for x in split["heldout"] if x.startswith("cola_") and x[5:] not in twins | REAL_SKIP)
    sources = []   # (output folder, item name, folder with the pictures, picture list, beverage type, item fields)
    for i in ids:
        rec = json.loads((DATA / "cola_samples" / i / "record.json").read_text())
        gt = json.loads((DATA / "ground_truth" / f"{i}.json").read_text())
        sources.append((DATA / "scenes_real_final", f"{i}__scene0", DATA / "cola_samples" / i, rec["images"],
                        rec["product_type"] or "spirits",
                        {"application": real_application(rec, gt), "printed": real_printed(gt),
                         "expected": {"overall": "approved", "findings": [],
                                      "warning_misprinted": not gt["warning"].get("matches_required_text", True),
                                      "warning_present": gt["warning"].get("present")},
                         "base_item": f"cola_{i}"}))
    tampered = sorted(d for d in (DATA / "tampered_final").iterdir() if d.is_dir())
    by_label = {}
    for d in tampered:   # one planted change per label, the kinds taken in turn
        by_label.setdefault(d.name.split("__")[0], []).append(d)
    for n, (base, ds) in enumerate(sorted(by_label.items())):
        d = ds[n % len(ds)]
        it = json.loads((d / "item.json").read_text())
        sources.append((DATA / "scenes_tampered_final", f"{d.name}__scene0", d, it["images"],
                        it["application"]["beverage_type"],
                        {"application": it["application"], "printed": it["printed"], "expected": it["expected"],
                         "base_item": d.name}))
    for out in {s_[0] for s_ in sources}:
        shutil.rmtree(out, ignore_errors=True)
        out.mkdir(parents=True)
    report = {"model": None if args.no_model else MODEL, "items": [], "failed": []}
    sheets = {}
    for n, (out, name, folder, pics, btype, fields) in enumerate(sources):
        rng = random.Random(f"final-{name}")
        images, recs = [], []
        try:
            k = 0
            for im in pics:
                label = load_rgb(folder / im["file"])
                extra = " seen from the back" if "back" in im["image_type"].lower() else ""
                lw = label.shape[1]
                parts = [(0, lw, "")] if lw / label.shape[0] < 1.4 else \
                    [(0, int(0.6 * lw), " (left part)"), (int(0.4 * lw), lw, " (right part)")]
                for a, b, part in parts:
                    k += 1
                    final, r = real_scene(np.ascontiguousarray(label[:, a:b]), btype, f"final_{name}_{k}", rng, bed, extra)
                    r["source_image"] = im["file"] + (f" columns {a}-{b}" if part else "")
                    images.append((f"scene_{k}.jpg", final, {**im, "image_type": im["image_type"] + part}))
                    recs.append(r)
        except Exception as e:  # noqa: BLE001  (a refused or failed call: the item is not made, and counted)
            report["failed"].append({"id": name, "why": f"model call failed: {str(e)[:150]}"})
            print(f"[{n + 1}/{len(sources)}] {name} model error {e}", flush=True)
            continue
        if not all(r["label_pixels_identical_before_camera_effects"] and r["label_pixels_identical_after_our_geometry"]
                   for r in recs):
            raise SystemExit(f"{name}: label area changed; stopping")
        dest = out / name
        dest.mkdir()
        for fname, final, _ in images:
            Image.fromarray(final).save(dest / fname, quality=90)
        item = {"id": name, "images": [{"file": f, "image_type": im["image_type"]} for f, _, im in images],
                "source": {"type": "real label scene (final test)",
                           "license": "public COLA registry label artwork; scene generated for this project"},
                "application": fields["application"], "printed": fields["printed"], "expected": fields["expected"],
                "provenance": {"base_item": fields["base_item"], "model": "composite" if args.no_model else MODEL,
                               "prompt": [r["prompt"] for r in recs], "seed": [r["seed"] for r in recs]}}
        (dest / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False))
        report["items"].append({"id": name, "set": out.name, "base_item": fields["base_item"], "pictures": recs})
        for (f, _, _), r in zip(images, recs):
            cam = r["camera"]
            sheets.setdefault(out, []).append((f"{name[:14]} {f}", dest / f, f"{btype} {cam['mode']} {cam['framing']} "
                                               + " ".join(r["camera_effects"])))
        print(f"[{n + 1}/{len(sources)}] {name} ok {len(images)} pictures", flush=True)
    if bed:
        report.update(calls_this_run=bed.calls, est_cost_usd_this_run=[round(bed.calls * PRICE_LOW, 2),
                                                                         round(bed.calls * PRICE_HIGH, 2)])
    for out, sheet in sheets.items():
        (out / "_report.json").write_text(json.dumps({**report, "items": [x for x in report["items"]
                                                                          if x["set"] == out.name]}, indent=1))
        contact_sheet(sheet, out / "_contact_sheet.jpg")
    print(f"made {len(report['items'])}, failed {len(report['failed'])}, calls {bed.calls if bed else 0}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--count", type=int, default=54, help="scenes to make before dropping unreadable ones")
    ap.add_argument("--max-calls", type=int, default=70, help="hard cap on paid model calls in this run")
    ap.add_argument("--only", help="one synthetic item id (for a trial)")
    ap.add_argument("--reroll", default="", help="comma-separated scene ids to make again with the next seed")
    ap.add_argument("--no-model", action="store_true", help="composite only: our drawn bottle, no model call")
    ap.add_argument("--real", action="store_true", help="real approved labels (practice_extra) into data/scenes_real")
    ap.add_argument("--final", action="store_true", help="the final-test labels and their planted changes (see main_final)")
    args = ap.parse_args()
    if args.final:
        return main_final(args)
    if args.real:
        return main_real(args)
    picked = choose(args.count)
    attempts_path = OUT / "_attempts.json"   # which scenes were made again because the model drew no bottle
    rerolls = json.loads(attempts_path.read_text()) if attempts_path.exists() else {}
    for r in filter(None, args.reroll.split(",")):
        rerolls[r] = rerolls.get(r, 0) + 1
    if args.only:
        picked = [(d, it) for d, it in dev_items() if d.name == args.only]
    RAW.mkdir(parents=True, exist_ok=True)
    OUT.mkdir(parents=True, exist_ok=True)
    bed = None if args.no_model else Bedrock(args.max_calls)

    sys.path.insert(0, str(ROOT))
    from app.ocr.reader import Reader
    reader = Reader(cpus=4)
    reader.warm_up()

    report = {"model": None if args.no_model else MODEL, "items": [], "dropped": []}
    sheet = []
    for n, (d, it) in enumerate(picked):
        rng = random.Random(f"scene-{it['id']}")
        btype = it["application"]["beverage_type"]
        kind, container, color = rng.choice(CONTAINER[btype])
        scene_key, scene = SCENES[rng.randrange(len(SCENES))]
        prompt = (f"realistic phone photo of a single {container.removeprefix('a ').removeprefix('an ')} {scene}, "
                  f"the whole {kind} visible, paper label on the {kind}, sharp focus on the label, shallow depth of field")
        seed = rng.randrange(1, 4_000_000_000)
        attempt = rerolls.get(f"{it['id']}__scene0", 0)
        seed = (seed + 7919 * attempt) % 4_000_000_000 or 1
        front_meta = next(im for im in it["images"] if im["image_type"].startswith("Brand"))
        back_metas = [im for im in it["images"] if im is not front_meta]
        label = np.asarray(Image.open(d / front_meta["file"]).convert("RGB"))
        if kind == "can" and (label.shape[0] > label.shape[1] or attempt):  # a tall label does not fit a can
            kind, container, color = CONTAINER["malt"][1]
            prompt = prompt.replace("aluminium beer can", "brown glass beer bottle").replace(" can", " bottle")
        geo = {"half_angle": rng.uniform(22, 38) if kind == "bottle" else rng.uniform(30, 45),
               "bow": rng.uniform(0.04, 0.10), "tilt": rng.uniform(-1.5, 1.5)}
        lh, lw = label.shape[:2]
        frac = 0.28 if (btype == "malt" and kind == "bottle") else 0.34  # a beer bottle is drawn narrow
        target_w = int(min(frac * W, 0.36 * H * lw / lh) * rng.uniform(0.92, 1.05))  # room for a whole bottle
        patch = warp_label(label, target_w, geo["half_angle"], geo["bow"], geo["tilt"], rng)
        guide, at, (bx0, bx1) = guide_canvas(patch, kind, color, rng)
        guide_np, full = paste(np.asarray(guide), patch, at)
        name = f"{it['id']}__scene0"
        key = hashlib.sha1(json.dumps([MODEL, prompt, NEGATIVE, seed, at, patch.shape, bx0, bx1, "v3"]).encode()).hexdigest()[:8]
        raw_path = RAW / f"{name}_{key}.png"  # cache only reused for the very same request
        if args.no_model:
            base = guide_np
        else:
            if not raw_path.exists():
                mask = Image.fromarray(np.where(patch[..., 3] > 0, 0, 255).astype(np.uint8))
                m = Image.new("L", (W, H), 255)
                m.paste(mask, at)
                try:
                    t = time.time()
                    gen = bed.inpaint(Image.fromarray(guide_np), m.convert("RGB"), prompt, seed)
                    print(f"  model {time.time() - t:.1f}s size={gen.size}", flush=True)
                except Exception as e:  # noqa: BLE001  (a refused or failed call drops the item, counted)
                    bed.errors.append((name, str(e)[:200]))
                    report["dropped"].append({"id": name, "why": f"model call failed: {str(e)[:120]}"})
                    print(f"[{n + 1}/{len(picked)}] {name} model error {e}", flush=True)
                    continue
                gen.save(raw_path)
            gen = Image.open(raw_path).convert("RGB")
            if gen.size != (W, H):
                gen = gen.resize((W, H), Image.LANCZOS)
            base = np.asarray(gen)
        # our label pixels back on top; the label area must equal our warped label exactly
        composite, full = paste(base, patch, at)
        x, y = at
        ph, pw = patch.shape[:2]
        inside = full[y:y + ph, x:x + pw]
        identical = bool(np.array_equal(composite[y:y + ph, x:x + pw][inside], patch[..., :3][inside]))
        model_diff = float(np.abs(base[y:y + ph, x:x + pw][inside].astype(int)
                                  - patch[..., :3][inside].astype(int)).mean())
        final, effects = camera(composite, rng)
        after_fx = float(np.abs(final[y:y + ph, x:x + pw][inside].astype(int)
                                - patch[..., :3][inside].astype(int)).mean())
        dest = OUT / name
        if dest.exists():
            shutil.rmtree(dest)
        dest.mkdir(parents=True)
        Image.fromarray(final).save(dest / "scene.jpg", quality=90)
        for bm in back_metas:
            shutil.copyfile(d / bm["file"], dest / bm["file"])
        reading = reader.read([("scene.jpg", (dest / "scene.jpg").read_bytes())])
        ok = brand_found(it["application"]["brand_name"], reading.lines())
        # text the MODEL drew (signs, other labels): read the picture with our label greyed out
        bg_only = final.copy()
        bg_only[y:y + ph, x:x + pw][patch[..., 3] > 0] = 128
        buf = io.BytesIO()
        Image.fromarray(bg_only).save(buf, "JPEG", quality=90)
        bg_read = reader.read([("bg.jpg", buf.getvalue())])
        model_words = sorted({w for r in bg_read.readings for w, c, _ in r.words
                              if c >= 0.7 and len(w) >= 4 and w.isalpha()})
        rec = {"id": name, "base_item": it["id"], "container": kind, "scene": scene_key, "geometry": geo,
               "label_box": [x, y, pw, ph], "label_pixels_identical_before_camera_effects": identical,
               "model_pixels_vs_label_mean_abs_diff": round(model_diff, 1),
               "final_vs_label_mean_abs_diff": round(after_fx, 1), "camera_effects": effects, "brand_found": ok,
               "model_drawn_words": model_words}
        if not identical:
            raise SystemExit(f"{name}: label area changed; stopping")
        if not ok:
            shutil.rmtree(dest)
            report["dropped"].append({"id": name, "why": "reader did not find the brand in the scene picture",
                                      "read": [l for l in reading.lines() if l][:12]})
            print(f"[{n + 1}/{len(picked)}] {name} DROPPED (brand not read)", flush=True)
            continue
        item = {
            "id": name,
            "images": [{"file": "scene.jpg", "image_type": front_meta["image_type"]}] + back_metas,
            "source": {"type": "synthetic scene", "license": "generated for this project"},
            "application": it["application"],
            "printed": it["printed"],
            "expected": it["expected"],
            "provenance": {"base_item": it["id"], "model": "composite" if args.no_model else MODEL,
                           "prompt": None if args.no_model else prompt, "seed": seed},
        }
        (dest / "item.json").write_text(json.dumps(item, indent=2))
        report["items"].append(rec)
        sheet.append((name, dest / "scene.jpg", f"{it['expected']['overall']} {scene_key} {kind}"))
        print(f"[{n + 1}/{len(picked)}] {name} ok {scene_key}/{kind} diff_model={model_diff:.0f}", flush=True)
    if bed:
        paid = len(list(RAW.glob("*.png")))  # every cached output is one paid call, over all runs
        report.update(calls_this_run=bed.calls, errors=bed.errors, paid_calls_all_runs=paid,
                      est_cost_usd_all_runs=[round(paid * PRICE_LOW, 2), round(paid * PRICE_HIGH, 2)])
    if args.reroll:
        attempts_path.write_text(json.dumps(rerolls, indent=1))
    report["rerolled"] = rerolls
    if not args.only:
        (OUT / "_report.json").write_text(json.dumps(report, indent=1))
        if sheet:
            contact_sheet(sheet, OUT / "_contact_sheet.jpg")
    print(f"kept {len(report['items'])}, dropped {len(report['dropped'])}, calls {bed.calls if bed else 0}")


if __name__ == "__main__":
    main()
