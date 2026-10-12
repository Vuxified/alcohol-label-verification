"""Turn registry records fetched in a browser (out/ttb_fetch/b*.json) into practice labels.

The TTB registry stopped answering the automated collector on 2026-10-09 while an ordinary browser still worked, so
the records were fetched from a visible browser at one request every 4 s. Each record is
saved like the others (data/cola_samples/<ttb_id>/record.json + images), checked against the held-out set and the
existing practice labels, and listed in data/splits/practice_extra2.json.

Usage: python tools/import_ttb_fetch.py
"""

import base64
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from tools import dedupe_check  # noqa: E402
from tools.collect_cola_samples import DETAIL_FIELDS  # noqa: E402

COLA = ROOT / "data" / "cola_samples"
SPLIT = ROOT / "data" / "splits" / "practice_extra2.json"


def record_of(r):
    """The same fields collect_cola_samples.read_detail / read_form take from the two pages."""
    rec = {"ttb_id": r["id"]}
    for field in DETAIL_FIELDS:
        m = re.search(rf"{re.escape(field)}:[ \t]*([^\n]*)", r["detail"])
        rec[field.lower().replace(" ", "_").replace("/", "_").replace("#", "no")] = m.group(1).strip() if m else ""
    m = re.search(r"Principal Place of Business\):\s*\n(.*?)\n\s*Plant Registry", r["detail"], re.S)
    rec["applicant"] = " | ".join(x.strip() for x in m.group(1).splitlines() if x.strip()) if m else ""
    boxes = r["boxes"]
    rec["source"] = "imported" if len(boxes) > 1 and boxes[1] else "domestic"
    rec["product_type"] = next((k for k, on in zip(["wine", "spirits", "malt"], boxes[2:5]) if on), "")
    dims = re.findall(r"Image Type:\s*\n?\s*(.+?)\s*\n\s*Actual Dimensions:\s*([\d.]+)\s*inches W X\s*([\d.]+)\s*inches H",
                      r["form"])
    rec["images"] = []
    for n, (im, d) in enumerate(zip(r["images"], dims + [None] * len(r["images"])), 1):
        if im["status"] != 200 or not im["ctype"].startswith("image"):
            continue
        ext = ".png" if "png" in im["ctype"] else ".jpg"
        rec["images"].append({"file": f"{n:02d}_{re.sub(r'[^a-z]+', '_', im['type'].lower()).strip('_')}{ext}",
                              "image_type": im["type"], "width_in": float(d[1]) if d else None,
                              "height_in": float(d[2]) if d else None, "_b64": im["b64"]})
    return rec


def main():
    held_h, dev_h = dedupe_check.reference_hashes()
    banned = {w.upper() for w in json.loads((ROOT / "data" / "splits" / "heldout_brands.json").read_text())}
    ids = json.loads(SPLIT.read_text())["dev"] if SPLIT.exists() else []
    for path in sorted((ROOT / "out" / "ttb_fetch").glob("b[0-9]*.json")):
        data = json.loads(path.read_text())
        for r in json.loads(data) if isinstance(data, str) else data:
            if f"cola_{r['id']}" in ids or (COLA / r["id"]).exists():
                continue
            if r.get("error") or "APPROVED" not in (re.search(r"Status:\s*([^\n]*)", r.get("detail", "")) or [""])[0]:
                print(r["id"], "skipped:", r.get("error") or "not approved")
                continue
            rec = record_of(r)
            if not rec["images"]:
                print(r["id"], "skipped: no label images")
                continue
            folder = COLA / r["id"]
            folder.mkdir()
            for im in rec["images"]:
                (folder / im["file"]).write_bytes(base64.b64decode(im.pop("_b64")))
            near_held, near_dev = dedupe_check.nearest(folder, rec, held_h, dev_h)
            why = dedupe_check.reasons(rec, set(), banned, near_held, near_dev)
            if why:
                for f in folder.iterdir():
                    f.unlink()
                folder.rmdir()
                print(r["id"], "rejected:", ", ".join(why))
                continue
            (folder / "record.json").write_text(json.dumps(rec, indent=2))
            ids.append(f"cola_{r['id']}")
            print(r["id"], rec["product_type"], rec["brand_name"])
    SPLIT.write_text(json.dumps({"dev": ids, "note": "Practice labels fetched 2026-10-09 from the TTB Public COLA "
                                 "Registry in a browser; answer keys await the owner's review."}, indent=1))
    print(len(ids), "practice labels in", SPLIT.relative_to(ROOT))


if __name__ == "__main__":
    main()
