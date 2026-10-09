"""Net contents (RULES.md §4; 27 CFR 4.37, 4.72, 5.70, 5.203, 7.70)."""

import re
from dataclasses import dataclass

from .model import Application, FieldResult, Verdict

ML_PER = {"ml": 1, "cl": 10, "l": 1000, "fl oz": 29.5735, "pint": 473.176, "quart": 946.353, "gal": 3785.41}

# Authorized standards of fill, in mL.
SPIRITS_FILLS = {3750, 3000, 2000, 1800, 1750, 1500, 1000, 945, 900, 750, 720, 710, 700, 570, 500,
                 475, 375, 355, 350, 331, 250, 200, 187, 100, 50}
WINE_FILLS = {3000, 2250, 1800, 1500, 1000, 750, 720, 700, 620, 600, 568, 550, 500, 473, 375, 360,
              355, 330, 300, 250, 200, 187, 180, 100, 50}

# A whole number only: not the tail of a longer one, nor a number right after a lone digit ("7 50 ML" is not a clear
# 50 mL: the reader split 750). The unit may be glued to what follows ("750mL40%ALC/VOL") or joined by a dash.
_N = r"(?<![\d.,])(?<!(?<![\d.,])\d\s)(\d+(?:[.,]\d+)?)"  # "070 750mL" (a barcode before it) is fine
_TO = r"(?:\s*|-)"  # "750 ML", "750ML", "750-ML"; not "2 - L" (noise)
_END = r"(?![a-z])"
_UNIT_PATTERNS = [
    ("fl oz", re.compile(rf"{_N}{_TO}(?:u\.?s\.?\s*)?fl(?:uid)?\.?\s*(?:oz\.?|ounces?{_END})", re.I)),
    ("pint", re.compile(rf"{_N}{_TO}(?:pints?|pts?){_END}\.?", re.I)),
    ("quart", re.compile(rf"{_N}{_TO}(?:quarts?|qts?){_END}\.?", re.I)),
    ("gal", re.compile(rf"{_N}{_TO}(?:u\.?s\.?\s*)?gal(?:lons?|\.)?{_END}", re.I)),
    ("ml", re.compile(rf"{_N}{_TO}(?:ml|millilit(?:er|re)s?){_END}", re.I)),
    ("cl", re.compile(rf"{_N}{_TO}(?:cl|centilit(?:er|re)s?){_END}", re.I)),
    ("l", re.compile(rf"{_N}{_TO}(?:l|ltrs?|lit(?:er|re)s?){_END}(?!\s*/)", re.I)),
]
# "1 PINT 8 FL. OZ.", "1 PT, 3.2 FL. OZ.", "1 PINT 9.4 FL" (after a pint, "fl" can only be fluid ounces)
_COMPOUND = re.compile(r"(\d+)\s*(?:pints?|pts?)\.?[\s,]*(\d+(?:\.\d+)?)\s*fl(?:uid)?\.?(?:\s*(?:oz|ounces?))?", re.I)


# Common malt beverage containers (fluid ounces), used only to tell a second container size from other numbers.
MALT_SIZES_ML = {round(oz * ML_PER["fl oz"]) for oz in (7, 8, 8.4, 10, 11.2, 12, 14.9, 16, 16.9, 19.2, 22, 24, 25, 25.4,
                                                        32, 40, 64)}


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
            num = m.group(1)
            # "1,750" is a thousands separator; "0,75" (European style) is a decimal comma
            value = float(num.replace(",", "") if re.fullmatch(r"\d{1,3},\d{3}", num) else num.replace(",", "."))
            found.append(Amount(value * ML_PER[unit], m.group(0).strip(), unit in ("ml", "cl", "l")))
            taken.append(m.span())
    return found


def parse_amount(text: str) -> float | None:
    amounts = find_amounts(text)
    return amounts[0].ml if amounts else None


