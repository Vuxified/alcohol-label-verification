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
    ("Old Tom", "Old Tom Reserve", C),              # extra word: could be another product, or the bottler line
    ("Stone's Throw", "Stone Throw", C),            # possessive dropped: near match
    ("Copper Hollow", "Juniper Ridge", C),          # not found: the brand may be decorative type the reader missed
    ("Bacardi", "BACARDÍ", P),                      # accents ignored
    ("Woodford Reserve", "THE WOODFORD RESERVE DISTILLERY", P),  # company words around the brand
    ("Bulleit", "BULLEIT DISTILLING CO.", P),
    ("Crown Royal", "CROWN ROYAL| 40 ALC/VOL (80", P),  # an amount beside it, split off
    ("L'Orée", "L'Orée 2025", P),                   # a number (vintage) beside it
    ("Caught Adrift India Pale Ale", "BEER: Caught Adrift India Pale Ale", P),
    ("Iron Anchor", "Iron Anchor Reserve", C),      # a name word beside it: may be another brand
    ("Logyard", "LOGYARD BREWING KANE, PA", C),     # a place beside it: a person decides
])
def test_brand_matching(expected, label, verdict):
    assert match_text("brand_name", expected, ["Some other line", label]).verdict == verdict


def test_brand_with_space_dropped_by_reader_matches():  # "FourRoses" read for "Four Roses" (TTB 24207001000388)
    assert match_text("brand_name", "Four Roses", ["FourRoses"]).verdict == P


def test_brand_only_in_bottler_line_says_so():
    r = match_text("brand_name", "Cupcake", ["BOTTLED BY CUPCAKE VINEYARDS, LIVERMORE & RIPON, CA."])
    assert r.verdict == C and "bottler" in r.reason


def test_space_rule_does_not_hide_extra_words():
    assert match_text("brand_name", "Old Tom", ["OldTomReserve"]).verdict != P


def test_one_character_difference_in_a_long_name_is_not_a_match():  # independent review, 2026-10-08
    assert match_text("class_type", "Kentucky Straight Bourbon Whisky", ["KENTUCKY STRAIGHT BOURBAN WHISKY"]).verdict == C


def test_a_clearly_read_different_number_does_not_match():  # owner decision, 2026-10-09
    r = match_text("brand_name", "Eagle Rare 10 Year Old", ["EAGLE RARE 12 YEAR OLD"])
    assert r.verdict == F and r.code == "BRAND_NAME_NUMBER_DIFFERS" and r.found == "EAGLE RARE 12 YEAR OLD"


def test_a_number_that_is_not_clearly_read_stays_please_check():
    assert match_text("brand_name", "Eagle Rare 10 Year Old", ["EAGLE RARE 1O YEAR OLD"]).verdict == C  # letter O
    assert match_text("brand_name", "Eagle Rare 10 Year Old", ["EAGLE RARE 12 YEAR"]).verdict == C  # a word differs too
    assert match_text("brand_name", "Eagle Rare 10", ["EAGLE RARE 10 12"]).verdict != F  # extra number, not a different one


def test_brand_split_across_lines():
    assert match_text("brand_name", "Old Tom Distillery", ["OLD TOM", "DISTILLERY"]).verdict == P


def test_class_extra_words_is_check_not_fail():
    r = match_text("class_type", "Straight Bourbon Whiskey", ["Kentucky Straight Bourbon Whiskey"])
    assert r.verdict == C


def test_brand_inside_bottler_line_is_check():  # seen on approved labels (Chateau Ste. Michelle, Sutter Home)
    r = match_text("brand_name", "Sutter Home", ["BOTTLED BY SUTTER HOME FAMILY VINEYARDS, CERES, CALIFORNIA"])
    assert r.verdict == C and r.code == "BRAND_NAME_EXTRA_WORDS"


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


def test_abv_not_found_is_check():  # could not find is not the same as clearly different
    r = check_abv(spirits(abv=40), ["750 mL"])
    assert r.verdict == C and r.code == "ABV_MISSING"


def test_table_wine_may_omit_abv():
    app = Application("wine", "Juniper Ridge", abv=13)
    assert check_abv(app, ["Juniper Ridge", "California Table Wine"]).verdict == P


def test_wine_over_14_must_show_abv():  # not found, so a person looks (RULES.md §1)
    app = Application("wine", "Juniper Ridge", abv=19.5)
    assert check_abv(app, ["Juniper Ridge", "Table Wine"]).verdict == C


def test_abv_abbreviation_on_wine_needs_check():
    app = Application("wine", "Juniper Ridge", abv=13.5)
    assert check_abv(app, ["13.5% ABV"]).code == "ABV_ABBREVIATION"


def test_malt_without_declared_abv_is_not_checked():
    app = Application("malt", "Black Juniper")
    assert check_abv(app, ["Black Juniper", "12 FL. OZ."]).verdict == NA


