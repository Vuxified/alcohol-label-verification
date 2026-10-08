"""Run the whole app pipeline (reader + rules) over the practice (dev) labels and score it (DESIGN.md §3).

Items:
  cola  real TTB-approved labels. The application is built from the answer key (what the label says), so every
        field should match; any "Does not match" is a FALSE FAIL (the tool would be stricter than TTB).
  syn   generated labels with known mistakes (data/synthetic/*/item.json "expected"); a label with a mistake must
        never come back "Matches" overall (a FALSE PASS), and should name the right finding.
Prints per-field verdict counts, every false fail and false pass, and time per application (p50 / p95 / max).
Writes out/eval/<name>.json. The held-out (final-test) set is refused: it is run once, by the owner, on Oct 13.

Usage: python tools/evaluate.py --name dev1 [--set cola,syn] [--limit N] [--cpus 4]
"""

import argparse
import json
import statistics
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ocr.reader import Reader  # noqa: E402
from app.pipeline import check_application  # noqa: E402
from app.verify import Application, Verdict  # noqa: E402

DATA = ROOT / "data"
# The field each planted mistake belongs to: that field must never come back "Matches" (a false pass hidden by an
# unrelated "Please check" elsewhere on the label still counts).
FIELD_OF = {"ABV": "abv", "PROOF": "proof", "NET_CONTENTS": "net_contents", "BRAND_NAME": "brand_name",
            "CLASS_TYPE": "class_type", "WARNING_NOT_CAPS": "warning_caps", "WARNING_BOLD": "warning_bold",
            "WARNING_TYPE_SIZE": "warning_size", "WARNING": "warning_text"}


def field_of(code):
    return next(f for prefix, f in FIELD_OF.items() if code.startswith(prefix))
OUT = ROOT / "out" / "eval"


def dev_ids():
    return set(json.loads((DATA / "splits" / "split.json").read_text())["dev"])


def cola_items(dev):
    for i in sorted(x[5:] for x in dev if x.startswith("cola_")):
        rec = json.loads((DATA / "cola_samples" / i / "record.json").read_text())
        gt = json.loads((DATA / "ground_truth" / f"{i}.json").read_text())
        imported = rec.get("source") == "imported"
        app = Application(rec["product_type"] or "spirits", gt["brand_name"], gt.get("class_type"), gt.get("abv"),
                          gt.get("net_contents_text"), gt.get("name_address_text"), rec.get("source", "domestic"),
                          gt.get("country_of_origin_text") if imported else None)
        images = [(im["file"], (DATA / "cola_samples" / i / im["file"]).read_bytes()) for im in rec["images"]]
        yield i, "cola", app, images, {"overall": "approved", "warning_present": gt["warning"].get("present")}


def syn_items(dev):
    for d in sorted((DATA / "synthetic").iterdir()):
        if not d.is_dir() or "_".join(d.name.split("_")[:3]) not in dev:
            continue
        it = json.loads((d / "item.json").read_text())
        a = it["application"]
        app = Application(a["beverage_type"], a["brand_name"], a.get("class_type"), a.get("abv"), a.get("net_contents"),
                          a.get("name_address"), a.get("source", "domestic"), a.get("country_of_origin"))
        images = [(im["file"], (d / im["file"]).read_bytes()) for im in it["images"]]
        yield d.name, "syn", app, images, it["expected"]


def pct(xs, q):
    xs = sorted(xs)
    return xs[max(0, int(round(q * len(xs))) - 1)] if xs else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--set", default="cola,syn")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cpus", type=int, default=4)
    args = ap.parse_args()
    dev = dev_ids()
    items = []
    if "cola" in args.set:
        items += list(cola_items(dev))
    if "syn" in args.set:
        items += list(syn_items(dev))
    if args.limit:
        items = items[:args.limit]
    reader = Reader(cpus=args.cpus)
    reader.warm_up()
    rows, counts, times = [], defaultdict(Counter), defaultdict(list)
    false_fail, false_pass = [], []
    for n, (iid, kind, app, images, expected) in enumerate(items, 1):
        res = check_application(reader, app, images)
        verdicts = {f.field: f.verdict.value for f in res.fields}
        for f in res.fields:
            counts[(kind, f.field)][f.verdict.value] += 1
        times[kind].append(res.seconds)
        row = {"id": iid, "kind": kind, "overall": res.overall.value, "seconds": res.seconds,
               "fields": [{"field": f.field, "verdict": f.verdict.value, "code": f.code, "reason": f.reason}
                          for f in res.fields],
               "passes": res.reading.passes, "dropped": res.reading.dropped, "turns": res.reading.turns,
               "expected": expected}
        rows.append(row)
        if kind == "cola":
            for f in res.fields:
                if f.verdict == Verdict.FAIL:
                    false_fail.append((iid, f.field, f.code, f.reason[:120]))
        elif expected["overall"] != "pass":
            for code in expected.get("findings", []):
                if verdicts.get(field_of(code)) == Verdict.PASS.value:
                    false_pass.append((iid, field_of(code), code))
        print(f"[{n}/{len(items)}] {iid} {kind} {res.overall.value} {res.seconds:.2f}s "
              f"warning={verdicts.get('warning_text')} {' '.join(res.reading.passes)}", flush=True)
    print("\n== verdicts per field (pass / check / fail / n/a)")
    for (kind, fld), c in sorted(counts.items()):
        print(f"  {kind:4s} {fld:18s} {c['pass']:3d} / {c['check']:3d} / {c['fail']:3d} / {c['n/a']:3d}")
    print(f"\n== FALSE FAILS on approved labels: {len(false_fail)}")
    for x in false_fail:
        print("  ", *x)
    print(f"== FALSE PASSES (the mistaken field said Matches): {len(false_pass)}")
    for x in false_pass:
        print("  ", *x)
    syn = [r for r in rows if r["kind"] == "syn" and r["expected"]["overall"] != "pass"]
    named = sum(1 for r in syn if any(f["code"] in r["expected"].get("findings", []) for f in r["fields"]))
    print(f"== mistakes named correctly: {named}/{len(syn)}")
    for kind, ts in times.items():
        print(f"== time {kind}: p50 {statistics.median(ts):.2f}s  p95 {pct(ts, .95):.2f}s  max {max(ts):.2f}s  (n={len(ts)})")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.name}.json").write_text(json.dumps({"rows": rows, "false_fail": false_fail, "false_pass": false_pass,
                                                       "when": time.strftime("%Y-%m-%d %H:%M")}, indent=1))


if __name__ == "__main__":
    main()
