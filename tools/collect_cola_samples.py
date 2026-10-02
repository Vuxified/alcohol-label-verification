"""Collect a small, slow-paced sample of approved labels from TTB's Public COLA Registry.

For each brand searched, saves the application data (record.json) and the label
images to data/cola_samples/<ttb_id>/. This is test data for the verifier, not a
bulk download: one request every few seconds, ~50 records total.

Usage: python tools/collect_cola_samples.py
"""

import csv
import json
import re
import time
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE = "https://www.ttbonline.gov/colasonline"
OUT = Path(__file__).resolve().parent.parent / "data" / "cola_samples"
DATE_FROM, DATE_TO = "01/01/2024", "10/01/2026"  # recent records have label images
DELAY_S = 3
PER_BRAND = 2

# Brand searches per product type — mix of domestic and imported. Malt includes
# flavored malt beverages (seltzers, hard tea), where alcohol content is mandatory.
BRANDS = {
    "spirits": ["BUFFALO TRACE", "MAKER'S MARK", "JACK DANIEL'S", "TITO'S", "JIM BEAM",
                "HENNESSY", "PATRON", "BACARDI", "TANQUERAY", "JAMESON", "FOUR ROSES",
                "WOODFORD RESERVE", "BULLEIT", "CROWN ROYAL", "SMIRNOFF", "GREY GOOSE",
                "CAPTAIN MORGAN", "DON JULIO", "JOHNNIE WALKER", "WILD TURKEY", "ABSOLUT"],
    "wine": ["BAREFOOT", "KENDALL-JACKSON", "YELLOW TAIL", "JOSH", "19 CRIMES",
             "LA MARCA", "ROBERT MONDAVI", "CUPCAKE", "APOTHIC", "CHATEAU STE. MICHELLE",
             "SUTTER HOME", "WOODBRIDGE", "BERINGER", "SANTA MARGHERITA", "KIM CRAWFORD",
             "MEIOMI", "BOTA BOX", "OYSTER BAY", "TAYLOR FLADGATE", "CAYMUS"],
    "malt": ["COORS", "BUDWEISER", "SAMUEL ADAMS", "SIERRA NEVADA", "CORONA EXTRA",
             "HEINEKEN", "GUINNESS", "BLUE MOON", "MODELO", "STELLA ARTOIS",
             "WHITE CLAW", "TRULY", "TWISTED TEA", "MICHELOB", "YUENGLING", "PABST",
             "DOS EQUIS", "LAGUNITAS", "DOGFISH HEAD", "FOUR LOKO"],
}
TARGET_PER_TYPE = 30

DETAIL_FIELDS = ["Status", "Serial #", "Class/Type Code", "Origin Code", "Brand Name",
                 "Fanciful Name", "Type of Application", "Total Bottle Capacity",
                 "Approval Date"]


def pause():
    time.sleep(DELAY_S)


def search(page, brand):
    page.goto(f"{BASE}/publicSearchColasBasic.do")
    page.fill('input[name="searchCriteria.dateCompletedFrom"]', DATE_FROM)
    page.fill('input[name="searchCriteria.dateCompletedTo"]', DATE_TO)
    page.fill('input[name="searchCriteria.productOrFancifulName"]', brand.replace("'", "%") + "%")
    page.click('input[type=submit][value="Search"], button:has-text("Search")')
    page.wait_for_load_state()
    ids = page.eval_on_selector_all(
        "a", "as => as.map(a => a.textContent.trim()).filter(t => /^\\d{14}$/.test(t))")
    return list(dict.fromkeys(ids))


def read_detail(page, ttb_id):
    page.goto(f"{BASE}/viewColaDetails.do?action=publicDisplaySearchBasic&ttbid={ttb_id}")
    text = page.inner_text("body")
    record = {"ttb_id": ttb_id}
    for field in DETAIL_FIELDS:
        m = re.search(rf"{re.escape(field)}:[ \t]*([^\n]*)", text)
        record[field.lower().replace(" ", "_").replace("/", "_").replace("#", "no")] = (
            m.group(1).strip() if m else "")
    m = re.search(r"Principal Place of Business\):\s*\n(.*?)\n\s*Plant Registry", text, re.S)
    record["applicant"] = " | ".join(l.strip() for l in m.group(1).splitlines() if l.strip()) if m else ""
    return record


