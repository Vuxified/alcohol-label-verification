"""Collect more approved labels from TTB's Public COLA Registry, slowly, for training and extra practice data.

Searches one completion date at a time, picks spirits, wine and malt rows from the result list by their
class/type description, and downloads each record and its label images. Each record is checked against the
final-test set (tools/dedupe_check.py rules), uploaded to the project's private S3 bucket
(s3://<bucket>/registry_pool/<ttb_id>/) and deleted locally; only data/registry_pool/index.json stays here.
The final-test set never changes: records already collected and brands that appear in the final test are skipped.

Politeness: one request every 3 seconds or slower, one session at a time, a time limit per session.
Stop rule: any HTTP error, a page that does not load in time, an access-denied / CAPTCHA / rate-limit page, or a
page without the expected content ends the session at once and writes data/registry_pool/STOPPED.txt.
No retries, no workarounds.

Usage: python tools/collect_registry_pool.py --minutes 25 --target 400
Run again later to continue; it resumes where it stopped (data/registry_pool/days_done.json).

A named batch of extra practice labels, with counts per type, kept in data/cola_samples/<ttb_id>/ as well:
    python tools/collect_registry_pool.py --batch extra2 --targets malt=45,spirits=32,wine=23 \
        --per-day malt=4,spirits=2,wine=2 --per-class malt=12,spirits=4,wine=4 --minutes 60
A batch takes no brand already collected, at most one record per applicant company, and at most --per-class
records with the same class/type description; resuming counts the batch's records in index.json.
"""

import argparse
import csv
import json
import random
import re
import time
from datetime import date, timedelta
from pathlib import Path

from PIL import Image
from playwright.sync_api import TimeoutError as PageTimeout, sync_playwright

import shutil
import subprocess

import dedupe_check
from collect_cola_samples import BASE, read_detail, read_form, save_images

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "registry_pool"
COLA = ROOT / "data" / "cola_samples"
SPLIT = ROOT / "data" / "splits" / "split.json"
BUCKET = "alcohol-label-data-739275480230"
DELAY_S = 3.0
# Real block pages, not TTB's standing "unauthorized use is prohibited" banner, which is on every page.
BLOCKED = re.compile(r"captcha|verify you are human|access denied|request (was )?rejected|too many requests|"
                     r"temporarily (blocked|unavailable)|forbidden", re.I)
MALT = re.compile(r"\b(BEER|ALE|LAGER|STOUT|PORTER|MALT|MALT BEVERAGE|PILSNER|IPA)\b")
WINE = re.compile(r"\b(WINE|CHAMPAGNE|SPARKLING|VERMOUTH|PORT|SHERRY|CIDER|MEAD|SAKE)\b")
SPIRITS = re.compile(r"\b(WHISK(E)?Y|BOURBON|VODKA|GIN|RUM|TEQUILA|MEZCAL|BRANDY|COGNAC|LIQUEUR|CORDIAL|"
                     r"SPECIALTIES|SPIRITS|SCOTCH|SCHNAPPS|ABSINTHE)\b")


class Stop(Exception):
    pass


last = [0.0]


def polite():
    wait = DELAY_S - (time.monotonic() - last[0])
    if wait > 0:
        time.sleep(wait)
    last[0] = time.monotonic()


def check(page, resp, expect=None):
    """Stop rule: raise Stop on anything that is not a normal page."""
    if resp is not None and not resp.ok:
        raise Stop(f"HTTP {resp.status} at {page.url}")
    text = page.inner_text("body")
    if BLOCKED.search(text):
        raise Stop(f"block page at {page.url}: {BLOCKED.search(text).group(0)!r}")
    if expect and expect not in text:
        raise Stop(f"expected {expect!r} missing at {page.url}")
    return text


def product_type(desc):
    d = desc.upper()
    if MALT.search(d):
        return "malt"
    if WINE.search(d):
        return "wine"
    if SPIRITS.search(d):
        return "spirits"
    return None


def search_day(page, day):
    polite()
    check(page, page.goto(f"{BASE}/publicSearchColasBasic.do"), "Search")
    s = day.strftime("%m/%d/%Y")
    page.fill('input[name="searchCriteria.dateCompletedFrom"]', s)
    page.fill('input[name="searchCriteria.dateCompletedTo"]', s)
    polite()
    page.click('input[type=submit][value="Search"], button:has-text("Search")')
    page.wait_for_load_state()
    check(page, None, "TTB ID")
    rows = page.eval_on_selector_all("table tr", "trs => trs.map(tr => [...tr.cells].map(c => c.innerText.trim()))")
    out = []
    for r in rows:
        if len(r) >= 10 and re.fullmatch(r"\d{14}", r[0]):
            out.append({"ttb_id": r[0], "brand": r[5], "fanciful": r[4], "origin": r[7], "class_desc": r[9]})
    return out


