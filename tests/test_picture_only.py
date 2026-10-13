"""Picture-only checks: with the brand left blank (only pictures given), an item left blank is not compared; instead the app looks for the statement the
rules require on the label (27 CFR 4.32, 5.63, 7.63). Found = "On the label"; a required statement not found =
Please check; never Does not match, since there is nothing to compare with."""

from app.verify import Application, Verdict, verify
from app.verify.presence import ON_LABEL, read_values

SPIRITS = ["OLD LANTERN", "KENTUCKY STRAIGHT BOURBON WHISKEY", "45% ALC/VOL (90 PROOF)", "750 ML",
           "DISTILLED AND BOTTLED BY OLD LANTERN DISTILLING CO., BARDSTOWN, KY"]
WINE = ["HILLSIDE CELLARS", "2021 CABERNET SAUVIGNON", "NAPA VALLEY", "ALC. 13.5% BY VOL.", "750 ML",
        "PRODUCED AND BOTTLED BY HILLSIDE CELLARS, NAPA, CA"]
BEER = ["RIVER BEND", "INDIA PALE ALE", "12 FL OZ", "BREWED AND CANNED BY RIVER BEND BREWING, BEND, OR"]


def run(kind, lines, **given):
    return {f.field: f for f in verify(Application(kind, given.pop("brand_name", ""), **given), lines).fields}


def test_blank_items_found_on_the_label():
    r = run("spirits", SPIRITS)
    for field in ("class_type", "abv", "net_contents", "name_address"):
        assert r[field].verdict == Verdict.PASS and r[field].code == ON_LABEL, field
    assert r["abv"].found == "45% ALC/VOL"
    assert "BOTTLED BY" in r["name_address"].found


def test_blank_brand_is_for_a_person_to_confirm():
    # Required on the label, but usually a logo: Please check, never a guess at which text is the brand.
    brand = run("spirits", SPIRITS)["brand_name"]
    assert brand.verdict == Verdict.CHECK and brand.code == "BRAND_NOT_GIVEN" and brand.found is None


def test_nothing_is_ever_does_not_match_without_application_values():
    for kind, lines in (("spirits", SPIRITS), ("wine", WINE), ("malt", BEER), ("spirits", ["SOMETHING"]),
                        ("wine", ["X", "760 ML"]), ("spirits", ["40% ALC/VOL", "45% ALC/VOL"])):
        assert all(f.verdict != Verdict.FAIL for f in run(kind, lines).values())


def test_spirits_without_alcohol_content_is_please_check():
    r = run("spirits", [x for x in SPIRITS if "ALC" not in x])
    assert r["abv"].verdict == Verdict.CHECK and "5.65" in r["abv"].reason


def test_two_different_alcohol_contents_is_please_check():
    assert run("spirits", ["40% ALC/VOL", "45% ALC/VOL"])["abv"].verdict == Verdict.CHECK


def test_table_wine_may_leave_out_alcohol_content():
    r = run("wine", ["HILLSIDE", "RED TABLE WINE", "750 ML", "BOTTLED BY HILLSIDE, NAPA, CA"])
    assert r["abv"].verdict == Verdict.PASS and "table wine" in r["abv"].reason.lower()


def test_wine_with_neither_is_please_check():
    r = run("wine", ["HILLSIDE", "CABERNET SAUVIGNON", "750 ML"])
    assert r["abv"].verdict == Verdict.CHECK


def test_beer_without_alcohol_content_is_not_checked():
    assert run("malt", [x for x in BEER])["abv"].verdict == Verdict.NOT_APPLICABLE


def test_missing_bottler_line_and_net_contents_are_please_check():
    r = run("malt", ["RIVER BEND", "INDIA PALE ALE"])
    assert r["name_address"].verdict == Verdict.CHECK
    assert r["net_contents"].verdict == Verdict.CHECK


def test_a_size_not_allowed_for_wine_is_please_check():
    r = run("wine", ["HILLSIDE", "RED WINE", "760 ML"])
    assert r["net_contents"].verdict == Verdict.CHECK


def test_missing_class_is_please_check():
    assert run("spirits", ["OLD LANTERN", "45% ALC/VOL", "750 ML"])["class_type"].verdict == Verdict.CHECK


def test_imported_without_country_looks_for_the_country_statement():
    r = run("wine", WINE + ["PRODUCT OF ITALY"], source="imported")
    assert r["country_of_origin"].verdict == Verdict.PASS and "ITALY" in r["country_of_origin"].found
    assert run("wine", WINE, source="imported")["country_of_origin"].verdict == Verdict.CHECK


def test_given_values_are_still_compared():
    r = run("spirits", SPIRITS, brand_name="Old Lantern", abv=40.0)
    assert r["abv"].verdict == Verdict.FAIL and r["abv"].code != ON_LABEL


def test_read_values_fills_the_form():
    v = read_values(SPIRITS)
    assert v["abv"] == "45" and v["net_contents"] == "750 ML"
    assert v["class_type"] == "KENTUCKY STRAIGHT BOURBON WHISKEY"
    assert v["name_address"].startswith("DISTILLED AND BOTTLED BY")
    assert v["beverage_type"] == "spirits"
    assert read_values(WINE)["beverage_type"] == "wine" and read_values(BEER)["beverage_type"] == "malt"
    assert read_values(WINE + ["PRODUCT OF ITALY"])["country_of_origin"] == "Italy"


def test_hard_tea_and_lemonade_are_malt_beverages():
    assert read_values(["HARD ICED TEA", "4% ALC./VOL."])["beverage_type"] == "malt"
    assert read_values(["HARD LEMONADE"])["beverage_type"] == "malt" and read_values(["HARD TEA"])["beverage_type"] == "malt"
    assert "beverage_type" not in read_values(["ICED TEA"])


def test_read_values_leaves_out_what_it_did_not_find():
    v = read_values(["SOMETHING"])
    assert "abv" not in v and "net_contents" not in v and "beverage_type" not in v


def test_with_a_brand_typed_blank_items_stay_not_checked():
    r = run("spirits", ["OLD LANTERN", "45% ALC/VOL", "750 ML"], brand_name="Old Lantern")
    assert "class_type" not in r and "name_address" not in r
    assert r["abv"].verdict == Verdict.NOT_APPLICABLE or r["abv"].code == "ABV_NOT_DECLARED"


def test_an_address_split_after_a_comma_is_joined():
    v = read_values(["BOTTLED BY LANTERN CO., LOUISVILLE,", "KY", "750 ML"])
    assert v["name_address"] == "BOTTLED BY LANTERN CO., LOUISVILLE, KY"
