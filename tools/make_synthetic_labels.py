"""Render synthetic alcohol labels with known answers, including deliberate defects.

Each item is a fictional product (front + back label) rendered at 300 dpi, so physical
type size is exact, plus the application data and the verdict the verifier should give.
Defect types follow docs/RULES.md. Output: data/synthetic/<item_id>/{front.png, back.png, item.json}
and data/synthetic/manifest.csv.

Usage: python tools/make_synthetic_labels.py [--per-type 12] [--seed 7]
"""

import argparse
import csv
import json
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FONTS = Path(__file__).resolve().parent / "fonts"
OUT = ROOT / "data" / "synthetic"
DPI = 300
MM = DPI / 25.4  # pixels per millimeter

WARNING = ("GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
           "alcoholic beverages during pregnancy because of the risk of birth defects. "
           "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
           "operate machinery, and may cause health problems.")
HEADING = "GOVERNMENT WARNING:"

BRAND_WORDS = ["Copper", "Hollow", "Stone's", "Throw", "Old", "Tom", "Juniper", "Ridge", "Ember",
               "Harbor", "Lantern", "Briar", "Falcon", "Meadow", "Iron", "Creek", "Silver", "Oak",
               "Willow", "Crown", "North", "Fork", "Red", "Barn", "Black", "Anchor", "Cedar", "Bluff"]
CITIES = [("Louisville", "KY"), ("Bardstown", "KY"), ("Napa", "CA"), ("Portland", "OR"),
          ("Asheville", "NC"), ("Austin", "TX"), ("Denver", "CO"), ("Burlington", "VT")]
IMPORT_COUNTRIES = ["Ireland", "Scotland", "Mexico", "France", "Italy", "Germany", "Australia"]

TYPES = {
    "spirits": {
        "classes": ["Kentucky Straight Bourbon Whiskey", "Vodka", "London Dry Gin",
                    "Blanco Tequila", "Rye Whiskey", "Spiced Rum"],
        "abv": [40.0, 43.0, 45.0, 46.5, 50.0], "net": [("750 mL", 750), ("1.75 L", 1750),
                                                      ("375 mL", 375), ("50 mL", 50)],
        "phrase": "Distilled and bottled by",
    },
    "wine": {
        "classes": ["Cabernet Sauvignon", "Chardonnay", "Red Wine", "Pinot Noir", "Port"],
        "abv": [12.5, 13.0, 13.5, 14.5, 19.5], "net": [("750 mL", 750), ("1.5 L", 1500),
                                                      ("187 mL", 187)],
        "phrase": "Produced and bottled by",
    },
    "malt": {
        "classes": ["Lager", "India Pale Ale", "Stout", "Hard Seltzer", "Pilsner"],
        "abv": [4.2, 5.0, 5.9, 6.8, 8.0], "net": [("12 FL. OZ.", 355), ("16 FL. OZ.", 473),
                                                 ("24 FL. OZ.", 710)],
        "phrase": "Brewed and bottled by",
    },
}

# Defect -> (expected overall verdict, finding code). "pass" items are correct labels.
DEFECTS = {
    "none": ("pass", None),
    "brand_case_only": ("pass", None),                # application title case, label all caps
    "abv_wrong": ("fail", "ABV_MISMATCH"),
    "proof_wrong": ("fail", "PROOF_MISMATCH"),        # spirits only
    "net_wrong": ("fail", "NET_CONTENTS_MISMATCH"),
    "net_metric_only": ("check", "NET_CONTENTS_UNITS"),  # malt only
    "brand_extra_word": ("check", "BRAND_NAME_EXTRA_WORDS"),  # could be the bottler line; a person decides
    "class_wrong": ("check", "CLASS_TYPE_MISMATCH"),          # not found is never "Does not match"
    "warning_missing": ("check", "WARNING_MISSING"),          # may be on a side not photographed
    "warning_titlecase": ("fail", "WARNING_NOT_CAPS"),
    "warning_wording": ("fail", "WARNING_TEXT_ALTERED"),
    "warning_heading_not_bold": ("check", "WARNING_BOLD_UNCONFIRMED"),
    "warning_too_small": ("check", "WARNING_TYPE_SIZE"),
}
WORDING_EDITS = [("may cause health problems", "can cause health problems"),
                 ("alcoholic beverages during", "beverages during"),
                 ("(2) Consumption", "Consumption"),
                 ("birth defects", "birth complications")]


def font(name, px, weight=None):
    f = ImageFont.truetype(str(FONTS / name), int(px))
    if weight is not None:
        f.set_variation_by_axes([weight])
    return f


def cap_px(mm):
    """Font size in px whose capital letters are `mm` tall (cap height ~0.7 em)."""
    return mm * MM / 0.7


def min_warning_mm(net_ml):
    return 1.0 if net_ml <= 237 else 2.0 if net_ml <= 3000 else 3.0


