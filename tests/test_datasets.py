"""Rules checked against the test datasets, using known label text (no OCR yet).

- Synthetic labels: the printed text is known, so each defect must produce its expected verdict.
- Real approved COLA labels: the answer key gives the printed text. TTB approved these, so a
  "Does not match" here is our bug (RULES.md §8: target zero).

Only development-split items are used; held-out items are reserved for the final scorecard.
"""

import json
from pathlib import Path

import pytest

from app.verify import Application, Verdict, verify

DATA = Path(__file__).resolve().parent.parent / "data"
DEV = set(json.loads((DATA / "splits" / "split.json").read_text())["dev"])

# Defects that are judged from the image (stroke weight, letter height), not from text.
IMAGE_ONLY_DEFECTS = {"warning_heading_not_bold", "warning_too_small"}


def _synthetic_items():
    for path in sorted((DATA / "synthetic").glob("*/item.json")):
        item = json.loads(path.read_text())
        if item["provenance"]["base_id"] in DEV and item["provenance"]["defect"] not in IMAGE_ONLY_DEFECTS:
            yield pytest.param(item, id=item["id"])


def _label_lines_from_printed(item):
    p, a = item["printed"], item["application"]
    abv = f"{p['abv']:g}% Alc./Vol." + (f" ({p['proof']:g} Proof)" if p.get("proof") else "")
    lines = [p["brand_name"], p["class_type"], abv, p["net_contents"], a["name_address"]]
    if a["source"] == "imported":
        lines.append(f"Product of {a['country_of_origin']}")
    if p["warning_text"]:
        lines.append(p["warning_text"])
    return lines


@pytest.mark.parametrize("item", list(_synthetic_items()))
def test_synthetic_label_gets_expected_verdict(item):
    a = item["application"]
    app = Application(a["beverage_type"], a["brand_name"], a["class_type"], a["abv"], a["net_contents"],
                      a["name_address"], a["source"], a["country_of_origin"])
    report = verify(app, _label_lines_from_printed(item))
    expected = item["expected"]["overall"]
    assert report.overall.value == expected, [(f.field, f.verdict.value, f.reason) for f in report.fields if f.verdict != Verdict.PASS]
    for code in item["expected"]["findings"]:
        assert code in {f.code for f in report.fields}, f"expected finding {code}"


def _real_items():
    for path in sorted((DATA / "ground_truth").glob("*.json")):
        truth = json.loads(path.read_text())
        if f"cola_{truth['id']}" in DEV:
            yield pytest.param(truth, id=truth["id"])


@pytest.mark.parametrize("truth", list(_real_items()))
def test_real_approved_label_never_fails(truth):
    """Application = what the answer key says is printed; label = the same printed text."""
    w = truth["warning"]
    lines = [v for v in (truth["brand_name"], truth["class_type"], truth["abv_text"], truth["net_contents_text"],
                         truth["name_address_text"], truth["country_of_origin_text"], w.get("text_as_printed")) if v]
    record = json.loads((DATA / "cola_samples" / truth["id"] / "record.json").read_text())
    app = Application(truth["beverage_type"], truth["brand_name"], truth["class_type"], truth["abv"],
                      truth["net_contents_text"], truth["name_address_text"], record["source"])
    report = verify(app, lines)
    fails = [(f.field, f.reason) for f in report.fields if f.verdict == Verdict.FAIL]
    if not w["present"]:  # e.g. non-alcoholic beer: no warning required
        fails = [x for x in fails if x[0] != "warning_text"]
    assert not fails