def read_form(page, ttb_id):
    page.goto(f"{BASE}/viewColaDetails.do?action=publicFormDisplay&ttbid={ttb_id}")
    boxes = page.eval_on_selector_all("input[type=checkbox]", "cs => cs.map(c => c.checked)")
    images = page.eval_on_selector_all(
        'img[alt^="Label Image"]',
        "is => is.map(i => ({type: i.alt.replace('Label Image: ', ''), src: i.src}))")
    # "Actual Dimensions: 2.29 inches W X 1.51 inches H" follows each image type, in image order
    text = page.inner_text("body")
    dims = re.findall(r"Image Type:\s*\n?\s*(.+?)\s*\n\s*Actual Dimensions:\s*([\d.]+)\s*inches W X\s*([\d.]+)\s*inches H", text)
    for img, (_, w, h) in zip(images, dims):
        img["width_in"], img["height_in"] = float(w), float(h)
    source = "imported" if len(boxes) > 1 and boxes[1] else "domestic"
    kinds = ["wine", "spirits", "malt"]
    product = next((k for k, on in zip(kinds, boxes[2:5]) if on), "")
    return source, product, images


def save_images(page, folder, images):
    saved = []
    for n, img in enumerate(images, 1):
        pause()
        # Load through the browser: the server's cert chain is incomplete and only
        # the browser's own TLS stack completes it.
        resp = page.goto(img["src"])
        if not resp or not resp.ok or not resp.headers.get("content-type", "").startswith("image"):
            continue
        ext = ".png" if "png" in resp.headers["content-type"] else ".jpg"
        name = f"{n:02d}_{re.sub(r'[^a-z]+', '_', img['type'].lower()).strip('_')}{ext}"
        (folder / name).write_bytes(resp.body())
        saved.append({"file": name, "image_type": img["type"],
                      "width_in": img.get("width_in"), "height_in": img.get("height_in")})
    return saved


def backfill_dimensions(page, path):
    """Add label dimensions to records collected before dimensions were captured."""
    record = json.loads(path.read_text())
    if all("width_in" in img for img in record["images"]):
        return
    pause()
    _, _, images = read_form(page, record["ttb_id"])
    for img in record["images"]:
        n = int(img["file"][:2]) - 1  # files are numbered in form order
        found = images[n] if n < len(images) else {}
        img["width_in"], img["height_in"] = found.get("width_in"), found.get("height_in")
    path.write_text(json.dumps(record, indent=2))


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        for kind, brands in BRANDS.items():
            got = 0
            for brand in brands:
                if got >= TARGET_PER_TYPE:
                    break
                pause()
                ids = search(page, brand)
                taken = 0
                for ttb_id in ids:
                    if taken >= PER_BRAND or got >= TARGET_PER_TYPE:
                        break
                    existing = OUT / ttb_id / "record.json"
                    if existing.exists():
                        backfill_dimensions(page, existing)
                        taken += 1; got += 1
                        continue
                    pause()
                    record = read_detail(page, ttb_id)
                    if record["status"] != "APPROVED":
                        continue
                    pause()
                    source, product, images = read_form(page, ttb_id)
                    if product != kind or not images:
                        continue
                    folder = OUT / ttb_id
                    folder.mkdir(exist_ok=True)
                    record.update(source=source, product_type=product,
                                  images=save_images(page, folder, images))
                    if not record["images"]:
                        folder.rmdir()
                        continue
                    (folder / "record.json").write_text(json.dumps(record, indent=2))
                    rows.append(record)
                    taken += 1; got += 1
                    print(f"[{kind} {got}] {ttb_id} {record['brand_name']} ({source}, {len(record['images'])} img)")
    with open(OUT / "index.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["ttb_id", "product_type", "source", "brand_name",
                                          "fanciful_name", "class_type_code", "origin_code",
                                          "approval_date", "image_count"])
        w.writeheader()
        for r in sorted((json.loads(p.read_text()) for p in OUT.glob("*/record.json")),
                        key=lambda r: (r["product_type"], r["brand_name"])):
            w.writerow({k: r.get(k, "") for k in w.fieldnames} | {"image_count": len(r["images"])})


if __name__ == "__main__":
    main()