def make_product(rng, kind):
    t = TYPES[kind]
    brand = " ".join(rng.sample(BRAND_WORDS, 2))
    imported = rng.random() < 0.3
    city, state = rng.choice(CITIES)
    net_text, net_ml = rng.choice(t["net"])
    abv = rng.choice(t["abv"])
    company = f"{brand.split()[0]} {rng.choice(['Distilling Co.', 'Cellars', 'Brewing Co.', 'Spirits LLC'])}"
    return {
        "beverage_type": kind,
        "brand_name": brand,
        "class_type": rng.choice(t["classes"]),
        "abv": abv,
        "proof": abv * 2 if kind == "spirits" else None,
        "net_contents": net_text,
        "net_contents_ml": net_ml,
        "source": "imported" if imported else "domestic",
        "country_of_origin": rng.choice(IMPORT_COUNTRIES) if imported else "United States",
        "name_address": (f"Imported by {company}, {city}, {state}" if imported
                         else f"{t['phrase']} {company}, {city}, {state}"),
    }


def apply_defect(app, defect, rng):
    """Return (label_fields, warning_spec) — what gets printed, given the true application."""
    label = dict(app)
    warn = {"text": WARNING, "heading_bold": True, "cap_mm": min_warning_mm(app["net_contents_ml"]) + 0.4}
    if defect == "brand_case_only":
        label["brand_name"] = app["brand_name"].upper()
    elif defect == "abv_wrong":
        label["abv"] = round(app["abv"] + rng.choice([-5, -1, 1, 5, 0.5]), 1)
        if label["proof"]:
            label["proof"] = label["abv"] * 2
    elif defect == "proof_wrong":
        label["proof"] = app["proof"] - 10
    elif defect == "net_wrong":
        label["net_contents"] = {"750 mL": "700 mL", "1.75 L": "1.5 L", "375 mL": "355 mL",
                                 "50 mL": "100 mL", "1.5 L": "1 L", "187 mL": "375 mL",
                                 "12 FL. OZ.": "16 FL. OZ.", "16 FL. OZ.": "12 FL. OZ.",
                                 "24 FL. OZ.": "22 FL. OZ."}[app["net_contents"]]
    elif defect == "net_metric_only":
        label["net_contents"] = f"{app['net_contents_ml']} mL"
    elif defect == "brand_extra_word":
        label["brand_name"] = app["brand_name"] + " Reserve"
    elif defect == "class_wrong":
        others = [c for c in TYPES[app["beverage_type"]]["classes"] if c != app["class_type"]]
        label["class_type"] = rng.choice(others)
    elif defect == "warning_missing":
        warn["text"] = None
    elif defect == "warning_titlecase":
        warn["text"] = WARNING.replace(HEADING, "Government Warning:")
    elif defect == "warning_wording":
        old, new = rng.choice(WORDING_EDITS)
        warn["text"] = WARNING.replace(old, new)
    elif defect == "warning_heading_not_bold":
        warn["heading_bold"] = False
    elif defect == "warning_too_small":
        warn["cap_mm"] = min_warning_mm(app["net_contents_ml"]) * 0.55
    return label, warn


def abv_line(label):
    s = f"{label['abv']:g}% Alc./Vol."
    if label.get("proof"):
        s += f" ({label['proof']:g} Proof)"
    return s


def render_front(label, rng, width_in, height_in):
    w, h = int(width_in * DPI), int(height_in * DPI)
    bg, ink = rng.choice([((246, 240, 225), (40, 30, 20)), ((20, 24, 30), (235, 215, 160)),
                          ((250, 250, 250), (25, 25, 25)), ((120, 20, 30), (250, 240, 220))])
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)
    d.rectangle([int(0.08 * DPI)] * 2 + [w - int(0.08 * DPI), h - int(0.08 * DPI)], outline=ink, width=6)
    brand_font = rng.choice([("Cinzel[wght].ttf", 700), ("PlayfairDisplay[wght].ttf", 800),
                             ("BebasNeue-Regular.ttf", None), ("Oswald[wght].ttf", 600)])
    y = int(h * 0.22)
    for text, f in [(label["brand_name"], font(brand_font[0], cap_px(7), brand_font[1])),
                    (label["class_type"], font("OldStandard-Regular.ttf", cap_px(3.2))),
                    (abv_line(label), font("LibreFranklin[wght].ttf", cap_px(2.8), 500)),
                    (label["net_contents"], font("LibreFranklin[wght].ttf", cap_px(2.8), 500))]:
        tw = d.textlength(text, font=f)
        if tw > w * 0.9:  # shrink long lines to fit
            f = font(f.path, f.size * (w * 0.9) / tw, brand_font[1] if f.path.endswith(brand_font[0]) else None)
            tw = d.textlength(text, font=f)
        d.text(((w - tw) / 2, y), text, font=f, fill=ink)
        y += int(f.size * 1.5)
    return img


