"""Picture-only checks (RULES.md §6a): an item left blank on the form is not compared; the app looks for the statement
the rules require on the label instead (mandatory label information: 27 CFR 4.32 wine, 5.63 spirits, 7.63 malt).
  On the label   the statement was found (verdict PASS with code ON_LABEL, shown as "On the label", not "Matches");
  Please check   a required statement was not found, or the label shows two different values;
  Not checked    the statement is not required for this product.
Never Does not match: there is no application value to compare with.
read_values() turns the same findings into suggested form values ("read from the label, please confirm"). The brand is
not suggested: it is usually a logo, and on 142 approved labels the largest line read was the brand only 24 times.
"""

import re

from .abv import _TABLE_WINE, AbvReading, find_abv, find_proof
from .model import FieldResult, Verdict
from .net_contents import MALT_SIZES_ML, SPIRITS_FILLS, WINE_FILLS, find_amounts

ON_LABEL = "ON_LABEL"
FILLS = {"spirits": SPIRITS_FILLS, "wine": WINE_FILLS}
MANDATORY = {"spirits": "27 CFR 5.63", "wine": "27 CFR 4.32", "malt": "27 CFR 7.63"}

# Words that name a class or type (27 CFR 5.141-5.156 spirits, 4.21 wine, 7.141-7.147 malt beverages).
CLASS_WORDS = {
    "spirits": r"whiske?y|bourbon|scotch|vodka|gin|rum|ron|brandy|cognac|armagnac|calvados|tequila|mezcal|liqueur|"
               r"cordial|schnapps|absinthe|grappa|pisco|cacha[cç]a|aquavit|akvavit|soju|shochu|baijiu|sotol|"
               r"(?:neutral|agave|grain|cane|distilled)\s+spirits?|spirit\s+whiske?y|cocktail|bitters|amaro|arak|ouzo",
    "wine": r"wine|vino|vin|champagne|sparkling|prosecco|cava|port|porto|sherry|madeira|marsala|vermouth|sake|mead|"
            r"cider|perry|ros[eé]|cabernet|merlot|pinot|chardonnay|sauvignon|riesling|zinfandel|syrah|shiraz|malbec|"
            r"tempranillo|sangiovese|nebbiolo|grenache|garnacha|moscato|muscat|gew[uü]rztraminer|viognier|chenin|"
            r"barbera|carmen[eè]re|petite?\s+sirah|semillon|albari[nñ]o|gr[uü]ner|lambrusco|chianti|rioja|bordeaux|"
            r"burgundy|meritage|claret",
    "malt": r"beer|ale|lager|stout|porter|pilsn?er|pils|ipa|bock|doppelbock|hefeweizen|weizen|weiss|witbier|wit|"
            r"saison|k[oö]lsch|gose|lambic|kriek|tripel|dubbel|quad|helles|m[aä]rzen|oktoberfest|dunkel|altbier|"
            r"malt\s+(?:beverage|liquor)|hard\s+seltzer|hard\s+(?:iced\s+)?tea|hard\s+lemonade|shandy|radler",
}
_CLASS = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in CLASS_WORDS.items()}
_BOTTLER = re.compile(r"\b(?:bottled|distilled|produced|imported|brewed|vinted|cellared|blended|made|packed|packaged|"
                      r"canned|manufactured|prepared|crafted|aged|finished|rectified|fermented|grown)\b"
                      r"[\w\s,&/.]{0,40}?\b(?:by|for)\b", re.I)
COUNTRIES = ("Argentina", "Australia", "Austria", "Barbados", "Belgium", "Brazil", "Bulgaria", "Canada", "Chile",
             "China", "Colombia", "Croatia", "Great Britain", "Cuba", "Czech Republic", "Denmark", "Dominican Republic", "England",
             "Estonia", "Finland", "France", "Georgia", "Germany", "Greece", "Guatemala", "Guyana", "Haiti", "Hungary",
             "Iceland", "India", "Ireland", "Israel", "Italy", "Jamaica", "Japan", "Korea", "Latvia", "Lebanon",
             "Lithuania", "Mexico", "Moldova", "Netherlands", "Holland", "New Zealand", "Nicaragua", "Nigeria", "Northern Ireland",
             "Norway", "Panama", "Peru", "Philippines", "Poland", "Portugal", "Puerto Rico", "Romania", "Russia",
             "Scotland", "Serbia", "Slovakia", "Slovenia", "South Africa", "Spain", "Sweden", "Switzerland", "Taiwan",
             "Thailand", "Trinidad", "Turkey", "Ukraine", "United Kingdom", "Uruguay", "Venezuela", "Vietnam", "Wales")
