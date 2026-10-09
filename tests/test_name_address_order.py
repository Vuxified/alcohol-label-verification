"""Name and address must be on the label as one statement: its words together and in order (a few stray reader tokens
and line wraps allowed), not scattered over the label. Found on a tampered Sutter Home label: the bottler line read
"SUTTER HILL FAMILY VINEYARDS", but "HOME" was in the logo, so every word was "somewhere" and it said Matches."""

from app.verify import Verdict
from app.verify.text import words_present

APP = "BOTTLED BY SUTTER HOME FAMILY VINEYARDS | CERES, CALIFORNIA"


def v(expected, lines):
    return words_present("name_address", expected, lines).verdict


def test_changed_bottler_name_is_not_matches_even_if_its_words_are_elsewhere():
    lines = ["SUTTER", "HOME", "CHARDONNAY", "BOTTLED BY SUTTER HILL FAMILY VINEYARDS | CERES, CALIFORNIA",
             "SUTTERHOME.COM 50097736"]
    assert v(APP, lines) == Verdict.CHECK


def test_the_statement_itself_matches():
    assert v(APP, ["SUTTER", "HOME", "BOTTLED BY SUTTER HOME FAMILY VINEYARDS | CERES, CALIFORNIA"]) == Verdict.PASS


def test_wrapped_across_lines_matches():
    lines = ["PRODUCED AND BOTTLED BY", "OLD TOM DISTILLERY", "BARDSTOWN, KENTUCKY"]
    assert v("Produced and bottled by Old Tom Distillery, Bardstown, KY", lines) == Verdict.PASS


def test_a_few_stray_tokens_between_words_match():
    lines = ["BOTTLED BY OLD TOM - DISTILLERY ® I", "BARDSTOWN, KY 40004"]
    assert v("Bottled by Old Tom Distillery, Bardstown, KY 40004", lines) == Verdict.PASS


def test_split_and_glued_words_still_match():
    assert v("Bottled by Old Tom Distillery, Bardstown, KY", ["BOTTLED BY OLDTOM DIST ILLERY BARDSTOWN KY"]) == Verdict.PASS