def render_back(label, warn, rng, width_in):
    w = int(width_in * DPI)
    margin = int(0.15 * DPI)
    body = font("LibreFranklin[wght].ttf", cap_px(warn["cap_mm"]), 400)
    heading = font("LibreFranklin[wght].ttf", cap_px(warn["cap_mm"]), 700 if warn["heading_bold"] else 400)
    small = font("LibreFranklin[wght].ttf", cap_px(2.2), 400)
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    usable = w - 2 * margin

    def text_width(line, first):
        """Pixel width, drawing the heading in its own (possibly bold) font."""
        if first and line.lower().startswith("government warning:"):
            return probe.textlength(line[:len(HEADING)], font=heading) + probe.textlength(line[len(HEADING):], font=body)
        return probe.textlength(line, font=body)

    def wrap(text, measure):
        """Greedy word wrap by measured pixel width, so no line runs past the edge."""
        out, line = [], ""
        for word in text.split():
            candidate = f"{line} {word}".strip()
            if line and measure(candidate, not out) > usable:
                out.append(line)
                line = word
            else:
                line = candidate
        return out + ([line] if line else [])

    lines = wrap(label["name_address"], lambda ln, _: probe.textlength(ln, font=small))
    if label["source"] == "imported":
        lines.append(f"Product of {label['country_of_origin']}")
    lines.append(label["net_contents"])
    warn_lines = wrap(warn["text"], text_width) if warn["text"] else []
    h = margin * 2 + len(lines) * int(small.size * 1.6) + len(warn_lines) * int(body.size * 1.3) + int(0.3 * DPI)
    img = Image.new("RGB", (w, h), (250, 248, 242))
    d = ImageDraw.Draw(img)
    y = margin
    for line in lines:
        d.text((margin, y), line, font=small, fill=(30, 30, 30))
        y += int(small.size * 1.6)
    y += int(0.15 * DPI)
    for i, line in enumerate(warn_lines):
        x = margin
        if i == 0 and line.lower().startswith("government warning:"):
            head = line[:len(HEADING)]
            d.text((x, y), head, font=heading, fill=(0, 0, 0))
            x += d.textlength(head, font=heading)
            line = line[len(HEADING):]
        d.text((x, y), line, font=body, fill=(0, 0, 0))
        y += int(body.size * 1.3)
    return img


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--per-type", type=int, default=12, help="base products per beverage type")
    ap.add_argument("--seed", type=int, default=7)
    args = ap.parse_args()
    rng = random.Random(args.seed)
    OUT.mkdir(parents=True, exist_ok=True)
    rows = []
    for kind in TYPES:
        for n in range(args.per_type):
            app = make_product(rng, kind)
            defects = [d for d in DEFECTS
                       if not (d == "proof_wrong" and kind != "spirits")
                       and not (d == "net_metric_only" and kind != "malt")]
            # every product gets a clean version plus three defect variants
            for defect in ["none"] + rng.sample([d for d in defects if d != "none"], 3):
                item_id = f"syn_{kind}_{n:02d}_{defect}"
                label, warn = apply_defect(app, defect, rng)
                width_in, height_in = rng.choice([(3.5, 4.0), (4.0, 3.5), (3.0, 4.5)])
                folder = OUT / item_id
                folder.mkdir(exist_ok=True)
                render_front(label, rng, width_in, height_in).save(folder / "front.png", dpi=(DPI, DPI))
                back = render_back(label, warn, rng, width_in)
                back.save(folder / "back.png", dpi=(DPI, DPI))
                overall, code = DEFECTS[defect]
                application = {k: v for k, v in app.items() if k != "net_contents_ml"}
                application.update(label_width_in=width_in)
                item = {
                    "id": item_id,
                    "images": [{"file": "front.png", "image_type": "Brand (front)",
                                "width_in": width_in, "height_in": height_in},
                               {"file": "back.png", "image_type": "Back",
                                "width_in": width_in, "height_in": round(back.height / DPI, 2)}],
                    "source": {"type": "synthetic", "license": "generated for this project"},
                    "application": application,
                    "printed": {k: label[k] for k in ("brand_name", "class_type", "abv", "proof", "net_contents")}
                               | {"warning_text": warn["text"], "warning_heading_bold": warn["heading_bold"],
                                  "warning_cap_mm": round(warn["cap_mm"], 2)},
                    "expected": {"overall": overall, "findings": [code] if code else []},
                    "provenance": {"base_id": f"syn_{kind}_{n:02d}", "defect": defect, "seed": args.seed},
                }
                (folder / "item.json").write_text(json.dumps(item, indent=2))
                rows.append({"id": item_id, "beverage_type": kind, "base_id": item["provenance"]["base_id"],
                             "defect": defect, "expected": overall, "finding": code or ""})
    with open(OUT / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    print(f"wrote {len(rows)} items to {OUT}")


if __name__ == "__main__":
    main()
