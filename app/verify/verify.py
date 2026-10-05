"""Run every rule for one application against the text read from its label images."""

from .abv import check_abv, check_proof
from .model import Application, FieldResult, Report, Verdict
from .net_contents import check_net_contents
from .text import match_text, words_present
from .warning import check_warning

NON_ALCOHOLIC_BELOW = 0.5  # % ABV; "alcoholic beverage" starts at 0.5% (27 CFR 16.10)


def verify(app: Application, lines: list[str]) -> Report:
    """`lines` is all text read from every image of the application, one entry per printed line."""
    report = Report()
    report.fields.append(match_text("brand_name", app.brand_name, lines))
    if app.class_type:
        report.fields.append(match_text("class_type", app.class_type, lines))
    non_alcoholic = app.abv is not None and app.abv < NON_ALCOHOLIC_BELOW
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
    result = words_present("country_of_origin", country, lines)
    if result.verdict == Verdict.FAIL:
        # TTB has approved imports without a "Product of" line (country may be on the container).
        return FieldResult("country_of_origin", Verdict.CHECK, f'"{country}" was not found on the label. Please confirm.',
                           code="COUNTRY_NOT_FOUND")
    return result
