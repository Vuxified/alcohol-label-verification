"""Build app/web/static/sample-batch.zip: a small batch for trying the batch page.

20 generated labels from the practice (dev) split, about half correct and half with a known problem, plus 2 rows
that are broken on purpose (an image missing from the ZIP, and a damaged image) to show that one bad row doesn't
stop the batch. The spreadsheet is inside the ZIP as manifest.csv, with a README.txt.

Usage: python tools/make_sample_batch.py
"""

import csv
import io
import json
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SYN = ROOT / "data" / "synthetic"
OUT = ROOT / "app" / "web" / "static" / "sample-batch.zip"
DEFECTS = ["abv_wrong", "net_wrong", "brand_extra_word", "class_wrong", "warning_missing", "warning_titlecase",
           "warning_wording", "proof_wrong", "net_metric_only", "brand_case_only"]
README = """Sample batch for Label Check
============================
manifest.csv lists 22 applications; their label images are in this ZIP.
20 are generated labels (made for this project, not real products): about half match their application and
half have a known problem, such as a wrong alcohol content or a reworded health warning.
Rows SAMPLE-21 and SAMPLE-22 are broken on purpose: one image is missing from the ZIP, and one image is damaged.
They show up as errors without stopping the rest of the batch.
"""


def dev_bases():
    return set(json.loads((ROOT / "data" / "splits" / "split.json").read_text())["dev"])


def pick():
    dev = dev_bases()
    items = [d for d in sorted(SYN.iterdir()) if d.is_dir() and "_".join(d.name.split("_")[:3]) in dev]
    kinds = ["spirits", "wine", "malt"]
    chosen = []
    for k, defect in enumerate(DEFECTS):  # one of each problem, rotating spirits / wine / beer
        hit = next((d for kind in kinds[k % 3:] + kinds[:k % 3] for d in items
                    if d.name.startswith(f"syn_{kind}_") and d.name.endswith("_" + defect)), None)
        if hit:
            chosen.append(hit)
    correct = [d for d in items if d.name.endswith("_none")]
    for k in range(len(correct)):  # then correct labels, also rotating, up to 20
        if len(chosen) >= 20:
            break
        kind = kinds[k % 3]
        hit = next((d for d in correct if d.name.startswith(f"syn_{kind}_") and d not in chosen), None)
        if hit:
            chosen.append(hit)
    return sorted(chosen, key=lambda d: d.name)


def main():
    rows, n = [], 0
    with zipfile.ZipFile(OUT, "w", zipfile.ZIP_DEFLATED) as z:
        for d in pick():
            n += 1
            item = json.loads((d / "item.json").read_text())
            a = item["application"]
            names = []
            for im in item["images"]:
                name = f"sample{n:02d}_{im['file']}"
                z.write(d / im["file"], f"images/{name}")
                names.append(f"images/{name}")
            rows.append({"application_id": f"SAMPLE-{n:02d}", "image_files": ";".join(names),
                         "beverage_type": a["beverage_type"], "brand_name": a["brand_name"],
                         "class_type": a.get("class_type") or "", "abv": "" if a.get("abv") is None else f"{a['abv']:g}",
                         "net_contents": a.get("net_contents") or "", "name_address": a.get("name_address") or "",
                         "source": a.get("source", "domestic"), "country_of_origin": a.get("country_of_origin") or ""})
        base = dict(rows[0])
        rows.append(base | {"application_id": "SAMPLE-21", "image_files": "images/not_in_this_zip.jpg"})
        z.writestr("images/sample22_damaged.jpg", b"\xff\xd8\xff\xe0 this is not really a picture")
        rows.append(base | {"application_id": "SAMPLE-22", "image_files": "images/sample22_damaged.jpg"})
        buf = io.StringIO()
        w = csv.DictWriter(buf, fieldnames=list(rows[0]), lineterminator="\r\n")
        w.writeheader()
        w.writerows(rows)
        z.writestr("manifest.csv", buf.getvalue())
        z.writestr("README.txt", README)
    print(f"wrote {OUT} ({OUT.stat().st_size / 1e6:.1f} MB, {len(rows)} rows)")


if __name__ == "__main__":
    main()
