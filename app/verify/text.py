"""Text normalization and finding expected values in label text (RULES.md §2)."""

import re
import unicodedata

from rapidfuzz import fuzz

from .model import FieldResult, Verdict

CHECK_SCORE = 85  # close enough to show as "Please check"; a match needs the same text (case, punctuation, spacing aside)
MAX_LINES_JOINED = 4  # a value may wrap across up to 4 label lines
# "Bottled by …", "Produced & bottled by …", "Imported by …": the name in this line is the bottler, not proof of the brand.
_BOTTLER = re.compile(r"\b(bottled|produced|brewed|vinted|distilled|imported|blended|cellared|made|canned)\b[^.]{0,40}?\bby\b", re.I)

_PUNCT_MAP = str.maketrans({"’": "'", "‘": "'", "`": "'", "´": "'", "′": "'", "“": '"', "”": '"',
                            "–": "-", "—": "-", "\u00a0": " ", "™": None, "℠": None, "®": None, "&": " and "})
# Words written two ways that mean the same thing in a name.
_SAME_WORD = {"saint": "st", "sainte": "ste"}


def normalize(text: str) -> str:
    """Case, accents, punctuation and spacing ignored; apostrophes inside words kept."""
    text = unicodedata.normalize("NFKC", text.translate(_PUNCT_MAP))  # before NFKC turns ™ into "TM"
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    text = text.casefold()
    text = re.sub(r"(?<=\w) ?' ?(?=s\b)", "'", text)   # a reader's stray space at an apostrophe: "STONE' S"
    text = re.sub(r"(?<=\w)'(?=\w)", "\x00", text)    # protect in-word apostrophes
    text = re.sub(r"[^\w\s\x00]", " ", text).replace("\x00", "'")
    return " ".join(_SAME_WORD.get(w, w) for w in text.split())


def _class_spelling(text: str) -> str:
    """§ 5.143: "The word whisky may be spelled as either 'whisky' or 'whiskey'." Class/type only."""
    return re.sub(r"\bwhiskey\b", "whisky", text)


def _windows(lines: list[str]):
    """Each line, and each run of up to MAX_LINES_JOINED consecutive lines joined."""
    for i in range(len(lines)):
        for n in range(1, MAX_LINES_JOINED + 1):
            if i + n <= len(lines):
                yield " ".join(lines[i:i + n])


def _only_numbers_differ(want: str, got: str) -> bool:
    """Same words in the same order, and every difference is one whole number read as another ("10" vs "12").
    A clearly read different number is Does not match (owner decision 2026-10-09; age statements, 27 CFR 5.74);
    anything less clear ("1O", a different word as well) stays Please check."""
    a, b = want.split(), got.split()
    pairs = [(x, y) for x, y in zip(a, b) if x != y]
    return (len(a) == len(b) and bool(pairs) and all(x.isdigit() and y.isdigit() and len(x) == len(y) for x, y in pairs)
            and not any(frozenset((c, d)) in _LOOKALIKE_DIGITS for x, y in pairs for c, d in zip(x, y) if c != d))


# Words that name what a product is (the class/type designations of 27 CFR parts 4, 5 and 7, and common wine grapes).
# One of these read in place of another ("RYE" for "BOURBON") is a different product, not a reading slip.
# Only products that can't be one another: a style or a broader word ("IPA" is an ale, "pilsner" a lager, "red" a wine)
# is left out, because a label may print the style large and the class small.
TYPE_WORDS = set("""bourbon rye wheat malt corn scotch vodka gin rum tequila mezcal brandy cognac armagnac pisco grappa
liqueur cordial schnapps absinthe aquavit sake shochu soju baijiu cachaca seltzer cider perry mead champagne port sherry
madeira vermouth cabernet merlot chardonnay pinot noir grigio gris sauvignon blanc riesling zinfandel syrah shiraz malbec
moscato muscat tempranillo sangiovese chianti prosecco cava""".split())
# Digits a reader mixes up: one read as another is never assumed to be a real difference.
_LOOKALIKE_DIGITS = {frozenset(p) for p in ("08", "17", "38", "56", "68", "14", "89", "58")}


