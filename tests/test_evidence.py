"""Evidence boxes and the warning verdict mapping, with fake readings (no OCR)."""

from app.evidence import locate
from app.ocr.reader import ApplicationReading, Reading
from app.pipeline import warning_fields
from app.verify import Verdict
from app.verify.warning import REQUIRED


def words(text, y=10, x0=0):
    out, x = [], x0
    for t in text.split():
        out.append((t, 0.9, (x, y, x + 10 * len(t), y + 12)))
        x += 10 * len(t) + 6
    return out


def test_locate_finds_the_words_and_their_box():
    frame = [words("OLD TOM DISTILLERY") + words("45% Alc./Vol. (90 Proof)", y=40)]
    pic, box = locate("45% Alc./Vol.", frame)
    assert pic == 0 and box[1] == 40 and box[0] == 0


def test_locate_on_the_right_picture():
    frames = [words("FRONT LABEL BRAND"), words("750 mL", y=30)]
    assert locate("750 mL", frames)[0] == 1


def test_locate_nothing_close():
    assert locate("Kentucky Straight Bourbon", [words("Vodka 750 mL")]) is None


def reading(*texts):
    return ApplicationReading(pictures=[], turns=[0],
                              readings=[Reading(0, fam, "main", t) for fam, t in texts])


def test_warning_match():
    text, caps = warning_fields(reading(("onnx", REQUIRED)))
    assert text.verdict == Verdict.PASS and caps.verdict == Verdict.PASS


def test_warning_changed_word_seen_by_two_engines_fails():
    altered = REQUIRED.replace("may cause", "can cause")
    text, _ = warning_fields(reading(("onnx", altered), ("tess", altered)))
    assert text.verdict == Verdict.FAIL and text.code == "WARNING_TEXT_ALTERED"


def test_warning_changed_word_seen_by_one_engine_is_please_check():
    altered = REQUIRED.replace("may cause", "can cause")
    text, _ = warning_fields(reading(("onnx", altered)))
    assert text.verdict == Verdict.CHECK


def test_warning_not_read_but_anchor_words_seen_is_please_check():
    text, _ = warning_fields(reading(("onnx", "SURGEON ... PREGNANCY ... MACHINERY")))
    assert text.verdict == Verdict.CHECK and text.code == "WARNING_NOT_READ"


def test_warning_absent_fails():
    text, _ = warning_fields(reading(("onnx", "OLD TOM DISTILLERY 750 mL")))
    assert text.verdict == Verdict.FAIL and text.code == "WARNING_MISSING"


def test_title_case_heading_by_two_engines_fails_caps():
    tc = REQUIRED.replace("GOVERNMENT WARNING", "Government Warning")
    _, caps = warning_fields(reading(("onnx", tc), ("tess", tc)))
    assert caps.verdict == Verdict.FAIL
