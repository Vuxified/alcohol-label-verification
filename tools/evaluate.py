"""Run the whole app pipeline (reader + rules) over the practice (dev) labels and score it (DESIGN.md §3).

Items:
  cola  real TTB-approved labels. The application is built from the answer key (what the label says), so every
        field should match; any "Does not match" is a FALSE FAIL (the tool would be stricter than TTB).
  syn   generated labels with known mistakes (data/synthetic/*/item.json "expected"); a label with a mistake must
        never come back "Matches" overall (a FALSE PASS), and should name the right finding.
Prints per-field verdict counts, every false fail and false pass, and time per application (p50 / p95 / max).
Writes out/eval/<name>.json. The held-out (final-test) set only runs with --final: once, by the owner, on Oct 13.

Usage: python tools/evaluate.py --name dev1 [--set cola,syn] [--limit N] [--cpus 4]
       python tools/evaluate.py --name final --final      # once, by the owner (checks image checksums first)
"""

import argparse
import hashlib
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
from tools.gate import shipped_code, shipped_code_changed  # noqa: E402

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


def heldout_ids():
    """The final-test labels, after checking every image is byte-identical to the checksums frozen on 2026-10-02."""
    manifest = json.loads((DATA / "splits" / "heldout_manifest.json").read_text())
    changed = [path for files in manifest.values() for path, digest in files.items()
               if hashlib.sha256((ROOT / path).read_bytes()).hexdigest() != digest]
    if changed:
        sys.exit(f"Final-test images changed since they were frozen, so the final test would not be fair: {changed[:5]}")
    return set(json.loads((DATA / "splits" / "split.json").read_text())["heldout"])


def extra_ids(name="practice_extra"):
    """More approved labels from the registry, answer key checked against the images (practice only)."""
    return set(json.loads((DATA / "splits" / f"{name}.json").read_text())["dev"])


def label_height(images, warning_file=None):
    """The real height (inches) of the label carrying the warning, from the COLA's "Actual Dimensions"; None for
    photos, whose pictures don't show the label edge to edge."""
    sized = [im for im in images if im.get("height_in")]
    hit = (next((im for im in sized if im["file"] == warning_file), None)
           or next((im for im in sized if "back" in im["file"].lower()), None))
    return hit["height_in"] if hit else None


def cola_items(dev, kind="cola"):
    for i in sorted(x[5:] for x in dev if x.startswith("cola_")):
        rec = json.loads((DATA / "cola_samples" / i / "record.json").read_text())
        gt = json.loads((DATA / "ground_truth" / f"{i}.json").read_text())
        imported = rec.get("source") == "imported"
        app = Application(rec["product_type"] or "spirits", gt["brand_name"], gt.get("class_type"), gt.get("abv"),
                          gt.get("net_contents_text"), gt.get("name_address_text"), rec.get("source", "domestic"),
                          gt.get("country_of_origin_text") if imported else None,
                          label_height_in=label_height(rec["images"], gt["warning"].get("image_file")))
        images = [(im["file"], (DATA / "cola_samples" / i / im["file"]).read_bytes()) for im in rec["images"]]
        yield i, kind, app, images, {"overall": "approved", "warning_present": gt["warning"].get("present"),
                                     "warning_misprinted": gt["warning"].get("matches_required_text") is False}


def syn_items(dev):
    for d in sorted((DATA / "synthetic").iterdir()):
        if not d.is_dir() or "_".join(d.name.split("_")[:3]) not in dev:
            continue
        it = json.loads((d / "item.json").read_text())
        a = it["application"]
        app = Application(a["beverage_type"], a["brand_name"], a.get("class_type"), a.get("abv"), a.get("net_contents"),
                          a.get("name_address"), a.get("source", "domestic"), a.get("country_of_origin"),
                          label_height_in=label_height(it["images"]))
        images = [(im["file"], (d / im["file"]).read_bytes()) for im in it["images"]]
        yield d.name, "syn", app, images, it["expected"]


def item_dirs(folder, kind):
    """Generated test sets in the synthetic format (built from practice labels only): tampered real labels, scenes."""
    root = DATA / folder
    for d in sorted(root.iterdir()) if root.exists() else []:
        if (d / "item.json").exists():
            it = json.loads((d / "item.json").read_text())
            a = it["application"]
            base = (it.get("provenance") or {}).get("base_id", "")[5:]
            gt = DATA / "ground_truth" / f"{base}.json"
            warning_file = json.loads(gt.read_text())["warning"].get("image_file") if base and gt.exists() else None
            app = Application(a["beverage_type"], a["brand_name"], a.get("class_type"), a.get("abv"),
                              a.get("net_contents"), a.get("name_address"), a.get("source", "domestic"),
                              a.get("country_of_origin"), label_height_in=label_height(it["images"], warning_file))
            yield d.name, kind, app, [(im["file"], (d / im["file"]).read_bytes()) for im in it["images"]], it["expected"]


