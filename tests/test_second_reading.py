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


# The same for a different number or product word in a text field: one misread ("12" read as "13") must not fail
# a correct label, so the difference stands only when the second reader sees it too.
WORDS_T = [[("KENTUCKY", 0.9, (10, 10, 120, 40)), ("STRAIGHT", 0.9, (130, 10, 240, 40)), ("RYE", 0.6, (250, 10, 300, 40)),
            ("WHISKEY", 0.9, (310, 10, 420, 40)), ("AGED", 0.9, (10, 100, 80, 130)), ("13", 0.6, (90, 100, 120, 130)),
            ("YEARS", 0.9, (130, 100, 210, 130))]]
APP_T = Application("spirits", "Old Tom", class_type="Kentucky Straight Bourbon Whiskey", fanciful_name="Aged 12 Years")


def test_a_different_number_in_a_name_needs_the_second_reader_too():
    f = FieldResult("fanciful_name", Verdict.FAIL, 'Label shows "AGED 13 YEARS".', code="FANCIFUL_NAME_NUMBER_DIFFERS",
                    found="AGED 13 YEARS")
    assert confirm_differences([f], [FRAME], WORDS_T, APP_T, read=reader("AGED 13 YEARS"))[0].verdict == Verdict.FAIL
    assert confirm_differences([f], [FRAME], WORDS_T, APP_T, read=reader("AGED 12 YEARS"))[0].verdict == Verdict.CHECK


def test_a_different_product_word_needs_the_second_reader_too():
    f = FieldResult("class_type", Verdict.FAIL, 'Label shows "KENTUCKY STRAIGHT RYE WHISKEY".',
                    code="CLASS_TYPE_WORD_DIFFERS", found="KENTUCKY STRAIGHT RYE WHISKEY")
    same = reader("KENTUCKY STRAIGHT RYE WHISKEY")
    assert confirm_differences([f], [FRAME], WORDS_T, APP_T, read=same)[0].verdict == Verdict.FAIL
    other = reader("KENTUCKY STRAIGHT BOURBON WHISKEY")
    assert confirm_differences([f], [FRAME], WORDS_T, APP_T, read=other)[0].verdict == Verdict.CHECK


def brand_near():
    return FieldResult("brand_name", Verdict.CHECK, 'Label shows "CRAZY", which is close to "Crazy Turtle" but not the same.',
                       code="BRAND_NAME_NEAR_MATCH", found="CRAZY")


def test_brand_read_close_is_matches_when_the_second_reader_sees_it_exactly():
    [f] = confirm_differences([brand_near()], [FRAME], WORDS, APP, read=reader("CRAZY TURTLE"))
    assert f.verdict == Verdict.PASS and "CRAZY TURTLE" in f.reason


def test_brand_read_close_stays_please_check_when_the_second_reader_differs_too():
    for seen in ("CRAZY TURTIE", "CRAZY TURTLE RESERVE", ""):
        [f] = confirm_differences([brand_near()], [FRAME], WORDS, APP, read=reader(seen))
        assert f.verdict == Verdict.CHECK and f.code == "BRAND_NAME_NEAR_MATCH"


def test_brand_close_stays_please_check_when_the_label_also_shows_another_version():
    # TTB 23353001000444 with "WOODFORD RESERVA" planted on the back: the front's logo, re-read, says RESERVE
    near = FieldResult("brand_name", Verdict.CHECK, "close", code="BRAND_NAME_NEAR_MATCH", found="CRAZY")
    app = Application("malt", "Crazy Turtle")
    [f] = confirm_differences([near], [FRAME], WORDS, app, read=reader("CRAZY TURTLE"),
                              lines=["CRAZY", "", "CRAZY TURTIE ALE"])
    assert f.verdict == Verdict.CHECK and "CRAZY TURTIE ALE" in f.reason
