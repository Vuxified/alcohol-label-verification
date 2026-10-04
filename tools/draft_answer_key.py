"""Second and third readings of every real label, to show the reviewer where the answer key may be wrong.

Two vision models on Amazon Bedrock (NVIDIA Nemotron Nano 12B v2 VL and Amazon Nova Pro) each read all images
of an application and copy the fields exactly as printed. Their answers are saved per model, then compared
with the drafted answer key field by field. A field is "agreed" when all three readings are the same after
ignoring spacing and letter case, otherwise "disputed".

The models only draft. Nothing they say becomes the answer key until a person confirms it in
tools/review_answer_key.py. Both models never approved a tampered warning in our test (Oct 4); models that did
were not chosen.

Needs AWS credentials with Bedrock access (us-east-1) and boto3 (requirements-tools.txt).

Usage:
    python tools/draft_answer_key.py              # draft missing readings, then cross-check
    python tools/draft_answer_key.py --check-only # cross-check existing readings
Writes data/answer_key_review/drafts/<model>/<ttb_id>.json and data/answer_key_review/crosscheck.json.
"""

import argparse
import io
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
TRUTH = ROOT / "data" / "ground_truth"
COLA = ROOT / "data" / "cola_samples"
REVIEW = ROOT / "data" / "answer_key_review"
DRAFTS = REVIEW / "drafts"
MODELS = {"nemotron": "nvidia.nemotron-nano-12b-v2", "nova_pro": "amazon.nova-pro-v1:0"}
FIELDS = ["brand_name", "class_type", "abv_text", "net_contents_text", "name_address_text",
          "country_of_origin_text", "warning_text"]
PROMPT = """These are the label images of one alcohol beverage product, used in a compliance check.
Copy each item below EXACTLY as it is printed on the labels: same words, capitalization and punctuation.
Do not correct, complete or normalize anything. Write [illegible] for a word you cannot read.
Use null when the item is not on any label.

Reply with only this JSON object:
{"brand_name": ..., "class_type": ..., "abv_text": ..., "net_contents_text": ...,
 "name_address_text": ..., "country_of_origin_text": ..., "warning_text": ...}

brand_name: the brand name. class_type: the class/type designation (e.g. "Kentucky Straight Bourbon Whiskey").
abv_text: the alcohol content statement. net_contents_text: the net contents (e.g. "750 mL").
name_address_text: the bottler/producer/importer name and address line.
country_of_origin_text: a country-of-origin statement, if any. warning_text: the full GOVERNMENT WARNING statement."""


def images_of(ttb_id):
    rec = json.loads((COLA / ttb_id / "record.json").read_text())
    out = []
    for im in rec["images"]:
        img = Image.open(COLA / ttb_id / im["file"]).convert("RGB")
        img.thumbnail((1600, 1600))
        b = io.BytesIO()
        img.save(b, "JPEG", quality=90)
        out.append(b.getvalue())
    return out


def ask(client, model_id, ttb_id):
    content = [{"image": {"format": "jpeg", "source": {"bytes": b}}} for b in images_of(ttb_id)]
    content.append({"text": PROMPT})
    t = time.perf_counter()
    r = client.converse(modelId=model_id, inferenceConfig={"maxTokens": 1200, "temperature": 0},
                        messages=[{"role": "user", "content": content}])
    text = "".join(c.get("text", "") for c in r["output"]["message"]["content"])
    m = re.search(r"\{.*\}", text, re.S)
    try:
        fields = json.loads(m.group(0)) if m else {}
    except json.JSONDecodeError:
        fields = {}
    return {"fields": {k: fields.get(k) for k in FIELDS}, "raw": text, "seconds": round(time.perf_counter() - t, 2)}


def draft(ids):
    import boto3
    from botocore.config import Config
    client = boto3.client("bedrock-runtime", region_name="us-east-1",
                          config=Config(read_timeout=120, retries={"max_attempts": 6, "mode": "adaptive"}))
    for name, model_id in MODELS.items():
        out = DRAFTS / name
        out.mkdir(parents=True, exist_ok=True)
        todo = [i for i in ids if not (out / f"{i}.json").exists()]

        def one(i):
            try:
                res = ask(client, model_id, i)
            except Exception as e:  # recorded, not fatal: the item simply has no reading from this model
                res = {"fields": {}, "raw": f"ERROR: {type(e).__name__}: {e}", "seconds": 0}
            (out / f"{i}.json").write_text(json.dumps({"model": model_id, **res}, indent=1, ensure_ascii=False))
            return i

        with ThreadPoolExecutor(4) as ex:
            for n, _ in enumerate(ex.map(one, todo), 1):
                if n % 10 == 0:
                    print(f"  {name}: {n}/{len(todo)}", flush=True)
        print(f"{name}: {len(todo)} drafted", flush=True)


