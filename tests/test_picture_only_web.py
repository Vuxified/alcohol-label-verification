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
    assert "Every required statement we looked for is on the label" in page.text
    assert page.text.count("On the label") >= 4  # class, alcohol, net contents, bottler: found, not "Matches"
    assert "Does not match" not in page.text


def test_beverage_type_is_still_needed_to_check(client):
    page = client.post("/check", data={}, files=files())
    assert page.status_code == 400


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
