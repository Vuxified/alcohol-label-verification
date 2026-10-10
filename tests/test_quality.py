"""Image quality hints (app/quality.py, RULES.md §6)."""

from types import SimpleNamespace

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from app.quality import picture_problems, quality_note


def label(size=(1200, 900)):
    img = Image.new("RGB", size, "white")
    d = ImageDraw.Draw(img)
    for y in range(40, size[1] - 40, 40):
        d.text((40, y), "GOVERNMENT WARNING: (1) ACCORDING TO THE SURGEON GENERAL", fill="black")
    return img


def test_sharp_label_has_no_problem():
    assert picture_problems("front.jpg", np.asarray(label())) == []


def test_heavily_blurred_label_is_called_blurry():
    blurred = label().filter(ImageFilter.GaussianBlur(4))
    assert picture_problems("front.jpg", np.asarray(blurred)) == ["front.jpg looks blurry"]


def test_small_picture_is_called_small():
    assert picture_problems("neck.jpg", np.asarray(label((500, 300)))) == ["neck.jpg is small (500×300 pixels)"]


def test_note_lists_only_the_poor_pictures():
    pics = [SimpleNamespace(name="front.jpg", full=np.asarray(label())),
            SimpleNamespace(name="back.jpg", full=np.asarray(label().filter(ImageFilter.GaussianBlur(4))))]
    assert quality_note(pics).startswith("Back.jpg looks blurry.")
    assert quality_note(pics[:1]) is None


def test_note_keeps_the_file_name_as_written():
    pics = [SimpleNamespace(name="IMG_1.JPG", full=np.asarray(label().filter(ImageFilter.GaussianBlur(4))))]
    assert quality_note(pics).startswith("IMG_1.JPG looks blurry.")


def test_a_picture_with_no_writing_is_named_not_called_blurry():
    blank = SimpleNamespace(name="blank.png", full=np.full((900, 1200, 3), 255, np.uint8))
    note = quality_note([blank], [[]])
    assert note.startswith("No writing was found on blank.png") and "blurry" not in note


def test_label_height_must_be_a_real_label_size():
    from app.typesize import parse_label_height
    assert parse_label_height("999") is None and parse_label_height("0.1") is None
    assert parse_label_height("0.5") == 0.5 and parse_label_height("24") == 24


def test_bold_heading_is_measured_thicker_than_regular_text():
    from PIL import ImageFont
    from app.bold import stroke_width
    try:
        regular = ImageFont.truetype("tools/fonts/OldStandard-Regular.ttf", 40)
        bold = ImageFont.truetype("tools/fonts/OldStandard-Bold.ttf", 40)
    except OSError:
        import pytest
        pytest.skip("test fonts not available")

    def word(font):
        img = Image.new("L", (360, 60), 255)
        ImageDraw.Draw(img).text((5, 5), "WARNING", font=font, fill=0)
        return np.asarray(img)
    assert stroke_width(word(bold)) > 1.25 * stroke_width(word(regular))
