"""Split test data into a development set and a held-out set, and freeze the held-out set.

Split is by base label, so a label and all its variants (synthetic defects, photo-style
copies) land on the same side. Stratified by beverage type. The held-out manifest records a
SHA-256 for every held-out image; committing it proves the set wasn't changed after tuning.

Rule: during development, never look at results on held-out items. Run them once, at the end.

Usage: python tools/make_split.py   (refuses to overwrite an existing split)
"""

import hashlib
import json
import random
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = DATA / "splits"
SEED = 20261002
HELD_OUT_SHARE = 0.3


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bases():
    """(base_id, beverage_type, [image paths]) for every real or synthetic base label."""
    for rec in sorted((DATA / "cola_samples").glob("*/record.json")):
        r = json.loads(rec.read_text())
        yield f"cola_{r['ttb_id']}", r["product_type"], [rec.parent / i["file"] for i in r["images"]]
    for rec in sorted((DATA / "real_photos").glob("*/record.json")):
        r = json.loads(rec.read_text())
        yield f"photo_{r['barcode']}", r["product_type"], [rec.parent / i["file"] for i in r["images"]]
    synth = defaultdict(list)
    for item in sorted((DATA / "synthetic").glob("*/item.json")):
        r = json.loads(item.read_text())
        synth[(r["provenance"]["base_id"], r["application"]["beverage_type"])] += [item.parent / i["file"] for i in r["images"]]
    for (base_id, kind), paths in synth.items():
        yield base_id, kind, paths


def main():
    if (OUT / "split.json").exists():
        raise SystemExit("data/splits/split.json already exists; the held-out set is frozen.")
    rng = random.Random(SEED)
    groups = defaultdict(list)  # (source, beverage_type) -> bases
    for base_id, kind, paths in bases():
        groups[(base_id.split("_")[0], kind)].append((base_id, paths))

    split, manifest = {"dev": [], "heldout": []}, {}
    for key in sorted(groups):
        members = sorted(groups[key])
        rng.shuffle(members)
        n_held = round(len(members) * HELD_OUT_SHARE)
        for i, (base_id, paths) in enumerate(members):
            side = "heldout" if i < n_held else "dev"
            split[side].append(base_id)
            if side == "heldout":
                manifest[base_id] = {str(p.relative_to(ROOT)): sha256(p) for p in paths}

    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "split.json").write_text(json.dumps(
        {"seed": SEED, "held_out_share": HELD_OUT_SHARE,
         "rule": "Variants of a base label (synthetic defects, augmented photos) follow their base.",
         "dev": sorted(split["dev"]), "heldout": sorted(split["heldout"])}, indent=2))
    (OUT / "heldout_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True))
    print(f"dev: {len(split['dev'])} base labels   held-out: {len(split['heldout'])} base labels "
          f"({sum(len(v) for v in manifest.values())} images hashed)")


if __name__ == "__main__":
    main()
