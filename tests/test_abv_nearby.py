"""Alcohol content printed apart from its wording (columns, line breaks, a misread word between): the application's
own number with a % sign and alcohol wording a few words away confirms it. This never fails a label: a different
number found this loose way stays Please check. Readings from real approved labels (cola2, 2026-10-09)."""

import pytest

from app.verify import Application, Verdict
from app.verify.abv import check_abv


def verdict(abv, text, bev="spirits"):
    return check_abv(Application(bev, "Brand", abv=abv), [text])


@pytest.mark.parametrize("abv, text", [
    (23, "COFFEE & NH MAPLE SYRUP 23% 46 750 ALC/VOL PROOF"),
    (10.7, "PLUM FLAVORED BEER 10.7% 11.2 ALC.VOL. FL OZ"),
    (57, 'DISTILLED FROM GRAIN" 114 57% PROOF ALC/VOL'),
    (13.4, "Chenin Blanc, 50% Cortese 13.4%. Alc. By Vol Clarksburg"),
    (21, "Bourbon Whiskey With Sugar 21% Ale by Vol: (42 proof)"),
    (30, "Real Maple Syrup 750ML ALC30% byvol 60 PROOF"),
])
def test_number_with_wording_nearby_matches(abv, text):
    f = verdict(abv, text)
    assert f.verdict == Verdict.PASS, f.reason


@pytest.mark.parametrize("abv, text", [
    (40, "MASH BILL 40% RYE 60% CORN"),                      # a percentage, but not of alcohol
    (4, "SALT AND LEMON 8 FL 12 OZ 4% GOVERNMENT WARNING"),   # no alcohol wording near it
    (24, "COFFEE & NH MAPLE SYRUP 23% 46 750 ALC/VOL PROOF"),  # a different number: never Does not match this way
    (23, "COFFEE 23 46 750 ALC/VOL PROOF"),                 # no % sign
    (3, "COFFEE 23% 46 750 ALC/VOL PROOF"),                 # only the tail of 23
])
def test_otherwise_please_check(abv, text):
    assert verdict(abv, text).verdict == Verdict.CHECK


def test_a_clear_statement_still_decides():
    # the strict reading finds 45% next to its wording: a 40% elsewhere doesn't make it Matches
    assert verdict(40, "45% ALC/VOL 40% of the barrels by volume").verdict != Verdict.PASS
