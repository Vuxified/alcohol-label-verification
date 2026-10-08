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
