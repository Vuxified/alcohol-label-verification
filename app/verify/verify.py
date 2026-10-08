"""Run every rule for one application against the text read from its label images."""

import re

from .abv import check_abv, check_proof, find_abv
from .model import Application, FieldResult, Report, Verdict
from .net_contents import check_net_contents
from .text import match_text, normalize, words_present
from .warning import check_warning

NON_ALCOHOLIC_BELOW = 0.5  # % ABV; "alcoholic beverage" starts at 0.5% (27 CFR 16.10)


def is_non_alcoholic(app: Application, lines: list[str]) -> bool:
    """Declared under 0.5% and the label doesn't show 0.5% or more (a typo like 0.4 for 40 must not switch checks off)."""
    if app.abv is None or app.abv >= NON_ALCOHOLIC_BELOW:
        return False
    return not any(r.value >= NON_ALCOHOLIC_BELOW for r in find_abv(" ".join(lines)))


def verify(app: Application, lines: list[str]) -> Report:
    """`lines` is all text read from every image of the application, one entry per printed line."""
    report = Report()
    report.fields.append(match_text("brand_name", app.brand_name, lines))
    if app.fanciful_name:
        report.fields.append(match_text("fanciful_name", app.fanciful_name, lines))
    if app.class_type:
        report.fields.append(match_text("class_type", app.class_type, lines))
    non_alcoholic = is_non_alcoholic(app, lines)
    if non_alcoholic:
        report.fields.append(FieldResult("abv", Verdict.NOT_APPLICABLE,
                                         f"Declared {app.abv:g}% (non-alcoholic); alcohol content rules not checked."))
    else:
        report.fields.append(check_abv(app, lines))
        report.fields.append(check_proof(app, lines))
    report.fields.append(check_net_contents(app, lines))
    if app.name_address:
        report.fields.append(words_present("name_address", app.name_address, lines))
    if app.source == "imported" and app.country_of_origin:
        report.fields.append(_check_country(app.country_of_origin, lines))
    if non_alcoholic:
        report.fields.append(FieldResult("warning_text", Verdict.NOT_APPLICABLE,
                                         "Health Warning not required below 0.5% alcohol (27 CFR 16.10)."))
    else:
        report.fields.extend(check_warning(lines))
    return report


def _check_country(country: str, lines: list[str]) -> FieldResult:
    """The country must appear as a country statement ("Product of Mexico", "Imported from …", "Made in …") or on a
    line of its own. Inside other text it proves nothing ("Santa Fe, New Mexico"), so that is Please check."""
    want = re.escape(normalize(country))
    stated = re.compile(rf"\b(product|produce|produced|made|brewed|distilled|bottled|imported|origin|hecho)\b"
                        rf"[a-z ]{{0,15}}\b(of|in|from|en)\s+{want}$|^{want}$")
    for line in lines:
        if stated.search(normalize(line)) and not re.search(rf"\bnew\s+{want}\b", normalize(line)):
            return FieldResult("country_of_origin", Verdict.PASS, f'Label shows "{line}".', found=line)
    # TTB has approved imports without a "Product of" line (country may be on the container).
    return FieldResult("country_of_origin", Verdict.CHECK,
                       f'No "Product of {country}" statement was found on the label. Please confirm the country of origin.',
                       code="COUNTRY_NOT_FOUND")