def norm(v, field=None):
    """Comparable form of a reading. Letter case and spacing never count. Alcohol and net contents compare
    their numbers and units only ("45.2%ALC/VOL" = "45.2% Alc./Vol. (90.4 Proof)" on the % figure).
    The warning compares its body after "GOVERNMENT WARNING:" (one drafter tends to drop the heading;
    capitals of the heading are checked by the reviewer on the picture)."""
    if v is None or str(v).strip().lower() in ("", "null", "none"):
        return None
    s = re.sub(r"\s+", " ", str(v)).strip().upper()
    s = re.sub(r"\s+([.,:;%)])", r"\1", s)
    s = re.sub(r"([(])\s+", r"\1", s)
    if field == "abv_text":
        m = re.search(r"(\d+(?:\.\d+)?)\s*%", s)
        return m.group(1) if m else s
    if field == "net_contents_text":
        return re.sub(r"[^0-9A-Z.]", "", s).replace("FL.OZ", "FLOZ").replace(".", "") or None
    if field == "warning_text":
        return re.sub(r"^.*?WARNING\s*:?\s*", "", s) or None
    return s or None


def warning_words(t):
    """The legal part of a warning reading as words with their punctuation: from "(1)"/"ACCORDING" to
    "PROBLEMS" plus its punctuation, words split at line breaks ("BE- CAUSE") joined, "(1)ACCORDING" split."""
    t = re.sub(r"(\w)- (\w)", r"\1\2", t)
    t = re.sub(r"\)(?=\w)", ") ", t)
    m = re.search(r"(\(1\)|ACCORDING).*?PROBLEMS\S?", t)
    return (m.group(0) if m else t).split()


def warning_agrees(key, other):
    """A model that skipped words does not dispute the key; one that read a different word or punctuation does."""
    import difflib
    a, b = warning_words(key), warning_words(other)
    ops = difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes()
    return all(op in ("equal", "delete") for op, *_ in ops)


def agree(field, vals, source=None):
    """True when the readings support the answer key. A model that found nothing does not count against it
    (models miss small print), but the key must have found what any model found, and at least one model must
    have read the same thing. The warning must match word for word (case and spacing aside); other text
    fields compare their words, ignoring order and punctuation (token set ratio >= 90)."""
    key = norm(vals.get("answer_key"), field)
    others = [norm(v, field) for k, v in vals.items() if k != "answer_key"]
    found = [o for o in others if o is not None]
    if field == "country_of_origin_text" and source == "domestic" and key is None:
        return True  # not required on domestic labels; models tend to invent one ("USA")
    if key is None:
        return not found
    if not found:
        return False
    if field == "warning_text":
        return all(warning_agrees(key, o) for o in found)
    if field == "net_contents_text":
        return all(key in o or o in key for o in found)  # "12FLOZ" agrees with "12FLOZ355ML"
    if field == "abv_text":
        return all(o == key for o in found)
    from rapidfuzz import fuzz
    clean = lambda t: re.sub(r"[^A-Z0-9 ]+", " ", t)
    return all(fuzz.token_set_ratio(clean(o), clean(key)) >= 90 for o in found)


def key_value(gt, field):
    return gt["warning"].get("text_as_printed") if field == "warning_text" else gt.get(field)


def crosscheck(ids):
    report = {}
    for i in ids:
        gt = json.loads((TRUTH / f"{i}.json").read_text())
        source = json.loads((COLA / i / "record.json").read_text()).get("source")
        readings = {"answer_key": {f: key_value(gt, f) for f in FIELDS}}
        for name in MODELS:
            p = DRAFTS / name / f"{i}.json"
            if p.exists():
                readings[name] = json.loads(p.read_text())["fields"]
        fields = {}
        for f in FIELDS:
            vals = {src: r.get(f) for src, r in readings.items() if r}
            fields[f] = {"status": "agreed" if agree(f, vals, source) else "disputed", "readings": vals}
        report[i] = {"disputed": [f for f, x in fields.items() if x["status"] == "disputed"], "fields": fields}
    (REVIEW / "crosscheck.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    n_disp = sum(1 for r in report.values() if r["disputed"])
    per_field = {f: sum(f in r["disputed"] for r in report.values()) for f in FIELDS}
    print(f"cross-check: {len(report)} labels, {n_disp} with at least one disputed field; per field: {per_field}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()
    ids = sorted(p.stem for p in TRUTH.glob("*.json"))
    if not args.check_only:
        draft(ids)
    crosscheck(ids)


if __name__ == "__main__":
    main()