def parse_typed_net(text: str, beverage_type: str) -> float | None:
    """What the agent typed as net contents -> mL, or None when it isn't one clear amount. Forgiving of how it is
    written ("750mls", "750 m l", "12oz", ".75 L"); a bare number takes the usual unit ("750" or "1.75" for spirits and
    wine, "12" for beer). Anything that doesn't read as exactly one amount is refused rather than guessed."""
    t = re.sub(r"\bm\s+l\b", "ml", text.strip().lower())
    t = re.sub(r"(?<=\d)\s*mls\b", " ml", t)
    t = re.sub(r"(?<=\d)oz\b", " oz", t)
    t = re.sub(r"\b(fl\.?\s*)?oz\b", lambda m: m.group(0) if m.group(1) else "fl oz", t)  # ounces of a drink are fluid ounces
    if re.fullmatch(r"\d+(?:[.,]\d+)?|[.,]\d+", t):
        n = float(t.replace(",", "."))
        unit = "fl oz" if beverage_type == "malt" else "ml" if n >= 50 else "l" if n < 10 else None
        return n * ML_PER[unit] if unit else None
    amounts = find_amounts(re.sub(r"(?<![\d.,])([.,]\d)", r"0\1", t))  # ".75 L"
    if not amounts or any(not _same(a.ml, amounts[0].ml) for a in amounts):
        return None
    return amounts[0].ml


def _same(a: float, b: float) -> bool:
    """Equal up to unit-conversion rounding (12 fl oz = 354.9 mL), but 350 mL and 355 mL are different sizes."""
    return abs(a - b) <= max(1.5, 0.004 * b)


def check_net_contents(app: Application, lines: list[str]) -> FieldResult:
    if not app.net_contents:
        return FieldResult("net_contents", Verdict.NOT_APPLICABLE, "No net contents declared; not checked.")
    expected = parse_typed_net(app.net_contents, app.beverage_type)
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
    fills = {"spirits": SPIRITS_FILLS, "wine": WINE_FILLS}.get(app.beverage_type)
    if fills is WINE_FILLS:  # § 4.72(b): wine may also come in even liters from 4 L up
        fills = fills | {a.ml for a in amounts if a.ml >= 3999 and _same(a.ml, round(a.ml / 1000) * 1000)}
    # Another clearly different container size on the label ("750 ML" and "1 L"). Serving statements ("1.5 fl oz"),
    # misreads of the same size ("15L" for "1.5L") and numbers that aren't a container size don't count.
    sizes = fills or MALT_SIZES_ML
    digits = lambda a: re.sub(r"\D", "", a.text)
    others = [a for a in amounts if not _same(a.ml, expected) and any(_same(a.ml, f) for f in sizes)
              and not (match and digits(a).strip("0") == digits(match).strip("0"))]
    if match and others:  # two different sizes read (a misread, or a gift pack): a person decides
        return FieldResult("net_contents", Verdict.CHECK,
                           f'Label shows "{match.text}" and also "{others[0].text}". Application says '
                           f'"{app.net_contents}". Please look.', code="NET_CONTENTS_CONFLICT", found=match.text)
    if not match:
        if fills and not any(_same(a.ml, f) for a in amounts for f in fills):
            # Not a legal container size for this product: far more likely a misread ("760ml" for 750 mL).
            return FieldResult("net_contents", Verdict.CHECK,
                               f'Label may say "{amounts[0].text}", which is not a standard size for {app.beverage_type}. '
                               f'Application says "{app.net_contents}". Please look.',
                               code="NET_CONTENTS_MISMATCH", found=amounts[0].text)
        if all(re.fullmatch(r"[\d.,]+(?:\s*|-)l", a.text, re.I) for a in amounts):
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
    if fills and not any(_same(match.ml, f) for f in fills):
        return FieldResult("net_contents", Verdict.CHECK,
                           f'"{match.text}" is not an authorized container size for {app.beverage_type}.',
                           code="NET_CONTENTS_NOT_STANDARD", found=match.text)
    return FieldResult("net_contents", Verdict.PASS, f'Label says "{match.text}".', found=match.text)
