"""Check one application: read its label images, run the rules, and keep the evidence (DESIGN.md §2).

The rules in app/verify stay pure and take text lines. The warning is judged across every independent reading
(warning_judge.py) instead of one joined text. Two safety rules from RULES.md §1 apply on top:
  - A reading problem never becomes "Does not match": a warning that could not be found while the label shows
    signs of it (anchor words, a pass that ran out of time) is "Please check".
  - "Does not match" for the warning wording needs two different engines showing the same change.
"""

import re
import time
from dataclasses import dataclass, field

from app.ocr.reader import ApplicationReading, Reader
from app.verify import Application, FieldResult, Verdict, verify
from app.verify.model import SEVERITY
from app.verify.verify import NON_ALCOHOLIC_BELOW
from app.verify.warning_judge import judge_detail

ANCHORS = re.compile(r"surgeon|pregnan|machinery|consumption|impairs", re.I)
OTHER_FIELDS = ("brand_name", "abv", "net_contents")


@dataclass
class CheckResult:
    application: Application
    fields: list[FieldResult]
    reading: ApplicationReading
    seconds: float
    notes: list[str] = field(default_factory=list)

    @property
    def overall(self) -> Verdict:
        return max((f.verdict for f in self.fields), key=SEVERITY.__getitem__, default=Verdict.PASS)


def _others_ok(app: Application):
    """Trigger for the whole-label passes: brand, alcohol and net contents all matched."""
    def ok(lines):
        report = verify(app, lines)
        return all(f.verdict in (Verdict.PASS, Verdict.NOT_APPLICABLE)
                   for f in report.fields if f.field in OTHER_FIELDS)
    return ok


def _words(words: list[str], show: int = 6) -> str:
    """The first few words, then a count, so a mostly unread warning doesn't print 30 words."""
    shown = ", ".join(f'"{w}"' for w in words[:show])
    return shown + (f" and {len(words) - show} more" if len(words) > show else "")


def warning_fields(reading: ApplicationReading) -> list[FieldResult]:
    d = judge_detail(reading.warning_readings())
    if not d["found"]:
        hints = any(ANCHORS.search(r.text) for r in reading.readings)
        late = any(t.startswith(("zoom", "sideways", "flip")) for t in reading.dropped)
        if hints or late:
            why = ("Parts of the warning were read, but not the whole statement." if hints
                   else "Text printed sideways or very small was not read in time.")
            return [FieldResult("warning_text", Verdict.CHECK,
                                f"{why} The warning may be printed sideways, curved or very small. Please look at the label.",
                                code="WARNING_NOT_READ"),
                    FieldResult("warning_caps", Verdict.NOT_APPLICABLE, "Warning not read.")]
        return [FieldResult("warning_text", Verdict.CHECK,
                            'The "GOVERNMENT WARNING" statement was not found on any image. If it is on another side of '
                            "the container, add a picture of that side.", code="WARNING_MISSING"),
                FieldResult("warning_caps", Verdict.NOT_APPLICABLE, "No warning found.")]
    if not d["missing"]:
        text = FieldResult("warning_text", Verdict.PASS, "Warning text matches 27 CFR 16.21 word for word.")
    elif d["words_strong"]:
        text = FieldResult("warning_text", Verdict.FAIL,
                           "Two independent readings show the warning worded differently near: "
                           + _words(d["missing"]) + ".", code="WARNING_TEXT_ALTERED")
    else:
        text = FieldResult("warning_text", Verdict.CHECK,
                           "Some words of the warning could not be confirmed: " + _words(d["missing"])
                           + ". Please compare it with 27 CFR 16.21.", code="WARNING_UNCONFIRMED")
    if not d["caps"] or any(d["caps"]):
        caps = FieldResult("warning_caps", Verdict.PASS, '"GOVERNMENT WARNING" is in capital letters.')
    elif d["caps_strong"]:
        caps = FieldResult("warning_caps", Verdict.FAIL, '"GOVERNMENT WARNING" is not in capital letters (27 CFR 16.22).',
                           code="WARNING_NOT_CAPS")
    else:
        caps = FieldResult("warning_caps", Verdict.CHECK, "The heading may not be in capital letters. Please look.",
                           code="WARNING_CAPS_UNCONFIRMED")
    return [text, caps]


def check_application(reader: Reader, app: Application, images: list[tuple[str, bytes]]) -> CheckResult:
    t0 = time.perf_counter()
    reading = reader.read(images, fields_ok=_others_ok(app))
    report = verify(app, reading.lines())
    fields = [f for f in report.fields if not f.field.startswith("warning")]
    if app.abv is not None and app.abv < NON_ALCOHOLIC_BELOW:
        fields += [f for f in report.fields if f.field.startswith("warning")]  # not required below 0.5% alcohol
    else:
        fields += warning_fields(reading)
    notes = []
    if any(t.startswith(("tesseract", "inverted")) for t in reading.dropped):
        fields = [FieldResult(f.field, Verdict.CHECK, f.reason + " Part of the label was not read in time; please check.",
                              code=f.code, found=f.found)
                  if f.verdict == Verdict.FAIL and f.code and f.code.endswith(("MISSING", "NOT_FOUND", "MISMATCH")) else f
                  for f in fields]
        if any(f.verdict == Verdict.CHECK for f in fields):  # only worth saying when something wasn't confirmed
            notes.append("Some extra reading passes ran out of time; anything not found is marked Please check.")
    return CheckResult(app, fields, reading, round(time.perf_counter() - t0, 3), notes)
