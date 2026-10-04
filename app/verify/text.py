"""Text normalization and finding expected values in label text (RULES.md §2)."""

import re
import unicodedata

from rapidfuzz import fuzz

from .model import FieldResult, Verdict

PASS_SCORE = 95
CHECK_SCORE = 85
MAX_LINES_JOINED = 3  # a value may wrap across up to 3 label lines

_PUNCT_MAP = str.maketrans({"’": "'", "‘": "'", "“": '"', "”": '"',
                            "–": "-", "—": "-", " ": " "})


def normalize(text: str) -> str:
    """Case, accents, punctuation and spacing ignored; apostrophes inside words kept."""
    text = unicodedata.normalize("NFKC", text).translate(_PUNCT_MAP)
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"(?<=\w)'(?=\w)", "\x00", text)    # protect in-word apostrophes
    text = re.sub(r"[^\w\s\x00]", " ", text).replace("\x00", "'")
    return " ".join(text.split())


def _class_spelling(text: str) -> str:
    """§ 5.143: "The word whisky may be spelled as either 'whisky' or 'whiskey'." Class/type only."""
    return re.sub(r"\bwhiskey\b", "whisky", text)


def _windows(lines: list[str]):
    """Each line, and each run of up to MAX_LINES_JOINED consecutive lines joined."""
    for i in range(len(lines)):
        for n in range(1, MAX_LINES_JOINED + 1):
            if i + n <= len(lines):
                yield " ".join(lines[i:i + n])


def match_text(field: str, expected: str, lines: list[str], extra_words: Verdict = Verdict.FAIL) -> FieldResult:
    """Find `expected` in the label lines.

    A label line (or a few joined lines) must match the whole value. If the value only
    appears inside a longer line ("Old Tom" inside "Old Tom Reserve"), that is a different
    value, and `extra_words` decides how serious that is.
    """
    norm = (lambda t: _class_spelling(normalize(t))) if field == "class_type" else normalize
    want = norm(expected)
    best_score, best_text = 0.0, None
    for window in _windows(lines):
        score = fuzz.ratio(want, norm(window))
        if score > best_score:
            best_score, best_text = score, window
    if best_score >= PASS_SCORE:
        return FieldResult(field, Verdict.PASS, f'Label shows "{best_text}".', found=best_text)

    contained = next((ln for ln in lines if re.search(rf"(?<!\S){re.escape(want)}(?!\S)", norm(ln))), None)
    if contained:
        return FieldResult(field, extra_words,
                           f'Label shows "{contained}", which adds words to "{expected}".',
                           code=f"{field.upper()}_EXTRA_WORDS", found=contained)
    if best_score >= CHECK_SCORE:
        return FieldResult(field, Verdict.CHECK,
                           f'Label shows "{best_text}", which is close to "{expected}" but not the same.',
                           code=f"{field.upper()}_NEAR_MATCH", found=best_text)
    return FieldResult(field, Verdict.FAIL, f'"{expected}" was not found on the label.',
                       code=f"{field.upper()}_MISMATCH")


def words_present(field: str, expected: str, lines: list[str]) -> FieldResult:
    """Looser check for multi-part statements (name and address): share of expected words found."""
    want = normalize(expected).split()
    have = set(normalize(" ".join(lines)).split())
    share = sum(w in have for w in want) / len(want) if want else 1.0
    if share >= 0.9:
        return FieldResult(field, Verdict.PASS, "Name and address found on the label.")
    if share >= 0.7:
        missing = [w for w in want if w not in have]
        return FieldResult(field, Verdict.CHECK, f"Some words were not found: {', '.join(missing)}.",
                           code=f"{field.upper()}_PARTIAL")
    return FieldResult(field, Verdict.FAIL, f'"{expected}" was not found on the label.',
                       code=f"{field.upper()}_MISMATCH")
