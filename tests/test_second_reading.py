"""A different alcohol content or net contents is "Does not match" only when a second, independent reader sees the
same different number at that spot (RULES.md §1: never fail a real label on one misread). Crazy Turtle (cola2,
TTB ID 26205001000228) prints 6.5%, but the word reader read "5.5%" in its display font."""

import numpy as np

from app.pipeline import confirm_differences
from app.verify import Application, FieldResult, Verdict

FRAME = np.full((200, 600, 3), 255, np.uint8)
WORDS = [[("CRAZY", 0.9, (10, 10, 200, 50)), ("5.5%", 0.6, (10, 100, 90, 130)), ("ALC/VOL", 0.9, (100, 100, 220, 130)),
          ("16", 0.9, (300, 100, 330, 130)), ("FL", 0.9, (335, 100, 360, 130)), ("OZ", 0.9, (365, 100, 400, 130))]]
APP = Application("malt", "Crazy Turtle", abv=6.5, net_contents="12 FL OZ")


def abv_fail():
    return FieldResult("abv", Verdict.FAIL, 'Label says "5.5% ALC/VOL". Application says 6.5%.', code="ABV_MISMATCH",
                       found="5.5% ALC/VOL")


def net_fail():
    return FieldResult("net_contents", Verdict.FAIL, 'Label says "16 FL OZ". Application says "12 FL OZ".',
                       code="NET_CONTENTS_MISMATCH", found="16 FL OZ")


def reader(text):
    seen = []

    def read(crop):
        seen.append(crop.shape)
        return text
    read.seen = seen
    return read


def test_second_reader_sees_the_application_number_so_please_check():
    [f] = confirm_differences([abv_fail()], [FRAME], WORDS, APP, read=reader("6.5% ALC/VOL"))
    assert f.verdict == Verdict.CHECK and f.code == "ABV_MISMATCH"
    assert "6.5% ALC/VOL" in f.reason and "second" in f.reason


def test_second_reader_sees_the_same_different_number_so_does_not_match():
    [f] = confirm_differences([abv_fail()], [FRAME], WORDS, APP, read=reader("5.5% ALC/VOL"))
    assert f.verdict == Verdict.FAIL


def test_second_reader_sees_nothing_so_please_check():
    [f] = confirm_differences([abv_fail()], [FRAME], WORDS, APP, read=reader(""))
    assert f.verdict == Verdict.CHECK


def test_second_reader_sees_a_third_number_so_please_check():
    [f] = confirm_differences([abv_fail()], [FRAME], WORDS, APP, read=reader("8.5% ALC/VOL"))
    assert f.verdict == Verdict.CHECK


def test_net_contents_too():
    [f] = confirm_differences([net_fail()], [FRAME], WORDS, APP, read=reader("16 FL OZ"))
    assert f.verdict == Verdict.FAIL
    [f] = confirm_differences([net_fail()], [FRAME], WORDS, APP, read=reader("12 FL OZ"))
    assert f.verdict == Verdict.CHECK


def test_spot_not_found_on_the_picture_so_please_check():
    f = FieldResult("abv", Verdict.FAIL, 'Label says "13% ALCOHOL BY VOLUME".', code="ABV_MISMATCH",
                    found="13% ALCOHOL BY VOLUME")
    [g] = confirm_differences([f], [FRAME], WORDS, APP, read=reader("13% ALCOHOL BY VOLUME"))
    assert g.verdict == Verdict.CHECK


def test_other_results_untouched_and_no_second_reading_needed():
    read = reader("anything")
    fields = [FieldResult("abv", Verdict.PASS, "ok"), FieldResult("brand_name", Verdict.FAIL, "different", code="X")]
    assert confirm_differences(fields, [FRAME], WORDS, APP, read=read) == fields
    assert read.seen == []


def test_crop_is_enlarged_for_the_second_reader():
    read = reader("5.5% ALC/VOL")
    confirm_differences([abv_fail()], [FRAME], WORDS, APP, read=read)
    assert read.seen and read.seen[0][0] >= 60  # small print is enlarged before Tesseract reads it
