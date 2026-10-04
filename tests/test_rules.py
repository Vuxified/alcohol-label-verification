"""Unit tests for each rule in docs/RULES.md, including the known traps."""

import pytest

from app.verify import Application, Verdict, verify
from app.verify.abv import check_abv, check_proof
from app.verify.net_contents import check_net_contents, parse_amount
from app.verify.text import match_text, normalize
from app.verify.warning import REQUIRED, check_warning

P, C, F, NA = Verdict.PASS, Verdict.CHECK, Verdict.FAIL, Verdict.NOT_APPLICABLE


def spirits(**kw):
    return Application(**({"beverage_type": "spirits", "brand_name": "Old Tom Distillery"} | kw))


# --- §2 text matching -------------------------------------------------------

@pytest.mark.parametrize("expected, label, verdict", [
    ("Stone's Throw", "STONE'S THROW", P),          # Dave's example: case only
    ("Stone's Throw", "STONE’S THROW", P),     # curly apostrophe
    ("Old Tom Distillery", "OLD TOM DISTILLERY", P),
    ("Old Tom", "Old Tom Reserve", F),              # extra word = different product
    ("Stone's Throw", "Stone Throw", C),            # possessive dropped: near match
    ("Copper Hollow", "Juniper Ridge", F),
    ("Bacardi", "BACARDÍ", P),                      # accents ignored
])
def test_brand_matching(expected, label, verdict):
    assert match_text("brand_name", expected, ["Some other line", label]).verdict == verdict


def test_brand_split_across_lines():
    assert match_text("brand_name", "Old Tom Distillery", ["OLD TOM", "DISTILLERY"]).verdict == P


def test_class_extra_words_is_check_not_fail():
    r = match_text("class_type", "Straight Bourbon Whiskey", ["Kentucky Straight Bourbon Whiskey"], extra_words=C)
    assert r.verdict == C


@pytest.mark.parametrize("expected, label", [
    ("Kentucky Straight Bourbon Whiskey", "KENTUCKY STRAIGHT BOURBON WHISKY"),  # § 5.143: either spelling
    ("Irish Whisky", "Irish Whiskey"),
    ("Whiskey", "WHISKY"),  # short: one letter is too big a share for the similarity score alone
])
def test_class_whisky_whiskey_spellings_match(expected, label):
    assert match_text("class_type", expected, [label]).verdict == P


def test_normalize():
    assert normalize("  Stone’s   THROW!! ") == "stone's throw"


# --- §3 alcohol content ------------------------------------------------------

@pytest.mark.parametrize("label", ["45% Alc./Vol.", "Alc. 45% by vol.", "45 percent alcohol by volume",
                                   "Alcohol by volume: 45%", "45% ALC/VOL", "ALC. 45% BY VOL.", "45.0% Alc./Vol."])
def test_abv_formats(label):
    assert check_abv(spirits(abv=45), [label]).verdict == P


def test_abv_mismatch():
    r = check_abv(spirits(abv=40), ["45% Alc./Vol."])
    assert r.verdict == F and r.code == "ABV_MISMATCH"


def test_abv_missing_on_spirits_fails():
    assert check_abv(spirits(abv=40), ["750 mL"]).code == "ABV_MISSING"


def test_table_wine_may_omit_abv():
    app = Application("wine", "Juniper Ridge", abv=13)
    assert check_abv(app, ["Juniper Ridge", "California Table Wine"]).verdict == P


def test_wine_over_14_must_show_abv():
    app = Application("wine", "Juniper Ridge", abv=19.5)
    assert check_abv(app, ["Juniper Ridge", "Table Wine"]).verdict == F


def test_abv_abbreviation_on_wine_needs_check():
    app = Application("wine", "Juniper Ridge", abv=13.5)
    assert check_abv(app, ["13.5% ABV"]).code == "ABV_ABBREVIATION"


def test_malt_without_declared_abv_is_not_checked():
    app = Application("malt", "Black Juniper")
    assert check_abv(app, ["Black Juniper", "12 FL. OZ."]).verdict == NA


def test_proof_twice_abv():
    assert check_proof(spirits(abv=45), ["45% Alc./Vol. (90 Proof)"]).verdict == P
    assert check_proof(spirits(abv=45), ["45% Alc./Vol. (80 Proof)"]).code == "PROOF_MISMATCH"


def test_proof_ignored_for_wine():
    assert check_proof(Application("wine", "X", abv=14), ["28 Proof"]).verdict == NA


# --- §4 net contents ----------------------------------------------------------

