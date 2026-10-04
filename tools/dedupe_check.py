"""Keep the final test honest: reject collected labels that could be copies of final-test (held-out) labels.

A collected record in data/registry_pool/ is rejected when any of these hold:
  1. its TTB ID is already in data/cola_samples (collected before);
  2. the first word of its brand is the first word of a held-out brand (same brand, maybe a new layout);
  3. one of its images looks like a held-out image: 64-bit difference hash (dHash) within Hamming
     distance 12, checked for the image as stored and turned 90/180/270 degrees; or within 6 of any
     practice (dev) image (a near-exact copy).
Writes data/splits/train_pool.json (one entry per record, with the nearest held-out distance) and
data/splits/heldout_brands.json. Never changes split.json or the held-out manifest.

Usage: python tools/dedupe_check.py
"""

import json
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
COLA = ROOT / "data" / "cola_samples"
POOL = ROOT / "data" / "registry_pool"
SPLITS = ROOT / "data" / "splits"
HELD_LIMIT, DEV_LIMIT = 12, 6


def dhash(img, size=8):
    g = img.convert("L").resize((size + 1, size), Image.LANCZOS)
    px = list(g.get_flattened_data()) if hasattr(g, "get_flattened_data") else list(g.getdata())
    bits = 0
    for r in range(size):
        for c in range(size):
            bits = (bits << 1) | (px[r * (size + 1) + c] > px[r * (size + 1) + c + 1])
    return bits


def hashes(path):
    img = Image.open(path)
    return [dhash(img.rotate(a, expand=True)) for a in (0, 90, 180, 270)]


def dist(a, b):
    return bin(a ^ b).count("1")


def reference_hashes():
    """dHashes of every held-out and every practice (dev) COLA image."""
    split = json.loads((SPLITS / "split.json").read_text())
    held = {x[5:] for x in split["heldout"] if x.startswith("cola_")}
    held_h, dev_h = [], []
    for p in COLA.glob("*/record.json"):
        rec = json.loads(p.read_text())
        for im in rec["images"]:
            (held_h if p.parent.name in held else dev_h).append(dhash(Image.open(p.parent / im["file"])))
    return held_h, dev_h


def nearest(folder, rec, held_h, dev_h):
    """Smallest Hamming distance from any of the record's images (any quarter turn) to a held-out / dev image."""
    near_held = near_dev = 64
    for im in rec["images"]:
        for h in hashes(folder / im["file"]):
            near_held = min([near_held] + [dist(h, x) for x in held_h])
            near_dev = min([near_dev] + [dist(h, x) for x in dev_h])
    return near_held, near_dev


def reasons(rec, known, held_brands, near_held, near_dev):
    why = []
    if rec["ttb_id"] in known:
        why.append("already collected")
    if (rec["brand_name"].split() or [""])[0].upper() in held_brands:
        why.append("held-out brand")
    if near_held <= HELD_LIMIT:
        why.append(f"looks like a held-out image (distance {near_held})")
    if near_dev <= DEV_LIMIT:
        why.append(f"near-copy of a practice image (distance {near_dev})")
    return why


def main():
    split = json.loads((SPLITS / "split.json").read_text())
    held = {x[5:] for x in split["heldout"] if x.startswith("cola_")}
    known = {p.parent.name for p in COLA.glob("*/record.json")}
    held_brands, held_h, dev_h = set(), [], []
    for i in known:
        rec = json.loads((COLA / i / "record.json").read_text())
        target = held_h if i in held else dev_h
        if i in held:
            held_brands.add(rec["brand_name"].split()[0].upper())
        for im in rec["images"]:
            target.append(dhash(Image.open(COLA / i / im["file"])))
    (SPLITS / "heldout_brands.json").write_text(json.dumps(sorted(held_brands), indent=1))

    out, rejected = [], 0
    for p in sorted(POOL.glob("*/record.json")):
        rec = json.loads(p.read_text())
        i = rec["ttb_id"]
        why = []
        if i in known:
            why.append("already collected")
        if (rec["brand_name"].split() or [""])[0].upper() in held_brands:
            why.append("held-out brand")
        near_held, near_dev = 64, 64
        for im in rec["images"]:
            for h in hashes(p.parent / im["file"]):
                near_held = min([near_held] + [dist(h, x) for x in held_h])
                near_dev = min([near_dev] + [dist(h, x) for x in dev_h])
        if near_held <= HELD_LIMIT:
            why.append(f"looks like a held-out image (distance {near_held})")
        if near_dev <= DEV_LIMIT:
            why.append(f"near-copy of a practice image (distance {near_dev})")
        rejected += bool(why)
        out.append({"id": i, "brand": rec["brand_name"], "product_type": rec.get("product_type"),
                    "nearest_heldout_hamming": near_held, "nearest_dev_hamming": near_dev,
                    "accepted": not why, "rejected_because": why})
    (SPLITS / "train_pool.json").write_text(json.dumps(out, indent=1))
    print(f"{len(out)} pool records: {len(out) - rejected} accepted, {rejected} rejected")
    for r in out:
        if r["rejected_because"]:
            print("  rejected", r["id"], r["brand"], "-", "; ".join(r["rejected_because"]))


if __name__ == "__main__":
    main()
