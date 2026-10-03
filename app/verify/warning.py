"""Government Health Warning Statement (RULES.md §5; 27 CFR 16.21, 16.22)."""

import difflib
import re

from .model import FieldResult, Verdict

REQUIRED = ("GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink "
            "alcoholic beverages during pregnancy because of the risk of birth defects. "
            "(2) Consumption of alcoholic beverages impairs your ability to drive a car or "
            "operate machinery, and may cause health problems.")
HEADING = "GOVERNMENT WARNING"
MIN_CAPS_SHARE = 0.9  # tolerates one ambiguous glyph from OCR


def _tokens(text: str) -> list[str]:
    """Words with hyphenation across line breaks rejoined ("BE- CAUSE", "BE-CAUSE" -> "BECAUSE")."""
    text = re.sub(r"(\w)-\s+(\w)", r"\1\2", text)
    text = re.sub(r"(?<=[a-zA-Z])-(?=[a-zA-Z])", "", text)
    return re.findall(r"\(?\w+\)?[:.,]?", text)


def _word(token: str) -> str:
    return re.sub(r"\W", "", token).casefold()


REQUIRED_TOKENS = _tokens(REQUIRED)
REQUIRED_WORDS = [_word(t) for t in REQUIRED_TOKENS]


def _find_heading(tokens: list[str]) -> int | None:
    words = [_word(t) for t in tokens]
    for i in range(len(words) - 1):
        if words[i] == "government" and words[i + 1] == "warning":
            return i
    return None


def check_warning(lines: list[str]) -> list[FieldResult]:
    """Returns two results: warning_text and warning_caps."""
    tokens = _tokens(" ".join(lines))
    start = _find_heading(tokens)
    if start is None:
        missing = FieldResult("warning_text", Verdict.FAIL, 'The "GOVERNMENT WARNING" statement was not found.',
                              code="WARNING_MISSING")
        return [missing, FieldResult("warning_caps", Verdict.NOT_APPLICABLE, "No warning found.")]

    window = tokens[start:start + len(REQUIRED_TOKENS) + 8]
    found_words = [_word(t) for t in window]
    matcher = difflib.SequenceMatcher(a=REQUIRED_WORDS, b=found_words, autojunk=False)
    changes = []
    last_b = 0
    for op, a1, a2, b1, b2 in matcher.get_opcodes():
        if op == "equal":
            last_b = b2
            continue
        if op == "insert" and a1 == len(REQUIRED_WORDS):
            break  # text after the statement ends is not part of it
        want = " ".join(REQUIRED_TOKENS[a1:a2]) or "(nothing)"
        got = " ".join(window[b1:b2]) or "(missing)"
        changes.append(f'"{want}" → "{got}"')
        last_b = max(last_b, b2)
    printed = " ".join(window[:last_b])

    if changes:
        text_result = FieldResult("warning_text", Verdict.FAIL,
                                  "Warning wording differs from 27 CFR 16.21: " + "; ".join(changes),
                                  code="WARNING_TEXT_ALTERED", found=printed)
    elif _punctuation(window[:last_b]) != _punctuation(REQUIRED_TOKENS):
        # Approved labels sometimes drop a period; words are what the rule protects.
        text_result = FieldResult("warning_text", Verdict.CHECK,
                                  "Warning words match, but punctuation differs slightly. Please confirm.",
                                  code="WARNING_PUNCTUATION", found=printed)
    else:
        text_result = FieldResult("warning_text", Verdict.PASS, "Warning text matches 27 CFR 16.21 word for word.",
                                  found=printed)

    heading = " ".join(tokens[start:start + 2])
    letters = [c for c in heading if c.isalpha()]
    caps_share = sum(c.isupper() for c in letters) / len(letters)
    if caps_share >= MIN_CAPS_SHARE:
        caps_result = FieldResult("warning_caps", Verdict.PASS, f'Heading is in capital letters: "{heading}".', found=heading)
    else:
        caps_result = FieldResult("warning_caps", Verdict.FAIL,
                                  f'Heading must be in capital letters ("GOVERNMENT WARNING"); label shows "{heading}" (27 CFR 16.22).',
                                  code="WARNING_NOT_CAPS", found=heading)
    return [text_result, caps_result]


def _punctuation(tokens: list[str]) -> str:
    return "".join(c for t in tokens for c in t if c in ":.,()")