# "Product of Italy", "Wine of Australia", and the same in Spanish and French ("Hecho en México", "Produit de France").
_COUNTRY = re.compile(r"\b(?:product|produce|made|distilled|brewed|bottled|imported|produced|wine|hecho|producto|produit)"
                      r"\s+(?:of|in|from|en|de|du)\s+(?:the\s+)?("
                      + "|".join(c.replace(" ", r"\s+").replace("Mexico", "M[eé]xico") for c in COUNTRIES) + r")\b", re.I)


# Lines that name a type in passing, not the designation: a sentence ("this beer is"), a company ("GIN DISTILLERS").
_NOT_DESIGNATION = re.compile(r"\b(?:is|are|was|this|our|we|you|your|its|has|have|from\s+the|notes\s+of|pairs?|"
                              r"llc|inc|co|company|cellars|distillers|distillery|brewery|winery|vineyards)\b", re.I)
_DESIGNATION_WORDS = re.compile(r"\b(?:straight|blended|bottled\s+in\s+bond|single|small\s+batch|kentucky|tennessee|"
                                r"india|pale|imperial|double|hazy|red|white|dry|sparkling|flavou?red|distilled|"
                                r"natural|with|and|style|reserve|aged|grain|malt|corn|rye|wheat|light)\b", re.I)


def _class_line(lines, kind):
    """The class or type designation: a short line with the kind's type word, the one with the most designation
    words ("KENTUCKY STRAIGHT BOURBON WHISKEY" over "TOASTED BOURBON"); never a sentence, a company or the bottler."""
    best, score = None, None
    for i, line in enumerate(lines):
        if not _CLASS[kind].search(line) or _NOT_DESIGNATION.search(line) or _BOTTLER.search(line):
            continue
        words = line.split()
        if len(words) > 8:
            continue
        s = (len(_CLASS[kind].findall(line)) + len(_DESIGNATION_WORDS.findall(line)), -i)
        if score is None or s > score:
            best, score = line.strip(), s
    return best


def _found(field, text, why):
    return FieldResult(field, Verdict.PASS, f"Not given on the application. The label shows {why}.", code=ON_LABEL,
                       found=text)


def _line(lines, pattern):
    """(line, match) of the first line where the pattern is found; a line ending in a comma continues on the next
    ("... Louisville," / "KY")."""
    for i, line in enumerate(lines):
        m = pattern.search(line)
        if m:
            while line.rstrip().endswith(",") and i + 1 < len(lines):
                i += 1
                line = f"{line.rstrip()} {lines[i].strip()}"
            return line, m
    return None, None


def class_present(kind, lines):
    line = _class_line(lines, kind) or _line(lines, _CLASS[kind])[0]
    if line:
        return _found("class_type", line, "a class or type")
    return FieldResult("class_type", Verdict.CHECK,
                       f"No class or type designation (like {'bourbon whisky or vodka' if kind == 'spirits' else 'red wine or Cabernet Sauvignon' if kind == 'wine' else 'ale or lager'}) "
                       f"was found. It is required ({MANDATORY[kind]}). Please check.", code="CLASS_NOT_FOUND")


def _abv_values(lines):
    readings = [r for r in find_abv(" ".join(lines)) if not r.below]
    distinct = []
    for r in readings:
        if all(abs(r.value - d.value) > 0.15 for d in distinct):  # "48.5" beside "48.59" is a misread, not two values
            distinct.append(r)
    return distinct


