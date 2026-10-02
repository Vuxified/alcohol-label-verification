"""Collect real-world bottle/can photos from Open Food Facts (crowd-sourced phone photos).

COLA registry images are clean flat artwork; these photos add glare, angles and curved
labels. Saves photos plus product metadata to data/real_photos/<barcode>/.
Images are licensed CC BY-SA by Open Food Facts contributors; see data/real_photos/LICENSE.md.

Usage: python tools/collect_openfoodfacts_photos.py
"""

import json
import re
import time
from pathlib import Path

import requests

OUT = Path(__file__).resolve().parent.parent / "data" / "real_photos"
API = "https://world.openfoodfacts.org/api/v2/search"
HEADERS = {"User-Agent": "alcohol-label-verification-prototype/0.1 (test data collection)"}
SEARCH_DELAY_S = 8  # OFF asks for at most ~10 search requests per minute
PER_TYPE = 15
CATEGORIES = {"malt": "en:beers", "wine": "en:wines", "spirits": "en:spirits"}
FIELDS = "code,product_name,brands,quantity,categories_tags,countries_tags,image_front_url,selected_images"


def search(category, page):
    params = {"categories_tags": category, "countries_tags_en": "united-states",
              "fields": FIELDS, "page_size": 50, "page": page, "sort_by": "unique_scans_n"}
    for attempt in range(5):  # the search API returns 503 when busy; back off and retry
        resp = requests.get(API, params=params, headers=HEADERS, timeout=60)
        if resp.status_code != 503:
            break
        time.sleep(30 * (attempt + 1))
    resp.raise_for_status()
    return resp.json().get("products", [])


def photo_urls(product):
    """Front photo plus any label/ingredients photo (often the back label)."""
    urls = {}
    if product.get("image_front_url"):
        urls["front"] = product["image_front_url"]
    for kind in ("ingredients", "packaging", "nutrition"):
        display = product.get("selected_images", {}).get(kind, {}).get("display", {})
        if display:
            urls[kind] = next(iter(display.values()))
    # API returns 400px previews; OCR needs the full-resolution original
    return {k: re.sub(r"\.\d+\.jpg$", ".full.jpg", u) for k, u in urls.items()}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for kind, category in CATEGORIES.items():
        got, page = 0, 1
        while got < PER_TYPE and page <= 3:
            products = search(category, page)
            time.sleep(SEARCH_DELAY_S)
            page += 1
            for product in products:
                if got >= PER_TYPE:
                    break
                urls = photo_urls(product)
                if "front" not in urls or not product.get("code"):
                    continue
                folder = OUT / product["code"]
                if (folder / "record.json").exists():
                    got += 1
                    continue
                folder.mkdir(exist_ok=True)
                saved = []
                for name, url in urls.items():
                    img = requests.get(url, headers=HEADERS, timeout=60)
                    time.sleep(1)
                    if img.ok and img.headers.get("content-type", "").startswith("image"):
                        (folder / f"{name}.jpg").write_bytes(img.content)
                        saved.append({"file": f"{name}.jpg", "source_url": url})
                record = {"barcode": product["code"], "product_type": kind,
                          "product_name": product.get("product_name", ""),
                          "brands": product.get("brands", ""), "quantity": product.get("quantity", ""),
                          "source": f"https://world.openfoodfacts.org/product/{product['code']}",
                          "license": "CC BY-SA (Open Food Facts contributors)", "images": saved}
                (folder / "record.json").write_text(json.dumps(record, indent=2))
                got += 1
                print(f"[{kind} {got}] {product['code']} {record['brands']} — {record['product_name']} ({len(saved)} img)")

    (OUT / "LICENSE.md").write_text(
        "Photos in this folder come from Open Food Facts (https://world.openfoodfacts.org) "
        "and are licensed CC BY-SA by their contributors. Each record.json links to its product page.\n")


if __name__ == "__main__":
    main()
