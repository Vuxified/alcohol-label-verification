"""Rules a label must follow on its own, checked from its text (RULES.md §6b). Citations checked against the eCFR text
of 2026-10-07. A broken rule is Please check with the rule quoted: the agent decides, and a misread number must not
become a refusal. A rule that does not apply to the label adds nothing; one that applies and is met is Matches.

  abv_minimum  spirits classes are bottled at 40% or more (vodka 5.142, whisky 5.143, gin 5.144, brandy 5.145,
               rum 5.147, agave spirits 5.148); flavored spirits at 30% or more (5.151). Only for a plain class line
               at 20% or more: liqueurs, specialties and mixed drinks have no class minimum.
  bonded       "Bottled in bond" means bottled at exactly 50% (100 proof) (5.88(a)(6)).
  wine_terms   "Table wine" / "light wine" only at 14% or less (4.21(a)(5), 4.36(a)); Part 4 covers wine of 7% to
               24% (4.6).
  malt_terms   "Low alcohol" / "reduced alcohol" only under 2.5% (7.65(d)); "non-alcoholic" only with "contains less
               than 0.5 percent (or .5%) alcohol by volume" (7.65(e)); "alcohol free" only with no alcohol (7.65(f)).
"""

import re

from .model import Application, FieldResult, Verdict
from .presence import _abv_values

CLASSES = (  # (pattern, name, section)
    (r"vodka", "vodka", "5.142"),
    (r"whiske?y|bourbon|scotch", "whisky", "5.143"),
    (r"gin", "gin", "5.144"),
    (r"brandy|cognac|armagnac", "brandy", "5.145"),
    (r"rum", "rum", "5.147"),
    (r"tequila|mezcal", "agave spirits (tequila, mezcal)", "5.148"),
)
_CLASS = re.compile(r"\b(?:" + "|".join(p for p, _, _ in CLASSES) + r")\b", re.I)
# The class line must be a class name and nothing else ("Kentucky Straight Bourbon Whiskey", "London Dry Gin",
# "Cherry Flavored Vodka"): any other word ("coffee meets premium vodka", "whiskey with sugar", "vodka soda") makes it a
# specialty, liqueur or mixed drink, which has no class minimum.
_PLAIN = re.compile(r"(?:\b(?:vodka|whiske?y|bourbon|scotch|gin|brandy|cognac|armagnac|rum|ron|tequila|mezcal|"
                    r"straight|kentucky|tennessee|rye|wheat|corn|malt|single|blended|irish|canadian|american|japanese|"
                    r"london|dry|old|tom|aged|years?|reserve|silver|gold|white|dark|black|anejo|añejo|reposado|blanco|"
                    r"plata|joven|extra|xo|vs|vsop|v\.s\.o\.p|napoleon|fine|apple|grape|pot|still|small|batch|barrel|"
                    r"cask|strength|double|triple|distilled|from|grain|potato|cane|agave|de|bottled|in|bond|"
                    r"flavou?red|natural|flavou?rs?|cherry|vanilla|cinnamon|honey|lemon|lime|orange|citrus|peach|"
                    r"raspberry|strawberry|coconut|pineapple|mango|spiced|with)\b|[\s\d%.,\-/()'’])+", re.I)
SPECIALTY_BELOW = 20  # under this a spirits class name is a ready-to-drink or specialty product, not a short spirit
_FLAVORED = re.compile(r"\bflavou?r", re.I)
_BOND = re.compile(r"\bbottled[\s-]+in[\s-]+bond\b", re.I)
_TABLE = re.compile(r"\b(table|light)\s+wine\b", re.I)
_LOW = re.compile(r"\b(low|reduced)[\s-]+alcohol\b", re.I)
_NON = re.compile(r"\bnon[\s-]*alcoholic\b", re.I)
_NON_STATEMENT = re.compile(r"less\s+than\s+(?:0?\.5|one[\s-]+half\s+(?:of\s+)?(?:one\s+)?)\s*(?:%|percent)", re.I)
_FREE = re.compile(r"\balcohol[\s-]+free\b", re.I)


def _abv(app, lines):
    """The one alcohol content on the label (else the application's); None when unclear."""
    values = _abv_values(lines)
    if len(values) > 1:
        return None
    return values[0].value if values else app.abv


def _check(field, rule, why):
    return FieldResult(field, Verdict.CHECK, f"{why} {rule} Please check.", code=field.upper())