# "13.5% Ale./Vol.", "7%akc/vel", "ALC30% byvol": alcohol wording the reader got slightly wrong. Used only when no
# clear statement was read, and only for a value this kind of product can have.
_LOOSE_ABV = re.compile(r"(?<![\d.,])(\d{1,2}(?:[.,]\d{1,2})?)\s*%{1,2}\s*\W{0,2}\s*(?:a[l1|][ceo](?![a-z])|a[uk]c|by\s*vol)"
                        r"|\ba[l1|][ce]\W{0,2}(\d{1,2}(?:[.,]\d{1,2})?)\s*%", re.I)
_PLAUSIBLE = {"malt": 16, "wine": 24, "spirits": 95}


def label_abv(kind, lines) -> list[AbvReading]:
    """The alcohol contents the label states. Two different ones are settled by the proof when it agrees with
    exactly one ("53.5% ALC./VOL." and a misread "3.5% ALC." beside "107 PROOF")."""
    values = _abv_values(lines)
    text = " ".join(lines)
    if len(values) > 1:
        agree = [v for v in values if any(abs(p / 2 - v.value) < 0.15 for p in find_proof(text))]
        return agree if len(agree) == 1 else values
    if values:
        return values
    loose = {}
    for m in _LOOSE_ABV.finditer(text):
        value = float((m.group(1) or m.group(2)).replace(",", "."))
        if 0 < value <= _PLAUSIBLE.get(kind, 95):
            loose.setdefault(value, AbvReading(value, m.group(0).strip()))
    return list(loose.values()) if len(loose) == 1 else []


def abv_present(kind, lines):
    values = label_abv(kind, lines)
    if len(values) > 1:
        return FieldResult("abv", Verdict.CHECK, f'The label shows two different alcohol contents: "{values[0].text}" '
                           f'and "{values[1].text}". Please check.', code="ABV_CONFLICT", found=values[0].text)
    if values:
        return _found("abv", values[0].text, "its alcohol content")
    text = " ".join(lines)
    if kind == "spirits":
        return FieldResult("abv", Verdict.CHECK, "No alcohol content was found. It is required on spirits "
                           "(27 CFR 5.65). Please check.", code="ABV_NOT_FOUND")
    if kind == "wine":
        table = _TABLE_WINE.search(text)
        if table:
            return _found("abv", table.group(0), f'"{table.group(0)}" instead of a number, allowed at 14% or less '
                          "(27 CFR 4.36)")
        return FieldResult("abv", Verdict.CHECK, 'No alcohol content was found. Wine must state it, unless it is '
                           '14% or less and says "table wine" or "light wine" (27 CFR 4.36). Please check.',
                           code="ABV_NOT_FOUND")
    return FieldResult("abv", Verdict.NOT_APPLICABLE, "Not given, and no alcohol content found on the label. Beer "
                       "does not have to state it under federal rules (27 CFR 7.65).")


def _sizes(kind, lines):
    """Container sizes on the label, in reading order; the ones allowed for this product first."""
    text = " ".join(lines)
    amounts = sorted(find_amounts(text), key=lambda a: text.find(a.text))
    allowed = FILLS.get(kind) or MALT_SIZES_ML
    # A bare "L" after a number is often a stray letter ("2024 L", "1829 L"): a whole number of liters over 60 is
    # dropped, and liters come after amounts in mL or ounces, which a reader rarely makes up.
    amounts = [a for a in amounts if not (re.fullmatch(r"\d+\s*l", a.text, re.I) and a.ml > 60000)]
    return sorted(amounts, key=lambda a: (not any(abs(a.ml - f) <= max(1.0, f * 0.01) for f in allowed),
                                          bool(re.fullmatch(r"[\d.,]+\s*l\.?", a.text, re.I))))


def net_present(kind, lines):
    sizes = _sizes(kind, lines)
    if not sizes:
        return FieldResult("net_contents", Verdict.CHECK, "No net contents were found. It is required "
                           f"({MANDATORY[kind]}), though it may be molded into the bottle. Please check.",
                           code="NET_CONTENTS_NOT_FOUND")
    first = sizes[0]
    fills = FILLS.get(kind)
    if fills and not any(abs(first.ml - f) <= max(1.0, f * 0.01) for f in fills):
        return FieldResult("net_contents", Verdict.CHECK, f'The label may say "{first.text}", which is not a standard '
                           f"size for {kind} ({'27 CFR 5.203' if kind == 'spirits' else '27 CFR 4.72'}). Please check.",
                           code="NET_CONTENTS_NOT_STANDARD", found=first.text)
    return _found("net_contents", first.text, "its net contents")


