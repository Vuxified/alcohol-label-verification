"""Picture-only on the web: the form works without a brand, reading on upload returns what the label says, and a
picture-only result says "On the label", never "Matches"."""

import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.web.main import app, state

SAMPLE = Path(__file__).resolve().parent.parent / "data" / "synthetic" / "syn_spirits_00_none"


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        for _ in range(120):
            if state["ready"]:
                break
            time.sleep(0.25)
        yield c


def files():
    return [("images", (n, (SAMPLE / n).read_bytes(), "image/png")) for n in ("front.png", "back.png")]


def test_fill_in_from_the_label(client):
    v = client.post("/api/read", files=files()).json()
    assert v["beverage_type"] == "spirits"
    assert v["abv"] == "50" and v["net_contents"].replace(" ", "").lower() == "750ml"
    assert "gin" in v["class_type"].lower()
    assert "brand_name" not in v  # brands are mostly logos: the agent types it
    assert "bottled by" in v["name_address"].lower()


def test_fill_in_needs_pictures(client):
    assert client.post("/api/read", data={}).status_code == 400


def test_check_with_pictures_only(client):
    page = client.post("/check", data={"beverage_type": "spirits"}, files=files())
    assert page.status_code == 200
    assert "One item needs your attention: the brand name." in page.text
    assert page.text.count("On the label") >= 4  # class, alcohol, net contents, bottler: found, not "Matches"
    assert "Does not match" not in page.text


def test_type_of_product_is_told_from_the_label(client):
    page = client.post("/check", data={}, files=files())  # nothing chosen: the gin label says it's spirits
    assert page.status_code == 200 and "Type of product: distilled spirits, told from the label." in page.text
    assert 'section-5.65"' in page.text  # spirits rules (and citations) were used


def test_type_of_product_asked_for_when_the_label_does_not_show_it(client):
    from PIL import Image
    import io
    blank = io.BytesIO()
    Image.new("RGB", (800, 600), "white").save(blank, "PNG")
    page = client.post("/check", data={}, files=[("images", ("blank.png", blank.getvalue(), "image/png"))])
    assert page.status_code == 400 and "couldn&#39;t tell the type of product" in page.text


def test_stylesheet_link_changes_with_the_file(client):
    # Browsers keep an old stylesheet; the link carries the file's fingerprint so a new look is fetched at once.
    import hashlib
    from pathlib import Path
    css = (Path(__file__).resolve().parent.parent / "app/web/static/app.css").read_bytes()
    assert f'/static/app.css?v={hashlib.sha256(css).hexdigest()[:10]}' in client.get("/").text


def test_pictures_up_to_20_mb_are_taken():
    # Phone photos can be large; up to 20 MB each is accepted, anything bigger gets a plain message.
    import io
    import numpy as np
    from PIL import Image
    from app.web.main import _check_file
    big = io.BytesIO()
    Image.fromarray(np.random.default_rng(0).integers(0, 256, (2500, 2500, 3), dtype=np.uint8)).save(big, "PNG")
    assert 15 * 1024 * 1024 < len(big.getvalue()) < 20 * 1024 * 1024 and _check_file("big.png", big.getvalue()) is None
    assert "The limit is 20 MB" in _check_file("huge.png", b"\0" * (20 * 1024 * 1024 + 1))


def test_every_result_row_names_its_rule(client):
    # Spirits: each row cites its 27 CFR section and links to it on eCFR.
    page = client.post("/check", data={"sample": "match"}).text
    for sec in ("5.64", "5.141", "5.65", "5.70", "5.66", "16.21", "16.22"):
        assert f'href="https://www.ecfr.gov/current/title-27/section-{sec}"' in page, sec


def test_rule_follows_the_product_type():
    from app.web import copy
    assert [copy.rule("brand_name", b) for b in ("spirits", "wine", "malt")] == ["5.64", "4.33", "7.64"]
    assert copy.rule("warning_caps", "wine") == "16.22"
    assert copy.rule("abv_minimum", "spirits", "45% meets the 40% minimum for gin (27 CFR 5.144).") == "5.144"
    assert copy.rule("abv_minimum", "spirits", "no citation here") is None


def test_brand_read_by_ai_is_shown_on_the_label(client, monkeypatch):
    # Nothing typed: the AI reading is shown as what the label says ("On the label"), never "Matches".
    from app import brand_ai
    monkeypatch.setattr(brand_ai, "read_brand", lambda images: "OLD LANTERN")
    assert client.post("/api/read", files=files()).json()["brand_name"] == "OLD LANTERN"
    page = client.post("/check", data={"beverage_type": "spirits"}, files=files())
    assert "OLD LANTERN" in page.text and "(read by AI; check the spelling)" in page.text
    assert "Every required statement we looked for is on the label." in page.text


def test_brand_typed_is_never_given_to_the_ai(client, monkeypatch):
    from app import brand_ai
    called = []
    monkeypatch.setattr(brand_ai, "read_brand", lambda images: called.append(1) or "SOMETHING ELSE")
    client.post("/check", data={"beverage_type": "spirits", "brand_name": "Old Lantern"}, files=files())
    assert not called


def test_ai_not_reachable_leaves_the_brand_to_check(client, monkeypatch):
    # Off (no LABEL_BRAND_MODEL) or failing (firewall, timeout): as before, the agent confirms the brand.
    from app import brand_ai
    monkeypatch.setattr(brand_ai, "MODEL", "us.amazon.nova-pro-v1:0")
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x"); monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_ENDPOINT_URL_BEDROCK_RUNTIME", "http://127.0.0.1:9")
    assert brand_ai.read_brand(files_bytes()) is None
    assert "brand_name" not in client.post("/api/read", files=files()).json()


def files_bytes():
    return [(n, (SAMPLE / n).read_bytes()) for n in ("front.png",)]
