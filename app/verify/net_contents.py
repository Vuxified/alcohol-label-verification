"""Net contents (RULES.md §4; 27 CFR 4.37, 4.72, 5.70, 5.203, 7.70)."""

import re
from dataclasses import dataclass

from .model import Application, FieldResult, Verdict

ML_PER = {"ml": 1, "cl": 10, "l": 1000, "fl oz": 29.5735, "pint": 473.176, "gal": 3785.41}

# Authorized standards of fill, in mL.
SPIRITS_FILLS = {3750, 3000, 2000, 1800, 1750, 1500, 1000, 945, 900, 750, 720, 710, 700, 570, 500,
                 475, 375, 355, 350, 331, 250, 200, 187, 100, 50}
WINE_FILLS = {3000, 2250, 1800, 1500, 1000, 750, 720, 700, 620, 600, 568, 550, 500, 473, 375, 360,
              355, 330, 300, 250, 200, 187, 180, 100, 50}

_N = r"(\d+(?:[.,]\d+)?)"
_UNIT_PATTERNS = [
    ("fl oz", re.compile(rf"{_N}\s*(?:u\.?s\.?\s*)?fl\.?\s*oz\.?", re.I)),
    ("pint", re.compile(rf"{_N}\s*pints?\b", re.I)),
    ("gal", re.compile(rf"{_N}\s*(?:u\.?s\.?\s*)?gal(?:lons?|\.)?\b", re.I)),
    ("ml", re.compile(rf"{_N}\s*(?:ml|millilit(?:er|re)s?)\b", re.I)),
    ("cl", re.compile(rf"{_N}\s*(?:cl|centilit(?:er|re)s?)\b", re.I)),
    ("l", re.compile(rf"{_N}\s*(?:l|lit(?:er|re)s?)\b(?!\s*/)", re.I)),
]
_COMPOUND = re.compile(r"(\d+)\s*pints?\.?\s*(\d+(?:\.\d+)?)\s*fl\.?\s*oz", re.I)


@dataclass
class Amount:
    ml: float
    text: str
    metric: bool


def find_amounts(text: str) -> list[Amount]:
    found = []
    taken = []
    for m in _COMPOUND.finditer(text):  # "1 PINT 8 FL. OZ."
        found.append(Amount(float(m.group(1)) * ML_PER["pint"] + float(m.group(2)) * ML_PER["fl oz"], m.group(0), False))
        taken.append(m.span())
    for unit, pattern in _UNIT_PATTERNS:
        for m in pattern.finditer(text):
            if any(a <= m.start() < b for a, b in taken):
                continue
            value = float(m.group(1).replace(",", "."))
            found.append(Amount(value * ML_PER[unit], m.group(0).strip(), unit in ("ml", "cl", "l")))
            taken.append(m.span())
    return found


def parse_amount(text: str) -> float | None:
    amounts = find_amounts(text)
    return amounts[0].ml if amounts else None


def _same(a: float, b: float) -> bool:
    return abs(a - b) <= max(5.0, 0.01 * b)


def check_net_contents(app: Application, lines: list[str]) -> FieldResult:
    if not app.net_contents:
        return FieldResult("net_contents", Verdict.NOT_APPLICABLE, "No net contents declared; not checked.")
    expected = parse_amount(app.net_contents)
    if expected is None:
        return FieldResult("net_contents", Verdict.CHECK, f'Could not understand the application value "{app.net_contents}".',
                           code="NET_CONTENTS_UNPARSED")
    amounts = find_amounts(" ".join(lines))
    if not amounts:
        # Net contents may be blown or molded into the container instead (5.63, 7.63), so not a fail.
        return FieldResult("net_contents", Verdict.CHECK,
                           "Net contents not found on the label. It may be molded into the bottle; please confirm.",
                           code="NET_CONTENTS_NOT_FOUND")
    match = next((a for a in amounts if _same(a.ml, expected)), None)
    if not match:
        if all(re.fullmatch(r"[\d.,]+\s*l", a.text, re.I) for a in amounts):
            # A bare "L" is easily a misread I, 1 or | (e.g. "1 L" read from can noise).
            return FieldResult("net_contents", Verdict.CHECK,
                               f'Label may say "{amounts[0].text}". Application says "{app.net_contents}". Please look.',
                               code="NET_CONTENTS_MISMATCH", found=amounts[0].text)
        return FieldResult("net_contents", Verdict.FAIL,
                           f'Label says "{amounts[0].text}". Application says "{app.net_contents}".',
                           code="NET_CONTENTS_MISMATCH", found=amounts[0].text)
    if app.beverage_type == "malt" and all(a.metric for a in amounts):
        # A real deficiency (27 CFR 7.70(c)), but TTB's practice is approval with a qualification requiring
        # fluid ounces (e.g. TTB ID 23328001000154), unless U.S. units are molded into the container.
        return FieldResult("net_contents", Verdict.CHECK,
                           f'Label shows only metric ("{match.text}"). Malt beverages must state U.S. units such as '
                           f'"12 FL. OZ."; metric may be added but not used instead (27 CFR 7.70). Unless the ounces are '
                           f'molded into the container, approval needs a qualification to add them.',
                           code="NET_CONTENTS_UNITS", found=match.text)
    fills = {"spirits": SPIRITS_FILLS, "wine": WINE_FILLS}.get(app.beverage_type)
    if fills and not any(_same(match.ml, f) for f in fills):
        return FieldResult("net_contents", Verdict.CHECK,
                           f'"{match.text}" is not an authorized container size for {app.beverage_type}.',
                           code="NET_CONTENTS_NOT_STANDARD", found=match.text)
    return FieldResult("net_contents", Verdict.PASS, f'Label says "{match.text}".', found=match.text)
