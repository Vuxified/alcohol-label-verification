"""Run every rule for one application against the text read from its label images."""

import re

from .abv import check_abv, check_proof, find_abv
from .model import Application, FieldResult, Report, Verdict
from .net_contents import check_net_contents
from .label_rules import label_rules
from .presence import _COUNTRY, COUNTRIES, ON_LABEL, abv_present, bottler_present, class_present, country_present, net_present
from .text import match_text, normalize, words_present
from .warning import check_warning

NON_ALCOHOLIC_BELOW = 0.5  # % ABV; "alcoholic beverage" starts at 0.5% (27 CFR 16.10)


def is_non_alcoholic(app: Application, lines: list[str]) -> bool:
    """Declared under 0.5% and the label doesn't show 0.5% or more (a typo like 0.4 for 40 must not switch checks off)."""
    if app.abv is None or app.abv >= NON_ALCOHOLIC_BELOW:
        return False
    return not any(r.value >= NON_ALCOHOLIC_BELOW and not r.below for r in find_abv(" ".join(lines)))


def verify(app: Application, lines: list[str]) -> Report:
    """`lines` is all text read from every image of the application, one entry per printed line."""
    report = Report()
    kind = app.beverage_type
    alone = not app.brand_name  # picture only: blank items are looked for on the label (presence.py), not skipped
    report.fields.append(match_text("brand_name", app.brand_name, lines) if app.brand_name else FieldResult(
        "brand_name", Verdict.NOT_APPLICABLE, "Not given on the application, so not compared."))
    if app.fanciful_name:
        report.fields.append(match_text("fanciful_name", app.fanciful_name, lines))
    if app.class_type:
        report.fields.append(match_text("class_type", app.class_type, lines))
    elif alone:
        report.fields.append(class_present(kind, lines))
    non_alcoholic = is_non_alcoholic(app, lines)
    if non_alcoholic:
        report.fields.append(FieldResult("abv", Verdict.NOT_APPLICABLE,
                                         f"Declared {app.abv:g}% (non-alcoholic); alcohol content rules not checked."))
    else:
        report.fields.append(abv_present(kind, lines) if alone and app.abv is None else check_abv(app, lines))
        report.fields.append(check_proof(app, lines))
    report.fields.extend(label_rules(app, lines))
    report.fields.append(net_present(kind, lines) if alone and not app.net_contents else check_net_contents(app, lines))
    if app.name_address:
        report.fields.append(words_present("name_address", app.name_address, lines))
    elif alone:
        report.fields.append(bottler_present(kind, lines))
    if app.source == "imported" and app.country_of_origin:
        report.fields.append(_check_country(app.country_of_origin, lines))
    elif app.source == "imported" and alone:
        report.fields.append(country_present(lines))
    if app.source == "imported":
        report.fields.append(_check_importer(kind, lines))
    if non_alcoholic:
        report.fields.append(FieldResult("warning_text", Verdict.NOT_APPLICABLE,
                                         "Health Warning not required below 0.5% alcohol (27 CFR 16.10)."))
    else:
        report.fields.extend(check_warning(lines))
    return report


# The same country in its own language, as labels print it either way. Scotland, England and Wales are not names for
# the United Kingdom here: an application saying United Kingdom for "Product of Scotland" is for a person to judge.
_SAME_COUNTRY = [{"italy", "italia"}, {"spain", "espana"}, {"germany", "deutschland"},
                 {"netherlands", "nederland", "holland"}, {"switzerland", "schweiz", "suisse", "svizzera"},
                 {"austria", "osterreich"}, {"belgium", "belgique", "belgie"}, {"greece", "hellas", "ellada"},
                 {"czech republic", "czechia", "ceska republika"}, {"japan", "nihon", "nippon"},
                 {"united kingdom", "great britain"}, {"united states", "usa", "united states of america"}]
