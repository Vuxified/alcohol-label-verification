"""Picture-only checks (RULES.md §6a): an item left blank on the form is not compared; the app looks for the statement
the rules require on the label instead (mandatory label information: 27 CFR 4.32 wine, 5.63 spirits, 7.63 malt).
  On the label   the statement was found (verdict PASS with code ON_LABEL, shown as "On the label", not "Matches");
  Please check   a required statement was not found, or the label shows two different values;
  Not checked    the statement is not required for this product.
Never Does not match: there is no application value to compare with.
read_values() turns the same findings into suggested form values ("read from the label, please confirm").
"""

import re

from .abv import _TABLE_WINE, find_abv
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
            r"malt\s+(?:beverage|liquor)|hard\s+seltzer|shandy|radler",
}
_CLASS = {k: re.compile(rf"\b(?:{v})\b", re.I) for k, v in CLASS_WORDS.items()}
_BOTTLER = re.compile(r"\b(?:bottled|distilled|produced|imported|brewed|vinted|cellared|blended|made|packed|packaged|"
                      r"canned|manufactured|prepared|crafted|aged|finished|rectified|fermented|grown)\b"
                      r"[\w\s,&/.]{0,40}?\b(?:by|for)\b", re.I)
COUNTRIES = ("Argentina", "Australia", "Austria", "Barbados", "Belgium", "Brazil", "Bulgaria", "Canada", "Chile",
             "China", "Colombia", "Croatia", "Cuba", "Czech Republic", "Denmark", "Dominican Republic", "England",
             "Estonia", "Finland", "France", "Georgia", "Germany", "Greece", "Guatemala", "Guyana", "Haiti", "Hungary",
             "Iceland", "India", "Ireland", "Israel", "Italy", "Jamaica", "Japan", "Korea", "Latvia", "Lebanon",
             "Lithuania", "Mexico", "Moldova", "Netherlands", "Holland", "New Zealand", "Nicaragua", "Northern Ireland",
             "Norway", "Panama", "Peru", "Philippines", "Poland", "Portugal", "Puerto Rico", "Romania", "Russia",
             "Scotland", "Serbia", "Slovakia", "Slovenia", "South Africa", "Spain", "Sweden", "Switzerland", "Taiwan",
             "Thailand", "Trinidad", "Turkey", "Ukraine", "United Kingdom", "Uruguay", "Venezuela", "Vietnam", "Wales")
_COUNTRY = re.compile(r"\b(?:product|produce|made|distilled|brewed|bottled|imported|produced)\s+(?:of|in|from)\s+"
                      r"(?:the\s+)?(" + "|".join(c.replace(" ", r"\s+") for c in COUNTRIES) + r")\b", re.I)


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
    line, _ = _line(lines, _CLASS[kind])
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


def abv_present(kind, lines):
    values = _abv_values(lines)
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
    return sorted(amounts, key=lambda a: not any(abs(a.ml - f) <= max(1.0, f * 0.01) for f in allowed))


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


def guess_kind(lines):
    """spirits / wine / malt when the label's class words point clearly to one, else None."""
    text = " ".join(lines)
    hits = {k: len(p.findall(text)) for k, p in _CLASS.items()}
    best = max(hits, key=hits.get)
    return best if hits[best] and sorted(hits.values())[-2] < hits[best] else None


def read_values(lines, kind=None) -> dict:
    """Suggested form values read from the label (only the ones found). The agent confirms every one."""
    kind = kind or guess_kind(lines)
    out = {"beverage_type": kind} if kind else {}
    values = _abv_values(lines)
    if len(values) == 1:
        out["abv"] = f"{values[0].value:g}"
    sizes = _sizes(kind, lines)
    if sizes:
        out["net_contents"] = sizes[0].text
    if kind:
        line, _ = _line(lines, _CLASS[kind])
        if line:
            out["class_type"] = line
    line, m = _line(lines, _BOTTLER)
    if line:
        out["name_address"] = line[m.start():].strip()
    line, m = _line(lines, _COUNTRY)
    if line:
        name = re.sub(r"\s+", " ", m.group(1)).lower()
        out["country_of_origin"] = next(c for c in COUNTRIES if c.lower() == name)
        out["source"] = "imported"
    return {k: v for k, v in out.items() if v}


def brand_guess(frame_words):
    """The largest line of print on the first picture (usually the brand), or None. Only a suggestion."""
    words = [w for w in (frame_words[0] if frame_words else []) if any(c.isalpha() for c in w[0])]
    if not words:
        return None
    h = lambda w: w[2][3] - w[2][1]
    mid = lambda w: (w[2][1] + w[2][3]) / 2
    top = max(words, key=h)
    line = sorted((w for w in words if abs(mid(w) - mid(top)) < 0.5 * h(top) and h(w) >= 0.6 * h(top)),
                  key=lambda w: w[2][0])
    return " ".join(w[0] for w in line)