def bottler_present(kind, lines):
    line, m = _line(lines, _BOTTLER)
    if line:
        return _found("name_address", line[m.start():].strip(), "a bottler or importer statement")
    return FieldResult("name_address", Verdict.CHECK, 'No "Bottled by", "Produced by", "Brewed by" or "Imported by" '
                       f"statement was found. A name and address is required ({MANDATORY[kind]}). Please check.",
                       code="NAME_ADDRESS_NOT_FOUND")


def country_present(lines):
    line, m = _line(lines, _COUNTRY)
    if line:
        return _found("country_of_origin", m.group(0), "a country of origin statement")
    return FieldResult("country_of_origin", Verdict.CHECK, 'Imported, but no "Product of …" statement was found '
                       "(19 CFR 134.11). It may be on the container. Please check.", code="COUNTRY_NOT_FOUND")


# When no class word decides it, what else every label of that kind carries: who made it and how ("Brewed by",
# "Distillery", "Vinted"), proof (spirits only), "contains sulfites" (wine), a vintage year beside a wine region.
_CLUES = {k: re.compile(rf"\b(?:{v})", re.I) for k, v in {
    "spirits": r"distill|proof\b|spirits?\b|liquor\b|agave|single\s+malt|barrel\s+aged|cask|aged\s+\d+\s+years",
    "wine": r"vinted|vintner|winery|wines?\b|vineyards?|cellars?\b|estate\s+bottled|contains\s+sulfites|sulfites|"
            r"grapes?|appellation|ava\b|varietal|sangria",
    "malt": r"brew|brewing|brewery|hops?\b|hopped|barley|malt\b|ibu\b|keg\b|barrel\s+\(?bbl|1/2\s*bbl|on\s+tap",
}.items()}


def guess_kind(lines):
    """spirits / wine / malt when the label's class words point clearly to one (or, with none, its other words do),
    else None."""
    text = " ".join(lines)
    clues = {k: len(p.findall(text)) for k, p in _CLUES.items()}
    # Over 24% alcohol is never wine (27 CFR 4.21) nor beer: spirits, when the label says anything of spirits
    # ("Whisky finished in sherry casks" has more wine words than spirits words).
    values = _abv_values(lines)  # every reading over 24%: "48 %alc" beside "4.8 % alc./vol." is a misread lager
    if values and all(v.value > 24 for v in values) and (clues["spirits"] or _CLASS["spirits"].search(text)):
        return "spirits"
    hits = {k: len(p.findall(text)) for k, p in _CLASS.items()}
    top = max(hits.values())
    tied = [k for k, n in hits.items() if n == top] if top else list(hits)
    if len(tied) == 1:
        return tied[0]
    best = max(tied, key=clues.get)  # class words tie (or there are none): the other words decide, among the tied
    return best if clues[best] and sorted(clues[k] for k in tied)[-2] < clues[best] else None


def read_values(lines, kind=None) -> dict:
    """Suggested form values read from the label (only the ones found). The agent confirms every one."""
    kind = kind or guess_kind(lines)
    out = {"beverage_type": kind} if kind else {}
    values = label_abv(kind, lines)
    if len(values) == 1:
        out["abv"] = f"{values[0].value:g}"
    sizes = _sizes(kind, lines)
    if sizes:
        out["net_contents"] = sizes[0].text
    if kind:
        line = _class_line(lines, kind) or _line(lines, _CLASS[kind])[0]
        if line:
            out["class_type"] = line
    line, m = _line(lines, _BOTTLER)
    if line:
        out["name_address"] = line[m.start():].strip()
    line, m = _line(lines, _COUNTRY)
    if line:
        name = re.sub(r"\s+", " ", m.group(1)).lower().replace("é", "e")
        out["country_of_origin"] = next(c for c in COUNTRIES if c.lower() == name)
        out["source"] = "imported"
    return {k: v for k, v in out.items() if v}