@pytest.mark.parametrize("text, ml", [("750 mL", 750), ("75 cl", 750), ("1.75 L", 1750),
                                      ("12 FL. OZ.", 354.9), ("1 PINT 8 FL. OZ.", 709.8), ("15.5 U.S. Gallons", 58674)])
def test_parse_amount(text, ml):
    assert parse_amount(text) == pytest.approx(ml, rel=0.001)


def test_net_contents_match_across_units():
    assert check_net_contents(spirits(net_contents="750 mL"), ["75 cl"]).verdict == P


def test_net_contents_mismatch():
    assert check_net_contents(spirits(net_contents="750 mL"), ["700 mL"]).code == "NET_CONTENTS_MISMATCH"


def test_malt_us_units_pass():
    app = Application("malt", "Black Juniper", net_contents="12 FL. OZ.")
    assert check_net_contents(app, ["12 FL. OZ. (355 mL)"]).verdict == P


def test_malt_metric_only_on_label_is_check():
    # TTB approves imports like this (e.g. Guinness "325ml"); U.S. units may be on the container
    app = Application("malt", "Black Juniper", net_contents="12 FL. OZ.")
    assert check_net_contents(app, ["355 mL"]).code == "NET_CONTENTS_UNITS"


def test_nonstandard_spirits_size_needs_check():
    assert check_net_contents(spirits(net_contents="800 mL"), ["800 mL"]).code == "NET_CONTENTS_NOT_STANDARD"


def test_net_contents_absent_is_check_not_fail():
    # may be molded into the bottle; TTB approves such labels
    assert check_net_contents(spirits(net_contents="750 mL"), ["OLD TOM"]).verdict == C


# --- §5 government warning -------------------------------------------------

def test_warning_exact_passes():
    text, caps = check_warning([REQUIRED])
    assert (text.verdict, caps.verdict) == (P, P)


def test_warning_wrapped_and_hyphenated_passes():
    wrapped = REQUIRED.replace("because", "be-\ncause").replace("Consumption", "CON- SUMPTION").split(" ")
    lines = [" ".join(wrapped[i:i + 6]) for i in range(0, len(wrapped), 6)]
    assert check_warning(lines)[0].verdict == P


def test_warning_title_case_fails():  # Jenny's catch
    _, caps = check_warning([REQUIRED.replace("GOVERNMENT WARNING", "Government Warning")])
    assert caps.code == "WARNING_NOT_CAPS"


def test_warning_all_caps_body_passes():
    assert check_warning([REQUIRED.upper()])[0].verdict == P


@pytest.mark.parametrize("old, new", [("may cause", "can cause"), ("alcoholic beverages during", "beverages during"),
                                      ("(2) Consumption", "Consumption"), ("birth defects", "birth complications")])
def test_warning_altered_wording_fails(old, new):
    assert check_warning([REQUIRED.replace(old, new)])[0].code == "WARNING_TEXT_ALTERED"


def test_warning_missing_period_is_check():  # seen on approved labels
    assert check_warning([REQUIRED.replace("birth defects.", "birth defects")])[0].code == "WARNING_PUNCTUATION"


def test_warning_missing_fails():
    assert check_warning(["OLD TOM", "750 mL"])[0].code == "WARNING_MISSING"


def test_text_after_warning_is_ignored():
    assert check_warning([REQUIRED + " Please enjoy responsibly. Visit our website."])[0].verdict == P


# --- overall -----------------------------------------------------------------

def test_sample_label_from_the_brief_passes():
    app = Application("spirits", "OLD TOM DISTILLERY", "Kentucky Straight Bourbon Whiskey", 45, "750 mL")
    lines = ["OLD TOM DISTILLERY", "Kentucky Straight Bourbon Whiskey", "45% Alc./Vol. (90 Proof)", "750 mL", REQUIRED]
    report = verify(app, lines)
    assert report.overall == P, [(f.field, f.reason) for f in report.fields if f.verdict != P]


def test_non_alcoholic_skips_abv_and_warning():
    app = Application("malt", "Black Juniper", abv=0.0, net_contents="12 FL. OZ.")
    report = verify(app, ["Black Juniper", "0.0", "12 FL. OZ."])
    assert report.get("abv").verdict == NA and report.get("warning_text").verdict == NA


def test_overall_is_worst_field():
    app = Application("spirits", "OLD TOM DISTILLERY", abv=45, net_contents="750 mL")
    lines = ["OLD TOM DISTILLERY", "40% Alc./Vol.", "750 mL", REQUIRED]
    assert verify(app, lines).overall == F
