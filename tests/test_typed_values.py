"""What an agent types into the form: the same value written different ways must mean the same thing."""

import pytest

from app.verify.abv import parse_typed_abv


@pytest.mark.parametrize("typed", ["45", "45%", "45 %", " 45 ", "45.0", "45,0", "45% Alc", "45% AL", "45% alc/vol",
                                   "45% Alc./Vol.", "45 % ALC/VOL", "45 percent", "45% ABV", "ABV 45%", "Alc. 45% by vol",
                                   "45% alcohol by volume", "45 alc", "45%.", "45%%"])
def test_typed_alcohol_written_many_ways_is_45(typed):
    assert parse_typed_abv(typed) == 45.0


@pytest.mark.parametrize("typed, value", [("13.5", 13.5), ("13,5%", 13.5), ("0.5", 0.5), ("5% Alc./Vol.", 5.0),
                                          (".5", 0.5)])
def test_typed_alcohol_decimals(typed, value):
    assert parse_typed_abv(typed) == value


@pytest.mark.parametrize("typed", ["", "forty five", "abc", "45 50", "45-50%", "90 proof", "96", "-5", "45% 12 oz"])
def test_typed_alcohol_that_is_not_one_clear_percentage_is_refused(typed):
    assert parse_typed_abv(typed) is None  # the form asks again; it never guesses
