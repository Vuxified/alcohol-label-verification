"""Marks shown on the results page. Display only: verdicts are decided in app/verify and app/pipeline."""

import re
from difflib import SequenceMatcher

from app.verify.warning import REQUIRED
from app.verify.warning_judge import REQ, align, extra_words, slot_evidence


def _key(word: str) -> str:
    return re.sub(r"[^0-9a-z]", "", word.lower())


def differing_words(asked: str | None, found: str | None):
    """-> (asked words, found words), each a list of (word, differs), or None when either is missing.
    Case and punctuation are ignored, as in the rules. When the two share no word, nothing is marked."""
    if not asked or not found:
        return None
    a, b = asked.split(), found.split()
    ops = SequenceMatcher(None, [_key(w) for w in a], [_key(w) for w in b], autojunk=False).get_opcodes()
    da, db = [False] * len(a), [False] * len(b)
    if any(tag == "equal" for tag, *_ in ops):
        for tag, i1, i2, j1, j2 in ops:
            if tag != "equal":
                da[i1:i2] = [True] * (i2 - i1)
                db[j1:j2] = [True] * (j2 - j1)
    return list(zip(a, da)), list(zip(b, db))


def warning_marks(readings):
    """The required warning text as parts (text, kind) for display, or None when no reading has the warning.
    kind: None (confirmed or punctuation), "missing" (no reading shows this required word),
    "label" (what a reading shows in its place), "extra" (a word a reading shows that isn't required)."""
    pairs = [a for a in (align(t) for _, t in readings if t) if a is not None]
    if not pairs:
        return None
    missing = {i for i in range(len(REQ)) if all(a[0][i] is None for a in pairs)}
    shown = {}
    for i in missing:
        for a in pairs:
            e = slot_evidence(a, i)
            if e and e[0] == "sub":
                shown.setdefault(i, e[1])
    added = {}
    for a in pairs:
        for i, w in sorted(extra_words(a)):
            if w not in added.setdefault(i, []):
                added[i].append(w)
    parts, pos = [], 0
    for i, m in enumerate(re.finditer(r"[A-Za-z0-9]+", REQUIRED)):
        parts.append((REQUIRED[pos:m.start()], None))
        parts.append((m.group(), "missing" if i in missing else None))
        if i in shown:
            parts.append((shown[i], "label"))
        parts += [(w, "extra") for w in added.get(i, [])]
        pos = m.end()
    parts.append((REQUIRED[pos:], None))
    return [p for p in parts if p[0]]