def abv_minimum(app, lines, abv):
    """From the label's own class line: the application's class is a broad registry code ("VODKA" is also used for
    vodka-based specialties), so it is not used here."""
    text = next((ln for ln in lines if _CLASS.search(ln)), None)
    if not text or abv is None or abv < SPECIALTY_BELOW or not _PLAIN.fullmatch(text):
        return None
    if re.search(r"\bwith\b", text, re.I) and not _FLAVORED.search(text):  # "whiskey with sugar": a specialty
        return None
    word = _CLASS.search(text).group(0)
    name, sec = next((n, s) for p, n, s in CLASSES if re.fullmatch(p, word, re.I))
    if _FLAVORED.search(text):
        name, sec, need = f"flavored {name}", "5.151", 30
    else:
        need = 40
    rule = f"27 CFR {sec}: {name} is bottled at not less than {need}% alcohol by volume ({2 * need}° proof)."
    if abv + 1e-9 < need:
        return _check("abv_minimum", rule, f'The label shows {abv:g}% for "{text.strip()}".')
    return FieldResult("abv_minimum", Verdict.PASS, f"{abv:g}% meets the {need}% minimum for {name} (27 CFR {sec}).")


def bonded(lines, abv):
    if not _BOND.search(" ".join(lines)) or abv is None:
        return None
    rule = 'A "bottled in bond" spirit is bottled at 50% alcohol by volume, 100 proof (27 CFR 5.88(a)(6)).'
    if abs(abv - 50) > 0.05:
        return _check("bonded", rule, f'The label says "bottled in bond" but shows {abv:g}%.')
    return FieldResult("bonded", Verdict.PASS, "Bottled in bond at 50% (100 proof), as 27 CFR 5.88(a)(6) requires.")


def wine_terms(lines, abv):
    if abv is None:
        return None
    table = _TABLE.search(" ".join(lines))
    if table and abv > 14:
        return _check("wine_terms", f'"{table.group(0).title()}" is wine of not more than 14% alcohol by volume '
                      "(27 CFR 4.21(a)(5), 4.36(a)).", f'The label says "{table.group(0)}" and shows {abv:g}%.')
    if not 7 <= abv <= 24:
        return _check("wine_terms", "The wine labeling rules (27 CFR part 4) apply to wine of 7% to 24% alcohol by "
                      "volume (27 CFR 4.6); outside that range other rules apply.", f"The label shows {abv:g}%.")
    if table:
        return FieldResult("wine_terms", Verdict.PASS, f'"{table.group(0)}" at {abv:g}%: within 14% (27 CFR 4.21).')
    return None


def malt_terms(lines, abv):
    text = " ".join(lines)
    low, non, free = _LOW.search(text), _NON.search(text), _FREE.search(text)
    if low and abv is not None:
        if abv >= 2.5:
            return _check("malt_terms", f'"{low.group(0)}" may be used only on malt beverages under 2.5% alcohol by '
                          "volume (27 CFR 7.65(d)).", f'The label says "{low.group(0)}" and shows {abv:g}%.')
        return FieldResult("malt_terms", Verdict.PASS, f'"{low.group(0)}" at {abv:g}%: under 2.5% (27 CFR 7.65(d)).')
    if non:
        if not _NON_STATEMENT.search(text):
            return _check("malt_terms", '"Non-alcoholic" needs the statement "contains less than 0.5 percent (or .5%) '
                          'alcohol by volume" right beside it (27 CFR 7.65(e)).',
                          f'The label says "{non.group(0)}", but that statement was not found.')
        return FieldResult("malt_terms", Verdict.PASS,
                           '"Non-alcoholic" with "contains less than 0.5% alcohol by volume" (27 CFR 7.65(e)).')
    if free and re.search(r"(?<![\d.])0(?:\.0+)?\s*%", text) and not abv:
        return FieldResult("malt_terms", Verdict.PASS, '"Alcohol free" at 0.0% (27 CFR 7.65(f)).')
    if free and abv is not None:
        if abv > 0:
            return _check("malt_terms", '"Alcohol free" may be used only on malt beverages containing no alcohol '
                          "(27 CFR 7.65(f)).", f'The label says "{free.group(0)}" and shows {abv:g}%.')
        return FieldResult("malt_terms", Verdict.PASS, '"Alcohol free" at 0.0% (27 CFR 7.65(f)).')
    return None


def label_rules(app: Application, lines: list[str]) -> list[FieldResult]:
    abv = _abv(app, lines)
    if app.beverage_type == "spirits":
        found = [abv_minimum(app, lines, abv), bonded(lines, abv)]
    elif app.beverage_type == "wine":
        found = [wine_terms(lines, abv)]
    else:
        found = [malt_terms(lines, abv)]
    return [f for f in found if f]
