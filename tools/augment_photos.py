"""Turn clean label artwork into photo-like test images: bottle curve, glare, tilt, blur, noise.

Reads COLA samples (data/cola_samples) and synthetic labels (data/synthetic) and writes
data/augmented/<base_id>__s<seed>/ with the distorted images and an item.json that points
back to the base item. The correct answer for a distorted image is the base item's answer,
except that "Please check" is also acceptable — a degraded photo may honestly be unreadable.
A distorted image must never turn a Fail into a Pass.

Output is reproducible from the seed, so it is not committed (see .gitignore).

Usage: python tools/augment_photos.py [--seeds 3] [--synthetic-every 4]
"""

import argparse
import json
import math
import random
from pathlib import Path

import albumentations as A
import cv2
import numpy as np

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "augmented"


def cylinder_wrap(img, half_angle_deg, rng):
    """Project flat artwork onto a cylinder seen head-on, with matte shading and a specular stripe."""
    h, w = img.shape[:2]
    phi = math.radians(half_angle_deg)
    r = w / (2 * phi)                      # label width = arc length 2*phi*r
    out_w = int(2 * r * math.sin(phi))
    xs = np.arange(out_w, dtype=np.float32) - out_w / 2
    angle = np.arcsin(np.clip(xs / r, -1, 1))
    map_x = np.tile((w / 2 + r * angle).astype(np.float32), (h, 1))
    map_y = np.tile(np.arange(h, dtype=np.float32)[:, None], (1, out_w))
    warped = cv2.remap(img, map_x, map_y, cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)
    shade = (np.cos(angle) ** 0.6)[None, :, None]
    stripe_center = rng.uniform(-0.5, 0.5) * out_w / 2
    stripe = np.exp(-((xs - stripe_center) ** 2) / (2 * (out_w * rng.uniform(0.02, 0.06)) ** 2))
    stripe = (stripe * rng.uniform(60, 140))[None, :, None]
    return np.clip(warped * shade + stripe, 0, 255).astype(np.uint8)


def glare_spot(img, rng):
    """Bright elliptical hotspot, like a flash reflection on glass."""
    h, w = img.shape[:2]
    mask = np.zeros((h, w), np.float32)
    center = (int(rng.uniform(0.2, 0.8) * w), int(rng.uniform(0.2, 0.8) * h))
    axes = (int(rng.uniform(0.06, 0.18) * w), int(rng.uniform(0.04, 0.12) * h))
    cv2.ellipse(mask, center, axes, rng.uniform(0, 180), 0, 360, 1.0, -1)
    mask = cv2.GaussianBlur(mask, (0, 0), sigmaX=max(axes) / 2)
    strength = rng.uniform(0.5, 0.95)
    return np.clip(img + mask[..., None] * strength * (255 - img), 0, 255).astype(np.uint8)


def photo_pipeline(seed):
    return A.Compose([
        A.Perspective(scale=(0.03, 0.08), keep_size=False, fit_output=True, p=0.9),
        A.Rotate(limit=8, border_mode=cv2.BORDER_CONSTANT, fill=(200, 200, 200), p=0.7),
        A.RandomBrightnessContrast(brightness_limit=0.25, contrast_limit=0.25, p=0.8),
        A.RandomShadow(p=0.3),
        A.OneOf([A.MotionBlur(blur_limit=(3, 7)), A.GaussianBlur(blur_limit=(3, 5))], p=0.6),
        A.ISONoise(p=0.5),
        A.ImageCompression(quality_range=(55, 90), p=0.9),
    ], seed=seed)


def base_items():
    """Yield (base_id, folder, images, expected) for COLA and synthetic items."""
    for rec in sorted((ROOT / "data" / "cola_samples").glob("*/record.json")):
        r = json.loads(rec.read_text())
        yield f"cola_{r['ttb_id']}", rec.parent, r["images"], {"overall": "pass", "findings": [],
                                                               "note": "approved COLA; field answers in ground truth"}
    for item in sorted((ROOT / "data" / "synthetic").glob("*/item.json")):
        r = json.loads(item.read_text())
        yield r["id"], item.parent, r["images"], r["expected"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seeds", type=int, default=3, help="distorted copies per COLA record")
    ap.add_argument("--synthetic-every", type=int, default=4, help="augment every Nth synthetic item")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    count = 0
    for i, (base_id, folder, images, expected) in enumerate(base_items()):
        is_synth = base_id.startswith("syn_")
        if is_synth and i % args.synthetic_every:
            continue
        for seed in range(args.seeds if not is_synth else 1):
            rng = random.Random(f"{base_id}-{seed}")
            pipeline = photo_pipeline(rng.randrange(1 << 30))
            ops = {"cylinder_half_angle": rng.choice([0, 25, 40, 55]), "glare": rng.random() < 0.6}
            dest = OUT / f"{base_id}__s{seed}"
            dest.mkdir(exist_ok=True)
            out_images = []
            for img_meta in images:
                img = cv2.imread(str(folder / img_meta["file"]), cv2.IMREAD_COLOR)
                if img is None:
                    continue
                if ops["cylinder_half_angle"]:
                    img = cylinder_wrap(img, ops["cylinder_half_angle"], rng)
                if ops["glare"]:
                    img = glare_spot(img, rng)
                img = pipeline(image=img)["image"]
                name = Path(img_meta["file"]).stem + ".jpg"
                cv2.imwrite(str(dest / name), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
                # physical size is unknown once photographed, so dimensions are not carried over
                out_images.append({"file": name, "image_type": img_meta.get("image_type", "")})
            item = {
                "id": dest.name,
                "images": out_images,
                "source": {"type": "augmented", "base_id": base_id, "base_folder": str(folder.relative_to(ROOT))},
                "augmentation": ops | {"seed": seed, "pipeline": "albumentations 2.0.8 photo_pipeline"},
                "expected": {"overall": expected["overall"], "findings": expected.get("findings", []),
                             "also_acceptable": ["check"], "never": ["pass"] if expected["overall"] == "fail" else []},
            }
            (dest / "item.json").write_text(json.dumps(item, indent=2))
            count += 1
    print(f"wrote {count} augmented items to {OUT}")


if __name__ == "__main__":
    main()
