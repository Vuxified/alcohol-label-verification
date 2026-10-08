"""Text normalization and finding expected values in label text (RULES.md §2)."""

import re
import unicodedata

from rapidfuzz import fuzz

from .model import FieldResult, Verdict

CHECK_SCORE = 85  # close enough to show as "Please check"; a match needs the same text (case, punctuation, spacing aside)
MAX_LINES_JOINED = 3  # a value may wrap across up to 3 label lines
# "Bottled by …", "Produced & bottled by …", "Imported by …": the name in this line is the bottler, not proof of the brand.
_BOTTLER = re.compile(r"\b(bottled|produced|brewed|vinted|distilled|imported|blended|cellared|made|canned)\b[^.]{0,40}?\bby\b", re.I)

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


def match_text(field: str, expected: str, lines: list[str]) -> FieldResult:
    """Find `expected` in the label lines.

    A label line (or a few joined lines) must match the whole value. If the value only
    appears inside a longer line ("Old Tom" inside "Old Tom Reserve", or inside the bottler line
    "BOTTLED BY OLD TOM DISTILLERY"), a person decides. Not finding a value is never "Does not
    match": it may be printed in decorative type the reader could not read (RULES.md §1).
    """
    norm = (lambda t: _class_spelling(normalize(t))) if field == "class_type" else normalize
    want = norm(expected)
    best_score, best_text = 0.0, None
    for window in _windows(lines):
        got = norm(window)
        # The reader sometimes drops the space between words ("FourRoses"): spacing alone never decides.
        if got.replace(" ", "") == want.replace(" ", ""):
            return FieldResult(field, Verdict.PASS, f'Label shows "{window}".', found=window)
        # Anything else is at best close: one character can be "10" vs "12" in a long name, so never a match.
        score = max(fuzz.ratio(want, got), fuzz.ratio(want.replace(" ", ""), got.replace(" ", "")))
        if score > best_score:
            best_score, best_text = score, window

    contained = next((ln for ln in lines if re.search(rf"(?<!\S){re.escape(want)}(?!\S)", norm(ln))), None)
    if contained and _BOTTLER.search(contained):
        return FieldResult(field, Verdict.CHECK,
                           f'"{expected}" was found only in the bottler line ("{contained}"). The brand itself may be '
                           'in decorative lettering the reader could not read; please look at the label.',
                           code=f"{field.upper()}_EXTRA_WORDS", found=contained)
    if contained:
        return FieldResult(field, Verdict.CHECK,
                           f'Label shows "{contained}", which adds words to "{expected}".',
                           code=f"{field.upper()}_EXTRA_WORDS", found=contained)
    if best_score >= CHECK_SCORE:
        return FieldResult(field, Verdict.CHECK,
                           f'Label shows "{best_text}", which is close to "{expected}" but not the same.',
                           code=f"{field.upper()}_NEAR_MATCH", found=best_text)
    return FieldResult(field, Verdict.CHECK,
                       f'"{expected}" was not found on the label. It may be in decorative type the reader could not read.',
                       code=f"{field.upper()}_MISMATCH")


def words_present(field: str, expected: str, lines: list[str]) -> FieldResult:
    """Multi-part statements (name and address): every expected word must be on the label to match. A missing word
    may be a different street or city, or text the reader missed, so it is "Please check", never "Does not match"."""
    want = normalize(expected).split()
    have = set(normalize(" ".join(lines)).split())
    missing = [w for w in want if w not in have]
    if not missing:
        return FieldResult(field, Verdict.PASS, "Name and address found on the label.")
    if len(missing) < len(want):
        return FieldResult(field, Verdict.CHECK, f"Some words were not found: {', '.join(missing)}.",
                           code=f"{field.upper()}_PARTIAL")
    return FieldResult(field, Verdict.CHECK, f'"{expected}" was not found on the label. Please look.',
                       code=f"{field.upper()}_MISMATCH")