def pct(xs, q):
    xs = sorted(xs)
    return xs[max(0, int(round(q * len(xs))) - 1)] if xs else 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True)
    ap.add_argument("--set", default="cola,syn", help="any of cola,syn,cola2,tampered,tampered_extra,scenes,scenes_real (all but the first two: practice only)")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--cpus", type=int, default=4)
    ap.add_argument("--final", action="store_true", help="the one-time final test on the held-out labels")
    args = ap.parse_args()
    if args.final:
        if (OUT / f"{args.name}.json").exists():
            sys.exit(f"out/eval/{args.name}.json already exists: the final test is run once. Its numbers are final.")
        dev = heldout_ids()
        print("FINAL TEST on the held-out labels (images verified unchanged). Run once; report the numbers as they are.")
    else:
        dev = dev_ids()
    sets = set(args.set.split(","))
    items = []
    if "cola" in sets:
        items += list(cola_items(dev))
    if "syn" in sets:
        items += list(syn_items(dev))
    if not args.final:
        if "cola2" in sets:
            items += list(cola_items(extra_ids(), "cola2"))
        if "cola3" in sets:  # 85 fetched 2026-10-09; answer keys await the owner's review
            items += list(cola_items(extra_ids("practice_extra2"), "cola3"))
        if "tampered" in sets:
            items += list(item_dirs("tampered", "tampered"))
        if "tampered_extra" in sets:  # made from the 78 extra labels, kept apart from reader training
            items += list(item_dirs("tampered_extra", "tampered_x"))
        if "scenes" in sets:
            items += list(item_dirs("scenes", "scene"))
        if "scenes_real" in sets:  # real approved labels photographed in scenes: scored like approved labels
            items += list(item_dirs("scenes_real", "scene_real"))
    if args.limit:
        items = items[:args.limit]
    code, changed = shipped_code(), shipped_code_changed()  # which version of the app this run measures (tools/gate.py)
    reader = Reader(cpus=args.cpus)
    reader.warm_up()
    rows, counts, times = [], defaultdict(Counter), defaultdict(list)
    false_fail, false_pass, misprints = [], [], []
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
        if kind in ("cola", "cola2", "cola3", "scene_real"):
            for f in res.fields:
                if f.verdict == Verdict.FAIL and f.field == "warning_text" and expected["warning_misprinted"]:
                    misprints.append((iid, f.reason[:120]))  # TTB approved it, but the printed warning really differs
                elif f.verdict == Verdict.FAIL:
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
    print(f"== approved labels whose printed warning really differs from 27 CFR 16.21, flagged: {len(misprints)}")
    for x in misprints:
        print("  ", *x)
    print(f"== FALSE PASSES (the mistaken field said Matches): {len(false_pass)}")
    for x in false_pass:
        print("  ", *x)
    if args.final:  # six final-test labels have a near-identical twin in practice: report without them too
        twins = set(json.loads((DATA / "splits" / "heldout_twins.json").read_text())["heldout"])
        print(f"== without the {len(twins)} final-test labels that have a twin in practice: "
              f"FALSE FAILS {sum(x[0] not in twins for x in false_fail)}, FALSE PASSES {len(false_pass)}, "
              f"real labels {sum(r['kind'] == 'cola' and r['id'] not in twins for r in rows)}")
    for kind in sorted({r["kind"] for r in rows} - {"cola", "cola2", "cola3", "scene_real"}):
        planted = [r for r in rows if r["kind"] == kind and r["expected"]["overall"] != "pass"]
        named = sum(1 for r in planted if any(f["code"] in r["expected"].get("findings", []) for f in r["fields"]))
        print(f"== mistakes named correctly ({kind}): {named}/{len(planted)}")
    for kind, ts in times.items():
        print(f"== time {kind}: p50 {statistics.median(ts):.2f}s  p95 {pct(ts, .95):.2f}s  max {max(ts):.2f}s  (n={len(ts)})")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{args.name}.json").write_text(json.dumps({"rows": rows, "false_fail": false_fail, "false_pass": false_pass, "misprints": misprints,
                                                       "when": time.strftime("%Y-%m-%d %H:%M"), "code": code,
                                                       "code_changed": changed, "limit": args.limit}, indent=1))


if __name__ == "__main__":
    main()
