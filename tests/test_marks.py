"""Marks on the results page: which words differ, and which warning words were not confirmed."""

from app.verify.warning import REQUIRED
from app.web.marks import differing_words, warning_marks


def marked(parts):
    return [w for w, differs in parts if differs]


def test_one_differing_word_is_marked_on_both_sides():
    asked, found = differing_words("Lantern Old Reserve 10 Year", "LANTERN OLD RESERVE 12 YEAR")
    assert marked(asked) == ["10"] and marked(found) == ["12"]
    assert " ".join(w for w, _ in found) == "LANTERN OLD RESERVE 12 YEAR"  # the label's text is shown as read


def test_case_and_punctuation_are_not_marked():
    asked, found = differing_words("Stone's Throw", "STONES THROW")
    assert marked(asked) == [] and marked(found) == []


def test_extra_words_on_the_label_are_marked():
    asked, found = differing_words("Sutter Home", "BOTTLED BY SUTTER HOME FAMILY VINEYARDS")
    assert marked(asked) == [] and marked(found) == ["BOTTLED", "BY", "FAMILY", "VINEYARDS"]


def test_nothing_in_common_marks_nothing():
    asked, found = differing_words("Old Tom", "RIVER BEND")  # every word would be marked: say nothing instead
    assert marked(asked) == [] and marked(found) == []


def test_missing_input_gives_none():
    assert differing_words("Old Tom", None) is None


def test_exact_warning_has_no_marks():
    parts = warning_marks([("onnx", REQUIRED), ("tess", REQUIRED)])
    assert "".join(t for t, _ in parts) == REQUIRED
    assert not [t for t, kind in parts if kind]


def test_changed_word_is_marked_and_the_label_word_shown():
    label = REQUIRED.replace("and may cause", "and can cause")
    parts = warning_marks([("onnx", label), ("tess", label)])
    assert [t for t, kind in parts if kind == "missing"] == ["may"]
    assert [t for t, kind in parts if kind == "label"] == ["can"]
    assert "".join(t for t, _ in parts).count("may") == 1  # legal text otherwise unchanged


def test_added_word_is_shown_where_it_was_read():
    label = REQUIRED.replace("beverages impairs", "beverages greatly impairs")
    parts = warning_marks([("onnx", label)])
    assert [t for t, kind in parts if kind == "extra"] == ["greatly"]


def test_no_warning_read_gives_none():
    assert warning_marks([("onnx", "750 mL")]) is None