def test_proof_twice_abv():
    assert check_proof(spirits(abv=45), ["45% Alc./Vol. (90 Proof)"]).verdict == P
    assert check_proof(spirits(abv=45), ["45% Alc./Vol. (80 Proof)"]).code == "PROOF_MISMATCH"


def test_impossible_proof_is_check():  # "82.6" read as "826" (TTB 25045001000301); proof cannot exceed 200
    r = check_proof(spirits(abv=41.3), ["41.3% Alc./Vol. 826 Proof"])
    assert r.verdict == C and r.code == "PROOF_MISMATCH"


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
    r = check_net_contents(spirits(net_contents="750 mL"), ["700 mL"])
    assert r.verdict == F and r.code == "NET_CONTENTS_MISMATCH"


def test_net_contents_bare_letter_l_is_check():  # "1 L" read from can noise like "I 1 1 E 1 L" (TTB 24008001000478)
    r = check_net_contents(spirits(net_contents="12 FL. OZ."), ["I 1 1 E 1 L - - d"])
    assert r.verdict == C and r.code == "NET_CONTENTS_MISMATCH"


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


def test_warning_not_found_is_check():
    r = check_warning(["OLD TOM", "750 mL"])[0]
    assert r.verdict == C and r.code == "WARNING_MISSING"


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


def test_name_address_not_found_is_check():  # independent review, 2026-10-08: not found is never Does not match
    from app.verify.text import words_present
    r = words_present("name_address", "Bottled by Old Tom Distillery, Bardstown, KY", ["750 mL", "45% Alc./Vol."])
    assert r.verdict == C


# --- independent review, 2026-10-08 -------------------------------------------

def test_low_declared_alcohol_still_checked_when_label_shows_more():
    report = verify(spirits(abv=0.4), ["OLD TOM DISTILLERY", "40% Alc./Vol."])
    assert report.get("abv").verdict == F
    assert report.get("warning_text").verdict != NA


def test_real_non_alcoholic_label_skips_alcohol_and_warning():
    report = verify(Application("malt", "Heineken 0.0", abv=0.0), ["Heineken 0.0", "0.0% ALC/VOL"])
    assert report.get("abv").verdict == NA and report.get("warning_text").verdict == NA


def test_fanciful_name_is_checked():
    report = verify(spirits(fanciful_name="Man O' War"), ["OLD TOM DISTILLERY", "MAN O' WAR"])
    assert report.get("fanciful_name").verdict == P
    report = verify(spirits(fanciful_name="Man O' War"), ["OLD TOM DISTILLERY"])
    assert report.get("fanciful_name").verdict == C


def test_net_contents_close_sizes_are_different():
    assert check_net_contents(spirits(net_contents="350 mL"), ["355 mL"]).verdict == F
    assert check_net_contents(Application("malt", "X", net_contents="12 FL. OZ."), ["355 mL"]).verdict != F


def test_net_contents_misread_to_an_impossible_size_is_check():  # "760ml" read for 750 mL on an approved wine
    assert check_net_contents(Application("wine", "X", net_contents="750 mL"), ["760ml"]).verdict == C
    assert check_net_contents(spirits(net_contents="750 mL"), ["7501 ML"]).verdict == C
    assert check_net_contents(spirits(net_contents="750 mL"), ["700 mL"]).verdict == F  # a real, legal size


def test_net_contents_thousands_comma():
    assert parse_amount("1,750 mL") == 1750


def test_country_must_be_a_country_statement():
    imp = lambda: Application("spirits", "Old Tom", source="imported", country_of_origin="Mexico")
    assert verify(imp(), ["OLD TOM", "PRODUCT OF MEXICO"]).get("country_of_origin").verdict == P
    assert verify(imp(), ["OLD TOM", "Hecho en Mexico", "MEXICO"]).get("country_of_origin").verdict == P
    assert verify(imp(), ["OLD TOM", "Bottled by Old Tom Co., Santa Fe, New Mexico"]).get("country_of_origin").verdict == C


def test_country_in_its_own_language():
    app = lambda c: Application("wine", "Old Tom", source="imported", country_of_origin=c)
    assert verify(app("Italy"), ["OLD TOM", "PRODOTTO IN ITALIA"]).get("country_of_origin").verdict == P
    assert verify(app("Spain"), ["OLD TOM", "PRODUCTO DE ESPAÑA"]).get("country_of_origin").verdict == P
    assert verify(app("Germany"), ["OLD TOM", "PRODUCT OF DEUTSCHLAND"]).get("country_of_origin").verdict == P
    assert verify(app("Italia"), ["OLD TOM", "PRODUCT OF ITALY"]).get("country_of_origin").verdict == P
    # Scotland is not a name for the United Kingdom here: a person judges that.
    assert verify(app("United Kingdom"), ["OLD TOM", "PRODUCT OF SCOTLAND"]).get("country_of_origin").verdict == C


