"""Rules a label must follow on its own (RULES.md §6b), checked from the label text: a rule that is broken is Please
check with the rule quoted (the agent decides), never Does not match. A rule that does not apply adds nothing."""

from app.verify.label_rules import label_rules
from app.verify import Application, Verdict

W = "GOVERNMENT WARNING"


def run(kind, lines, **given):
    return {f.field: f for f in label_rules(Application(kind, given.pop("brand_name", "X"), **given), lines)}


# Class minimums (27 CFR 5.142-5.148: 40%; flavored 5.151: 30%)
def test_vodka_under_40_percent_is_please_check():
    f = run("spirits", ["SILVER VODKA", "35% ALC/VOL", "750 ML"])["abv_minimum"]
    assert f.verdict == Verdict.CHECK and "5.142" in f.reason


def test_vodka_at_40_percent_meets_the_minimum():
    assert run("spirits", ["SILVER VODKA", "40% ALC/VOL"])["abv_minimum"].verdict == Verdict.PASS


def test_each_class_has_its_section():
    for word, sec in (("BOURBON WHISKEY", "5.143"), ("LONDON DRY GIN", "5.144"), ("BRANDY", "5.145"),
                      ("DARK RUM", "5.147"), ("TEQUILA BLANCO", "5.148")):
        f = run("spirits", [word, "35% ALC/VOL"])["abv_minimum"]
        assert f.verdict == Verdict.CHECK and sec in f.reason, word


def test_flavored_spirits_need_only_30_percent():
    assert run("spirits", ["CINNAMON FLAVORED WHISKY", "33% ALC/VOL"])["abv_minimum"].verdict == Verdict.PASS
    assert run("spirits", ["VODKA WITH NATURAL FLAVORS", "30% ALC/VOL"])["abv_minimum"].verdict == Verdict.PASS
    assert run("spirits", ["CHERRY FLAVORED VODKA", "25% ALC/VOL"])["abv_minimum"].verdict == Verdict.CHECK


def test_liqueurs_cocktails_and_mixed_drinks_have_no_class_minimum():
    for lines in (["COFFEE LIQUEUR", "20% ALC/VOL"], ["VODKA SODA", "4.5% ALC/VOL"], ["RUM CREAM", "17% ALC/VOL"],
                  ["MARGARITA COCKTAIL MADE WITH TEQUILA", "12.7% ALC/VOL"], ["GIN & TONIC", "7% ALC/VOL"]):
        assert "abv_minimum" not in run("spirits", lines), lines


def test_only_the_label_class_line_counts():
    # the application's class is a broad registry code: a 12% coffee drink filed as "VODKA" (cola2 25213001000246)
    assert "abv_minimum" not in run("spirits", ["SILVER", "35% ALC/VOL"], class_type="Vodka")


def test_specialty_products_seen_on_approved_labels_are_skipped():
    for lines in (["RICH COFFEE MEETS PREMIUM VODKA", "12% ALC/VOL"],                     # cola2 25213001000246
                  ["Straight Bourbon Whiskey With Sugar", "21% ALC/VOL"],                # cola2 25231001000857
                  ["PREMIUM VODKA", "12% ALC/VOL"]):                                     # under 20%: ready to drink
        assert "abv_minimum" not in run("spirits", lines), lines


def test_unclear_alcohol_content_adds_nothing():
    assert "abv_minimum" not in run("spirits", ["VODKA", "35% ALC/VOL", "40% ALC/VOL"])
    assert "abv_minimum" not in run("spirits", ["VODKA"])


# Bottled in bond (5.88(a)(6): exactly 50%, 100 proof)
def test_bottled_in_bond_must_be_100_proof():
    assert run("spirits", ["BOTTLED IN BOND", "BOURBON", "50% ALC/VOL (100 PROOF)"])["bonded"].verdict == Verdict.PASS
    f = run("spirits", ["BOTTLED-IN-BOND", "BOURBON", "45% ALC/VOL"])["bonded"]
    assert f.verdict == Verdict.CHECK and "5.88" in f.reason
    assert "bonded" not in run("spirits", ["BOURBON", "45% ALC/VOL"])


# Wine (4.21(a)(5), 4.36(a): table wine is 14% or less; 4.6: Part 4 covers 7-24%)
def test_table_wine_over_14_percent_is_please_check():
    f = run("wine", ["RED TABLE WINE", "14.5% ALC/VOL"])["wine_terms"]
    assert f.verdict == Verdict.CHECK and "4.21" in f.reason
    assert run("wine", ["RED TABLE WINE", "12.5% ALC/VOL"])["wine_terms"].verdict == Verdict.PASS


def test_wine_outside_7_to_24_percent_is_please_check():
    assert run("wine", ["SPARKLING WINE", "5.5% ALC/VOL"])["wine_terms"].verdict == Verdict.CHECK
    assert run("wine", ["CABERNET", "13.5% ALC/VOL"]).get("wine_terms") is None


# Malt beverages (7.65(d)-(f))
def test_low_alcohol_only_under_2_5_percent():
    assert run("malt", ["LOW ALCOHOL LAGER", "3.2% ALC/VOL"])["malt_terms"].verdict == Verdict.CHECK
    assert run("malt", ["REDUCED ALCOHOL ALE", "2.4% ALC/VOL"])["malt_terms"].verdict == Verdict.PASS


def test_non_alcoholic_needs_its_statement():
    f = run("malt", ["NON-ALCOHOLIC BREW"])["malt_terms"]
    assert f.verdict == Verdict.CHECK and "7.65" in f.reason
    ok = run("malt", ["NON-ALCOHOLIC BREW", "CONTAINS LESS THAN 0.5% ALCOHOL BY VOLUME"])["malt_terms"]
    assert ok.verdict == Verdict.PASS
    assert run("malt", ["NON ALCOHOLIC", "contains less than .5% alc/vol"])["malt_terms"].verdict == Verdict.PASS


def test_alcohol_free_only_without_alcohol():
    assert run("malt", ["ALCOHOL FREE", "0.4% ALC/VOL"])["malt_terms"].verdict == Verdict.CHECK
    assert run("malt", ["ALCOHOL-FREE", "0.0% ALC/VOL"])["malt_terms"].verdict == Verdict.PASS


def test_the_health_warning_words_do_not_count():
    warning = "CONSUMPTION OF ALCOHOLIC BEVERAGES IMPAIRS YOUR ABILITY"
    assert run("malt", ["IPA", warning, "6% ALC/VOL"]) == {}


def test_never_does_not_match():
    cases = [("spirits", ["VODKA", "20% ALC/VOL", "BOTTLED IN BOND"]), ("wine", ["TABLE WINE", "30% ALC/VOL"]),
             ("malt", ["NON-ALCOHOLIC", "ALCOHOL FREE", "LOW ALCOHOL", "5% ALC/VOL"])]
    for kind, lines in cases:
        assert all(f.verdict != Verdict.FAIL for f in run(kind, lines).values())