def days(seed=20261004):
    """Weekdays from 2025-01-02 to 2026-08-31, in a fixed random order (varied seasons and producers)."""
    d, end, out = date(2025, 1, 2), date(2026, 8, 31), []
    while d <= end:
        if d.weekday() < 5:
            out.append(d)
        d += timedelta(days=1)
    random.Random(seed).shuffle(out)
    return out


def heldout_brand_words():
    held = [x[5:] for x in json.loads(SPLIT.read_text())["heldout"] if x.startswith("cola_")]
    words = set()
    for i in held:
        rec = json.loads((COLA / i / "record.json").read_text())
        words.add(rec["brand_name"].split()[0].upper())
    return words


def per_type(text):
    """'malt=45,spirits=32,wine=23' -> {'malt': 45, 'spirits': 32, 'wine': 23}; missing types get 0."""
    out = {"spirits": 0, "wine": 0, "malt": 0}
    for part in filter(None, (text or "").split(",")):
        k, v = part.split("=")
        out[k.strip()] = int(v)
    return out


def company(applicant):
    """Applicant company from 'FL-I-21761 | Gulfcoast Trade, LLC | ...', without punctuation and legal suffix."""
    parts = applicant.split("|")
    name = parts[1] if len(parts) > 1 else applicant
    return re.sub(r"\b(LLC|L L C|INC|CO|CORP|CORPORATION|LTD|LIMITED|COMPANY)\b|[^A-Z0-9 ]", "", name.upper()).split()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=float, default=25)
    ap.add_argument("--target", type=int, default=400)
    ap.add_argument("--per-day", default="spirits=3,wine=3,malt=3",
                    help="rows taken per type from one day's first result page")
    ap.add_argument("--batch", help="name of a batch of extra practice labels (kept in data/cola_samples too)")
    ap.add_argument("--targets", help="with --batch: accepted records wanted per type, e.g. malt=45,spirits=32,wine=23")
    ap.add_argument("--per-class", help="with --batch: most records per class/type description, per type")
    ap.add_argument("--ids", help="a registry search export (CSV) to take records from instead of searching by day")
    args = ap.parse_args()
    PER_DAY = per_type(args.per_day)
    OUT.mkdir(parents=True, exist_ok=True)
    if (OUT / "STOPPED.txt").exists():
        print("A previous session hit the stop rule; read data/registry_pool/STOPPED.txt before running again.")
        return
    state_p = OUT / "days_done.json"
    done = set(json.loads(state_p.read_text())) if state_p.exists() else set()
    index_p = OUT / "index.json"
    index = json.loads(index_p.read_text()) if index_p.exists() else []
    have = {r["ttb_id"] for r in index} | {p.parent.name for p in COLA.glob("*/record.json")}
    banned = heldout_brand_words()
    held_h, dev_h = dedupe_check.reference_hashes()
    counts = {"spirits": 0, "wine": 0, "malt": 0}
    for r in index:
        if r.get("accepted", True) and (args.batch is None or r.get("batch") == args.batch):
            counts[r["product_type"]] = counts.get(r["product_type"], 0) + 1
    targets, per_class = per_type(args.targets), per_type(args.per_class)
    brands, companies, classes = set(), set(), {}
    if args.batch:
        for p_ in COLA.glob("*/record.json"):
            rec = json.loads(p_.read_text())
            brands.add(rec["brand_name"].strip().upper())
        brands |= {r["brand_name"].strip().upper() for r in index}
        for r in index:
            if r.get("batch") == args.batch and r["accepted"]:
                rec = json.loads((COLA / r["ttb_id"] / "record.json").read_text())
                companies.add(" ".join(company(rec["applicant"])))
                key = (product_type(r["class_desc"]), r["class_desc"])
                classes[key] = classes.get(key, 0) + 1

    def full(kind):
        if args.batch:
            return counts[kind] >= targets[kind]
        return counts[kind] >= args.target // 3 + 1

    def finished():
        if args.batch:
            return all(counts[k] >= targets[k] for k in counts)
        return sum(counts.values()) >= args.target
    log = open(OUT / "fetch_log.csv", "a", newline="")
    w = csv.writer(log)
    t_end = time.monotonic() + args.minutes * 60
    new = 0
    with sync_playwright() as p:
        page = p.chromium.launch().new_page()
        try:
            for day in ([None] if args.ids else days()):
                if time.monotonic() > t_end or finished():
                    break
                if day and day.isoformat() in done:
                    continue
                if args.ids:  # rows the owner exported from the registry's search page; no searching needed
                    rows = [{"ttb_id": x["TTB ID"].strip("'\" "), "brand": x["Brand Name"], "class_desc": x["Class/Type Desc"]}
                            for x in csv.DictReader(open(args.ids, encoding="utf-8-sig", errors="replace"))]
                else:
                    rows = search_day(page, day)
                    w.writerow([time.strftime("%H:%M:%S"), "search", day.isoformat(), len(rows)])
                took = {"spirits": 0, "wine": 0, "malt": 0}
                for r in rows:
                    kind = product_type(r["class_desc"])
                    if (not kind or (not args.ids and took[kind] >= PER_DAY[kind]) or r["ttb_id"] in have
                            or (r["brand"].split() or [""])[0].upper() in banned
                            or full(kind) or r["brand"].strip().upper() in brands
                            or (args.batch and classes.get((kind, r["class_desc"]), 0) >= per_class[kind])):
                        continue
                    if time.monotonic() > t_end:
                        break
                    polite()
                    record = read_detail(page, r["ttb_id"])
                    check(page, None, "TTB ID")
                    if record["status"] != "APPROVED":
                        continue
                    if args.batch and company(record["applicant"]) and " ".join(company(record["applicant"])) in companies:
                        continue
                    polite()
                    source, product, images = read_form(page, r["ttb_id"])
                    check(page, None)
                    if not images or full(product or kind):
                        continue
                    folder = OUT / r["ttb_id"]
                    folder.mkdir(exist_ok=True)
                    saved = save_images(page, folder, images)  # pauses 3 s before each image itself
                    last[0] = time.monotonic()  # the next request waits a full 3 s after the last image
                    if not saved:
                        folder.rmdir()
                        continue
                    record.update(source=source, product_type=product or kind, class_desc=r["class_desc"],
                                  images=saved, collected=time.strftime("%Y-%m-%d"))
                    (folder / "record.json").write_text(json.dumps(record, indent=2))
                    near_held, near_dev = dedupe_check.nearest(folder, record, held_h, dev_h)
                    why = dedupe_check.reasons(record, set(), banned, near_held, near_dev)
                    subprocess.run(["aws", "s3", "sync", str(folder), f"s3://{BUCKET}/registry_pool/{r['ttb_id']}/",
                                    "--only-show-errors"], check=True)
                    if args.batch and not why:  # keep a practice copy, in the same form as data/cola_samples
                        keep = COLA / r["ttb_id"]
                        keep.mkdir()
                        for im in saved:
                            shutil.copy(folder / im["file"], keep / im["file"])
                            dev_h.append(dedupe_check.dhash(Image.open(keep / im["file"])))
                        (keep / "record.json").write_text(json.dumps(
                            {k: v for k, v in record.items() if k not in ("class_desc", "collected")}, indent=2))
                        brands.add(record["brand_name"].strip().upper())
                        companies.add(" ".join(company(record["applicant"])))
                        key = (kind, r["class_desc"])
                        classes[key] = classes.get(key, 0) + 1
                    shutil.rmtree(folder)
                    index.append({"ttb_id": r["ttb_id"], "product_type": record["product_type"],
                                  "brand_name": record["brand_name"], "source": source,
                                  "class_desc": r["class_desc"], "images": len(saved),
                                  "nearest_heldout_hamming": near_held, "accepted": not why, "rejected_because": why}
                                 | ({"batch": args.batch} if args.batch else {}))
                    index_p.write_text(json.dumps(index, indent=1))
                    have.add(r["ttb_id"])
                    took[kind] += 1
                    if not why:
                        counts[record["product_type"]] = counts.get(record["product_type"], 0) + 1
                    new += 1
                    w.writerow([time.strftime("%H:%M:%S"), "record", r["ttb_id"], record["product_type"], len(saved)])
                    log.flush()
                    print(f"[{sum(counts.values())}] {r['ttb_id']} {record['product_type']:7s} {record['brand_name'][:40]}",
                          flush=True)
                if day:
                    done.add(day.isoformat())
                    state_p.write_text(json.dumps(sorted(done)))
        except (Stop, PageTimeout) as e:
            (OUT / "STOPPED.txt").write_text(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {e}\n")
            print("STOPPED:", e)
    log.close()
    subprocess.run(["aws", "s3", "cp", str(index_p), f"s3://{BUCKET}/registry_pool/index.json", "--only-show-errors"])
    print(f"session done: {new} new records; totals {counts}")


if __name__ == "__main__":
    main()
