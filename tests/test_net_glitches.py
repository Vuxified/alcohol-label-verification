"""Net contents as real approved labels were read (2026-10-09): the estimated-quantity mark read as a glued "e"
("720MLe"), a period before the unit ("750.ml"), and the M of ML read as W or N ("750WL"). The last only confirms the
declared amount; it never fails a label."""

import pytest

from app.verify import Application, Verdict
from app.verify.net_contents import check_net_contents


def verdict(net, text, bev="wine"):
    return check_net_contents(Application(bev, "Brand", net_contents=net), [text]).verdict


@pytest.mark.parametrize("net, text", [
    ("720ML", "TO DRIVE A CAR OR OPERATE 720MLe MACHINERY"),
    ("750 ml", "Imported by: 750mle Hootananny Wines"),
    ("750 ml", "Imported by: 750 mle & 7 Hootananny"),
    ("750 ml", "PRODUCTOF U 750.ml POLAND"),
    ("750 ML.", "DENOMINACION DE ORIGEN X00X-000000 750WL Contains Sulfites"),
    ("750 ML.", "DENOMINACION DE ORIGEN X00X-000000 750NL Contains Sulfites 2024 L"),
])
def test_read_glitches_still_match(net, text):
    assert verdict(net, text) == Verdict.PASS


@pytest.mark.parametrize("net, text", [
    ("700 ML", "DENOMINACION DE ORIGEN 750WL Contains Sulfites"),  # a different number: not confirmed
    ("750 ML", "750WL Contains Sulfites 1 L"),                     # a real other size on the label: a person looks
    ("750 ML", "750 WINES OF THE WORLD"),                          # no unit at all
])
def test_lookalike_unit_never_confirms_otherwise(net, text):
    assert verdict(net, text) != Verdict.PASS


def test_lookalike_unit_never_fails():
    assert verdict("700 ML", "750WL Contains Sulfites") != Verdict.FAIL