def test_a_second_country_on_the_label_is_for_a_person():
    app = Application("spirits", "Old Tom", source="imported", country_of_origin="Mexico")
    r = verify(app, ["OLD TOM", "PRODUCT OF MEXICO", "BOTTLED IN SPAIN"]).get("country_of_origin")
    assert r.verdict == C and r.code == "COUNTRY_SEVERAL" and "BOTTLED IN SPAIN" in r.reason
    assert verify(app, ["OLD TOM", "PRODUCT OF MEXICO", "HECHO EN MEXICO"]).get("country_of_origin").verdict == P
    typed_as_printed = Application("spirits", "Old Tom", source="imported", country_of_origin="Product of Ireland")
    assert verify(typed_as_printed, ["OLD TOM", "PRODUCT OF IRELAND"]).get("country_of_origin").verdict == P
    assert verify(typed_as_printed, ["PRODUCT OF IRELAND", "BOTTLED IN ENGLAND"]).get("country_of_origin").verdict == C
    scotch = Application("spirits", "Old Tom", source="imported", country_of_origin="Scotland")
    assert verify(scotch, ["DISTILLED AND BOTTLED IN SCOTLAND"]).get("country_of_origin").verdict == P


def test_imports_need_an_importer_statement():
    imp = lambda kind="spirits": Application(kind, "Old Tom", source="imported", country_of_origin="Mexico")
    found = verify(imp(), ["OLD TOM", "PRODUCT OF MEXICO", "IMPORTED BY OLD TOM IMPORTS, NEW YORK, NY"]).get("importer")
    assert found.verdict == P and found.code == "ON_LABEL" and "IMPORTED BY" in found.found
    assert verify(imp(), ["OLD TOM", "PRODUCT OF MEXICO", "Exclusively imported", "by Old Tom Imports, NY"]).get("importer").verdict == P
    missing = verify(imp("wine"), ["OLD TOM", "PRODUCT OF MEXICO", "BOTTLED BY OLD TOM CO., MEXICO CITY"]).get("importer")
    assert missing.verdict == C and missing.code == "IMPORTER_NOT_FOUND" and "4.35" in missing.reason
    domestic = verify(Application("spirits", "Old Tom"), ["OLD TOM", "BOTTLED BY OLD TOM, BARDSTOWN, KY"])
    assert all(f.field != "importer" for f in domestic.fields)


def test_shorter_class_across_a_line_break_says_what_the_label_shows():
    r = match_text("class_type", "Bourbon Whiskey", ["OLD TOM", "KENTUCKY STRAIGHT BOURBON", "WHISKEY"])
    assert r.verdict == C and r.code == "CLASS_TYPE_EXTRA_WORDS" and r.found == "KENTUCKY STRAIGHT BOURBON WHISKEY"


def test_grape_names_written_two_ways_are_not_a_different_product():
    assert match_text("class_type", "Pinot Gris", ["PINOT GRIGIO"]).verdict == C
    assert match_text("class_type", "Barossa Shiraz", ["BAROSSA SYRAH"]).verdict == C
    assert match_text("class_type", "Moscato d'Asti", ["MUSCAT D'ASTI"]).verdict != F


def test_importer_phrase_must_be_one_statement():
    imp = Application("wine", "Rossi", source="imported", country_of_origin="Italy")
    lines = ["ROSSI", "PRODUCT OF ITALY. IMPORTED FROM TUSCANY. BOTTLED BY ROSSI SRL"]
    assert verify(imp, lines).get("importer").verdict == C
    assert verify(imp, ["IMPORTED PREMIUM VODKA", "DISTILLED AND BOTTLED BY X"]).get("importer").verdict == C
    assert verify(imp, ["Imported and bottled by Rossi USA, Miami, FL"]).get("importer").verdict == P
    assert verify(imp, ["Sole importer: Rossi USA, Miami, FL"]).get("importer").verdict == P


def test_a_clearly_different_type_word_does_not_match():  # owner decision, 2026-10-09
    r = match_text("class_type", "Kentucky Straight Rye Whiskey", ["KENTUCKY STRAIGHT BOURBON WHISKEY"])
    assert r.verdict == F and r.code == "CLASS_TYPE_WORD_DIFFERS"
    assert match_text("class_type", "London Dry Gin", ["LONDON DRY RUM"]).verdict == F


def test_a_near_spelling_or_unknown_word_stays_please_check():
    assert match_text("class_type", "Kentucky Straight Bourbon Whiskey", ["KENTUCKY STRAIGHT BOURBAN WHISKEY"]).verdict == C
    assert match_text("class_type", "Kentucky Straight Bourbon Whiskey", ["KENTUCKY STRANGE BOURBON WHISKEY"]).verdict == C
    assert match_text("class_type", "Bourbon Whiskey", ["RYE GIN"]).verdict != F  # two words differ: not one clear swap


def test_brand_words_never_fail_on_a_different_word():  # decorative lettering can read as any word
    assert match_text("brand_name", "Old Tom Distillery", ["OLD GIN DISTILLERY"]).verdict == C