def _one_type_word_differs(want: str, got: str) -> bool:
    """Same words in the same order except one, and both of those are different type words ("rye" vs "bourbon").
    The other words must agree, so a lone "GIN" printed elsewhere never stands in for an unread "VODKA"."""
    a, b = want.split(), got.split()
    pairs = [(x, y) for x, y in zip(a, b) if x != y]
    return len(a) == len(b) >= 2 and len(pairs) == 1 and pairs[0][0] in TYPE_WORDS and pairs[0][1] in TYPE_WORDS


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
    if best_text and _only_numbers_differ(want, norm(best_text)):
        return FieldResult(field, Verdict.FAIL,
                           f'Label shows "{best_text}". The number differs from "{expected}".',
                           code=f"{field.upper()}_NUMBER_DIFFERS", found=best_text)
    if field == "class_type" and best_text and _one_type_word_differs(want, norm(best_text)):
        return FieldResult(field, Verdict.FAIL,
                           f'Label shows "{best_text}", a different product type from "{expected}".',
                           code=f"{field.upper()}_WORD_DIFFERS", found=best_text)
    if best_score >= CHECK_SCORE:
        return FieldResult(field, Verdict.CHECK,
                           f'Label shows "{best_text}", which is close to "{expected}" but not the same.',
                           code=f"{field.upper()}_NEAR_MATCH", found=best_text)
    return FieldResult(field, Verdict.CHECK,
                       f'"{expected}" was not found on the label. It may be in decorative type the reader could not read.',
                       code=f"{field.upper()}_MISMATCH")


_STATES = dict(zip("""alabama alaska arizona arkansas california colorado connecticut delaware florida georgia hawaii idaho
illinois indiana iowa kansas kentucky louisiana maine maryland massachusetts michigan minnesota mississippi missouri
montana nebraska nevada newhampshire newjersey newmexico newyork northcarolina northdakota ohio oklahoma oregon
pennsylvania rhodeisland southcarolina southdakota tennessee texas utah vermont virginia washington westvirginia
wisconsin wyoming districtofcolumbia""".split(), """al ak az ar ca co ct de fl ga hi id il in ia ks ky la me md ma mi mn
ms mo mt ne nv nh nj nm ny nc nd oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy dc""".split()))
_ADDRESS_WORD = {"company": "co", "street": "st", "incorporated": "inc", "corporation": "corp"}


def _address_words(text: str) -> list[str]:
    """Normalized words, with two-word state names joined ("new york") so states compare by abbreviation."""
    words = normalize(text).split()
    out, i = [], 0
    while i < len(words):
        two = "".join(words[i:i + 2])
        if two in _STATES and i + 1 < len(words):
            out.append(_STATES[two]); i += 2
            continue
        w = words[i]
        out.append(_STATES.get(w) or _ADDRESS_WORD.get(w, w)); i += 1
    return out


def words_present(field: str, expected: str, lines: list[str]) -> FieldResult:
    """Multi-part statements (name and address): every expected word must be on the label to match. A missing word
    may be a different street or city, or text the reader missed, so it is "Please check", never "Does not match".
    A ZIP code is not required on the label (27 CFR 5.66: city and state), so a typed one is not looked for."""
    want = [w for w in _address_words(expected) if not re.fullmatch(r"\d{5}(\d{4})?", w)]
    label = _address_words(" ".join(lines))
    have = set(label) | {a + b for a, b in zip(label, label[1:])}  # a reader may split one word in two
    read = set(label)
    missing = [w for k, w in enumerate(want) if w not in have
               and not (k + 1 < len(want) and w + want[k + 1] in read)       # "OLDTOM": space dropped by the reader
               and not (k > 0 and want[k - 1] + w in read)]
    if not missing:
        return FieldResult(field, Verdict.PASS, "Name and address found on the label.")
    if len(missing) < len(want):
        return FieldResult(field, Verdict.CHECK, f"Some words were not found: {', '.join(missing)}.",
                           code=f"{field.upper()}_PARTIAL")
    return FieldResult(field, Verdict.CHECK, f'"{expected}" was not found on the label. Please look.',
                       code=f"{field.upper()}_MISMATCH")
