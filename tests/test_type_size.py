"""Warning type size (27 CFR 16.22(b)): measured from the picture when the agent gives the label's height.

The pictures here are drawn at a known size, so the true letter height is known: 300 dots per inch, label 4 in tall.
"""

from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from app.typesize import min_height_mm, parse_label_height, size_field
from app.verify import Application, Verdict

DPI = 300
FONT = Path(__file__).resolve().parents[1] / "tools" / "fonts" / "LibreFranklin[wght].ttf"


def label(cap_mm, height_in=4.0, width_in=3.0):
    """A label with the warning set so its capital letters are cap_mm tall -> (picture, words with boxes)."""
    img = Image.new("RGB", (int(width_in * DPI), int(height_in * DPI)), "white")
    d = ImageDraw.Draw(img)
    cap_px = cap_mm / 25.4 * DPI
    font = ImageFont.truetype(str(FONT), 200)
    font = ImageFont.truetype(str(FONT), max(4, round(200 * cap_px / (font.getbbox("H")[3] - font.getbbox("H")[1]))))
    words, x, y = [], 40, int(height_in * DPI * 0.6)
    for w in "GOVERNMENT WARNING: (1) According to the Surgeon General,".split():
        x0, y0, x1, y1 = d.textbbox((x, y), w, font=font)
        d.text((x, y), w, fill="black", font=font)
        pad = 0.25 * (y1 - y0)  # the text finder's boxes are a little larger than the ink
        words.append((w, 0.99, (x0 - pad, y0 - pad, x1 + pad, y1 + pad)))
        x = x1 + font.size // 3
    return np.asarray(img), words


def app(net="750 mL", height="4", beverage="spirits"):
    return Application(beverage, "Brand", net_contents=net, label_height_in=parse_label_height(height))


@pytest.mark.parametrize("ml, mm", [(50, 1), (237, 1), (237.5, 2), (750, 2), (3000, 2), (3001, 3), (19000, 3)])
def test_minimum_by_container_size(ml, mm):
    assert min_height_mm(ml) == mm


@pytest.mark.parametrize("typed, inches", [("4", 4.0), ("4.5", 4.5), (" 3.25 in", 3.25), ('5"', 5.0), ("5 inches", 5.0),
                                           ("4,5", 4.5), ("", None), ("tall", None), ("0", None), ("-3", None)])
def test_label_height_typed(typed, inches):
    assert parse_label_height(typed) == inches


def test_big_enough_matches():
    img, words = label(2.4)
    f = size_field([img], [words], app())
    assert f.field == "warning_size" and f.verdict == Verdict.PASS, f.reason


def test_too_small_is_please_check_never_does_not_match():
    img, words = label(1.1)  # the planted mistake in the generated labels: 55% of the 2 mm minimum
    f = size_field([img], [words], app())
    assert f.verdict == Verdict.CHECK and f.code == "WARNING_TYPE_SIZE", f.reason
    assert "2 mm" in f.reason and "16.22" in f.reason


def test_just_over_the_minimum_is_not_confirmed():
    img, words = label(2.0)  # within measuring error of 2 mm: never a Matches that might be false
    assert size_field([img], [words], app()).verdict != Verdict.PASS


def test_capitals_between_the_two_readings_of_the_rule_are_not_checked():
    # 16.22 sets a minimum type size; capitals are about 70% of the type size. Capitals of 1.5 mm are too small if
    # the rule means letter height, and fine if it means type size: a picture cannot settle it, so not checked,
    # with the measured size shown.
    img, words = label(1.5)
    f = size_field([img], [words], app())
    assert f.verdict == Verdict.NOT_APPLICABLE and "1.5 mm" in f.reason


def test_small_container_has_a_lower_minimum():
    img, words = label(1.4)
    assert size_field([img], [words], app(net="200 mL")).verdict == Verdict.PASS


def test_measure_uses_the_typed_height():
    img, words = label(2.4)  # the same picture said to be half / twice as tall: the letters are half / twice as big
    assert size_field([img], [words], app(height="1.6")).verdict == Verdict.CHECK
    assert size_field([img], [words], app(height="8")).verdict == Verdict.PASS


def test_not_checked_without_label_height():
    img, words = label(1.1)
    f = size_field([img], [words], app(height=""))
    assert f.verdict == Verdict.NOT_APPLICABLE and "height" in f.reason


def test_not_checked_without_net_contents():
    img, words = label(1.1)
    assert size_field([img], [words], app(net=None)).verdict == Verdict.NOT_APPLICABLE


def test_not_checked_when_the_heading_is_not_found():
    img, words = label(2.4)
    words = [w for w in words if w[0] != "WARNING:"]
    assert size_field([img], [words], app()).verdict == Verdict.NOT_APPLICABLE


def test_form_takes_the_label_height():
    from app.web.main import _application
    form = {"beverage_type": "wine", "brand_name": "Old Tom", "abv": "", "label_height": "4.5 in"}
    assert _application(form).label_height_in == 4.5
    assert _application({**form, "label_height": ""}).label_height_in is None