# "Imported by …", "Exclusively imported by …", "Importer: …" (27 CFR 4.35(b), 5.68, 7.68: "imported by" or a similar
# phrase, then the importer's name and address).
# The phrase must be one statement: "Imported from Tuscany. Bottled by …" names no importer.
_IMPORTER = re.compile(r"\bimport(?:ed|er|ers)\s+(?:(?:and|&)\s+[a-z]+\s+)?(?:exclusively\s+)?(?:by|for)\b"
                       r"|\bimporters?\s*:", re.I)
_IMPORTER_RULE = {"spirits": "5.68", "wine": "4.35", "malt": "7.68"}


def _country_names(country: str) -> set[str]:
    name = re.sub(r"^the\s+", "", normalize(country))  # "The Netherlands"
    return next((group for group in _SAME_COUNTRY if name in group), {name})


def _check_country(country: str, lines: list[str]) -> FieldResult:
    """The country must appear as a country statement ("Product of Mexico", "Imported from …", "Made in …") or on a
    line of its own. Inside other text it proves nothing ("Santa Fe, New Mexico"), so that is Please check. A label
    that also names another country ("Bottled in Spain") is for a person to judge."""
    names = _country_names(country)
    want = "(?:" + "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True)) + ")"
    # "Product of (the) Mexico", "Brewed in Munich, Germany", "Produit de France", "Hecho en México"; other text may
    # follow on the same line ("PRODUCT OF MEXICO 750 ML"), as the reader often joins neighbouring lines.
    stated = re.compile(rf"\b(product|produce|produced|made|brewed|distilled|bottled|imported|origin|hecho|produit|"
                        rf"producto|prodotto|elaborado|embotellado)\b[a-z ]{{0,15}}\b(of|in|from|en|de|di)\s+"
                        rf"(?:the\s+)?(?:[a-z]+\s+){{0,2}}?{want}\b(?!\s+city\b)|^(?:the\s+)?{want}$")
    for line in lines:
        if stated.search(normalize(line)) and not re.search(rf"\bnew\s+{want}\b", normalize(line)):
            # Typed as the label prints it ("Product of Ireland"): the country named inside is not "another" one.
            typed = " ".join(names)
            ours = names | {n for c in COUNTRIES if re.search(rf"\b{re.escape(normalize(c))}\b", typed)
                            for n in _country_names(c)}
            other = next((ln for ln in lines for m in _COUNTRY.finditer(ln)
                          if not _country_names(m.group(1)) & ours), None)
            if other:
                return FieldResult("country_of_origin", Verdict.CHECK,
                                   f'Label shows "{line}", but also "{other}". Please confirm the country of origin.',
                                   code="COUNTRY_SEVERAL", found=line)
            return FieldResult("country_of_origin", Verdict.PASS, f'Label shows "{line}".', found=line)
    # TTB has approved imports without a "Product of" line (country may be on the container).
    return FieldResult("country_of_origin", Verdict.CHECK,
                       f'No "Product of {country}" statement was found on the label. Please confirm the country of origin.',
                       code="COUNTRY_NOT_FOUND")


def _check_importer(kind: str, lines: list[str]) -> FieldResult:
    """Imports must say who imported them: "Imported by" or a similar phrase, then the importer's name and address.
    Found is "On the label" (the statement is there; its name is not compared); not found is Please check."""
    text = " ".join(lines)
    if m := _IMPORTER.search(text):
        return FieldResult("importer", Verdict.PASS, "The label has an importer statement.", code=ON_LABEL,
                           found=text[m.start():m.start() + 80].rsplit(" ", 1)[0].strip())  # "Imported by Old Tom Imports, New York, NY"
    return FieldResult("importer", Verdict.CHECK, 'Imported, but no "Imported by" statement naming the importer was '
                       f"found (27 CFR {_IMPORTER_RULE.get(kind, '5.68')}). Please check.", code="IMPORTER_NOT_FOUND")
