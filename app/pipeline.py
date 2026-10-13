"""Check one application: read its label images, run the rules, and keep the evidence.

The rules in app/verify stay pure and take text lines. The warning is judged across every independent reading
(warning_judge.py) instead of one joined text. Two safety rules from RULES.md §1 apply on top:
  - A reading problem never becomes "Does not match": a warning that could not be found while the label shows
    signs of it (anchor words, a pass that ran out of time) is "Please check".
  - "Does not match" for the warning wording needs two different engines showing the same change, and so does a
    different alcohol content or net contents: Tesseract re-reads that spot (confirm_differences).
"""

import re
import time
from dataclasses import dataclass, field, replace

import cv2

from app.evidence import locate
from app.ocr.engine import tesseract
from app.ocr.reader import ApplicationReading, Reader
from app.bold import bold_field
from app.typesize import size_field
from app.quality import quality_note
from app.verify import Application, FieldResult, Verdict, verify
from app.verify.abv import check_abv
from app.verify.model import SEVERITY
from app.verify.net_contents import check_net_contents
from app.verify.text import match_text
from app.verify.presence import ON_LABEL, guess_kind
from app.verify.verify import is_non_alcoholic
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


def guessed_name(kind: str) -> str:
    return {"spirits": "distilled spirits", "wine": "wine", "malt": "beer or malt beverage"}[kind]


class UnknownProduct(Exception):
    """The type of product was left blank and the label doesn't show clearly which it is."""


def _others_ok(app: Application):
    """Trigger for the whole-label passes: brand, alcohol and net contents all matched."""
    def ok(lines):
        report = verify(app if app.beverage_type else replace(app, beverage_type=guess_kind(lines) or "spirits"), lines)
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
    if d["extra"] and not d["missing"]:  # never Does not match: text beside the warning can mix into every reading
        text = FieldResult("warning_text", Verdict.CHECK,
                           "The warning may contain added words: " + _words(d["extra"])
                           + ". Please compare it with 27 CFR 16.21.", code="WARNING_UNCONFIRMED")
    elif not d["missing"]:
        text = FieldResult("warning_text", Verdict.PASS, "Warning text matches 27 CFR 16.21 word for word.")
    elif d["words_strong"]:
        text = FieldResult("warning_text", Verdict.FAIL,
                           "Two independent readings show the warning worded differently near: "
                           + _words(d["missing"]) + ".", code="WARNING_TEXT_ALTERED")
    else:
        text = FieldResult("warning_text", Verdict.CHECK,
                           "Some words of the warning could not be confirmed: " + _words(d["missing"])
                           + ". Please compare it with 27 CFR 16.21.", code="WARNING_UNCONFIRMED")
    if not d["caps"] or all(d["caps"]):
        caps = FieldResult("warning_caps", Verdict.PASS, '"GOVERNMENT WARNING" is in capital letters.')
    elif d["caps_strong"]:
        caps = FieldResult("warning_caps", Verdict.FAIL, '"GOVERNMENT WARNING" is not in capital letters (27 CFR 16.22).',
                           code="WARNING_NOT_CAPS")
    else:
        caps = FieldResult("warning_caps", Verdict.CHECK, "The heading may not be in capital letters. Please look.",
                           code="WARNING_CAPS_UNCONFIRMED")
    return [text, caps]


def _second_reader(crop):
    return tesseract(crop, 7)


def _again(f: FieldResult, app: Application, seen: str) -> FieldResult:
    """The rule run again on the second reader's text of the same spot."""
    if f.field == "abv":
        return check_abv(app, [seen])
    if f.field == "net_contents":
        return check_net_contents(app, [seen])
    return match_text(f.field, getattr(app, f.field), [seen])


def _needs_second_reading(f: FieldResult) -> bool:
    return f.verdict == Verdict.FAIL and (f.field in ("abv", "net_contents")
                                          or (f.code or "").endswith(("_NUMBER_DIFFERS", "_WORD_DIFFERS")))


def confirm_differences(fields, frames, frame_words, app: Application, read=_second_reader) -> list[FieldResult]:
    """A different alcohol content, net contents, or number or product word in a name or class stays "Does not match"
    only when Tesseract, reading the same spot on its own, sees the same difference; otherwise "Please check" (one
    misread digit or word must not fail a label)."""
    out = []
    for f in fields:
        if not _needs_second_reading(f):
            out.append(f)
            continue
        spot = locate(f.found, frame_words)
        seen = ""
        if spot:
            k, (x0, y0, x1, y1) = spot
            h = y1 - y0
            crop = frames[k][max(0, int(y0 - 0.4 * h)):int(y1 + 0.4 * h), max(0, int(x0 - h)):int(x1 + h)]
            s = max(1.0, 64 / max(1, crop.shape[0]))  # small print enlarged, as Tesseract reads best near 30 px letters
            seen = read(cv2.resize(crop, None, fx=s, fy=s, interpolation=cv2.INTER_CUBIC)).strip()
            again = _again(f, app, seen)
            if (again.verdict == Verdict.FAIL and again.code == f.code
                    and re.sub(r"\D", "", again.found or "") == re.sub(r"\D", "", f.found)):
                out.append(f)
                continue
        why = (f'A second reading of that spot saw "{seen}", so the difference is not confirmed.' if seen
               else "A second reading of that spot could not confirm it.")
        out.append(FieldResult(f.field, Verdict.CHECK, f"{f.reason} {why} Please look.", code=f.code, found=f.found))
    return out


def check_application(reader: Reader, app: Application, images: list[tuple[str, bytes]]) -> CheckResult:
    t0 = time.perf_counter()
    reading = reader.read(images, fields_ok=_others_ok(app))
    guessed = None
    if not app.beverage_type:  # left blank: told by the label's class words ("Bourbon", "Cabernet", "Lager")
        guessed = guess_kind(reading.lines())
        if guessed is None:
            raise UnknownProduct
        app = replace(app, beverage_type=guessed)
    report = verify(app, reading.lines())
    fields = confirm_differences([f for f in report.fields if not f.field.startswith("warning")],
                                 reading.frames, reading.frame_words, app)
    if is_non_alcoholic(app, reading.lines()):
        fields += [f for f in report.fields if f.field.startswith("warning")]  # not required below 0.5% alcohol
    else:
        fields += warning_fields(reading)
        if not any(f.code in ("WARNING_MISSING", "WARNING_NOT_READ") for f in fields):  # bold only if a warning was read
            fields.append(bold_field(reading.frames, reading.frame_words))
            net = next((f.found for f in fields if f.field == "net_contents" and f.code == ON_LABEL), None)
            fields.append(size_field(reading.frames, reading.frame_words,
                                     replace(app, net_contents=net) if net and not app.net_contents else app))
    notes = [f"Type of product: {guessed_name(guessed)}, told from the label."] if guessed else []
    if any(t.startswith(("tesseract", "inverted")) for t in reading.dropped):
        fields = [FieldResult(f.field, Verdict.CHECK, f.reason + " Part of the label was not read in time; please check.",
                              code=f.code, found=f.found)
                  if f.verdict == Verdict.FAIL and f.code and f.code.endswith(("MISSING", "NOT_FOUND", "MISMATCH")) else f
                  for f in fields]
        if any(f.verdict == Verdict.CHECK for f in fields):  # only worth saying when something wasn't confirmed
            notes.append("Some extra reading passes ran out of time; anything not found is marked Please check.")
    if any(f.verdict == Verdict.CHECK for f in fields):  # a hint about the pictures, only when something is unsure
        hint = quality_note(reading.pictures, reading.frame_words)
        if hint:
            notes.append(hint)
    return CheckResult(app, fields, reading, round(time.perf_counter() - t0, 3), notes)
