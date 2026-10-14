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
# The same grape under two names (Pinot Gris is Pinot Grigio): never a different product, at most Please check.
_SAME_TYPE = {frozenset(p) for p in (("gris", "grigio"), ("syrah", "shiraz"), ("muscat", "moscato"))}
# Digits a reader mixes up: one read as another is never assumed to be a real difference.
_LOOKALIKE_DIGITS = {frozenset(p) for p in ("08", "17", "38", "56", "68", "14", "89", "58")}
# For printed amounts (alcohol, size): the pairs readers actually swap in numerals, so "45%" vs "46%" still fails.
_NUMERAL_LOOKALIKES = {frozenset(p) for p in ("08", "17", "14", "38")}


def could_be_misread(want: str, got: str) -> bool:
    """Digits of a number the label shows vs the application's: only the end of it was read ("50" for 750, "8" for
    4.8), or it differs only in digits readers confuse (1/4, 0/8, ...). Such a reading is never Does not match."""
    a, b = re.sub(r"\D", "", want).lstrip("0"), re.sub(r"\D", "", got).lstrip("0")
    if not a or not b or a == b:
        return False
    if len(b) < len(a) and a.endswith(b):
        return True
    return len(a) == len(b) and all(x == y or frozenset((x, y)) in _NUMERAL_LOOKALIKES for x, y in zip(a, b))


def _one_type_word_differs(want: str, got: str) -> bool:
    """Same words in the same order except one, and both of those are different type words ("rye" vs "bourbon").
    The other words must agree, so a lone "GIN" printed elsewhere never stands in for an unread "VODKA"."""
    a, b = want.split(), got.split()
    pairs = [(x, y) for x, y in zip(a, b) if x != y]
    return (len(a) == len(b) >= 2 and len(pairs) == 1 and pairs[0][0] in TYPE_WORDS and pairs[0][1] in TYPE_WORDS
            and frozenset(pairs[0]) not in _SAME_TYPE)


# Words printed around a brand that are not part of it: the company ("BULLEIT DISTILLING CO.", "THE WOODFORD RESERVE
# DISTILLERY") and amounts ("40% ALC/VOL", "750 ML"). Any other word beside it ("Iron Anchor Reserve") may make a
# different brand, so a person decides; so does a number beside a brand that has one ("10 YEAR OLD 12").
_AROUND_BRAND = set("""the distillery distilleries distillers distilling brewing brewery breweries brewers brewhouse
company co inc llc ltd corp winery wines vineyards vineyard cellars meadery cidery spirits sa sas srl spa gmbh www com
alc vol abv proof ml l oz fl""".split())


def _brand_beside(want: str, line: str) -> bool:
    """The brand's exact words in a part of the line (split at | , : ; ( ) and " - ") whose other words are all company
    words or amounts."""
    if _BOTTLER.search(line):  # the bottler line names the company, not the brand as printed
        return False
    for part in re.split(r"[|,:;()•·]|\s-\s", line):
        got = normalize(part)
        m = re.search(rf"(?<!\S){re.escape(want)}(?!\S)", got)
        if m and all(w in _AROUND_BRAND or (any(c.isdigit() for c in w) and not re.search(r"\d", want))
                     for w in (got[:m.start()] + " " + got[m.end():]).split()):
            return True
    return False


def other_version(expected: str, lines: list[str], skip: str = "") -> str | None:
    """A line showing a version of the brand that is close but not the same ("WOODFORD RESERVA" printed on the back
    while the front reads "WOODFORD RESERVE"): then the brand is never Matches. Lines that are part of `skip`, the
    reading being confirmed, are left out."""
    want = normalize(expected)
    n = len(want.split())
    for ln in lines:
        if not ln.strip() or ln.strip() in skip:
            continue
        words = normalize(ln).split()
        for i in range(len(words) - n + 1):
            got = " ".join(words[i:i + n])
            if got.replace(" ", "") != want.replace(" ", "") and fuzz.ratio(want, got) >= CHECK_SCORE:
                return ln
    return None


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
    beside = field == "brand_name" and next((ln for ln in lines if _brand_beside(want, ln)), None)
    if beside and not other_version(expected, lines):
        return FieldResult(field, Verdict.PASS, f'Label shows "{beside}", which has "{expected}" in it.', found=beside)
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
    # The words may be there across a line break ("KENTUCKY STRAIGHT BOURBON" / "WHISKEY" for "Bourbon Whiskey").
    across = min((w for w in _windows(lines) if not _BOTTLER.search(w)
                  and re.search(rf"(?<!\S){re.escape(want)}(?!\S)", norm(w))), key=len, default=None)
    if across:
        return FieldResult(field, Verdict.CHECK, f'Label shows "{across}", which adds words to "{expected}".',
                           code=f"{field.upper()}_EXTRA_WORDS", found=across)
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


def _in_order(want: list[str], label: list[str], gap: int = 3) -> bool:
    """The expected words appear in order, each within `gap` label words of the previous one (stray reader tokens,
    a "|" or "®", line wraps); a word split in two ("DIST ILLERY") or two glued ("OLDTOM") still count."""
    def at(k, j):  # -> (label words used, expected words used) when want[k] is at label[j]
        if label[j] == want[k]:
            return 1, 1
        if j + 1 < len(label) and label[j] + label[j + 1] == want[k]:
            return 2, 1
        if k + 1 < len(want) and label[j] == want[k] + want[k + 1]:
            return 1, 2
        return 0, 0

    for start in range(len(label)):
        j, k = start, 0
        while k < len(want):
            hit = next(((jj, *at(k, jj)) for jj in range(j, min(len(label), j + (1 if k == 0 else gap + 1)))
                        if at(k, jj)[0]), None)
            if hit is None:
                break
            j, k = hit[0] + hit[1], k + hit[2]
        if k >= len(want):
            return True
    return False


def words_present(field: str, expected: str, lines: list[str]) -> FieldResult:
    """Multi-part statements (name and address): every expected word must be on the label to match, each part of the
    statement (between commas, bars, sentence ends and "by"/"for") together and in order, a few stray reader tokens
    allowed; the parts may come in any order. Every word merely "somewhere" let a changed bottler name pass when the
    word was also in the logo (measured: 4 in 10 planted name changes came back Matches; now about 1 in 10). A missing word may be a different street or city, or text the reader missed, so it is "Please check", never
    "Does not match".
    A ZIP code is not required on the label (27 CFR 5.66: city and state), so a typed one is not looked for."""
    want = [w for w in _address_words(expected) if not re.fullmatch(r"\d{5}(\d{4})?", w)]
    label = _address_words(" ".join(lines))
    have = set(label) | {a + b for a, b in zip(label, label[1:])}  # a reader may split one word in two
    read = set(label)
    missing = [w for k, w in enumerate(want) if w not in have
               and not (k + 1 < len(want) and w + want[k + 1] in read)       # "OLDTOM": space dropped by the reader
               and not (k > 0 and want[k - 1] + w in read)]
    parts = [[w for w in _address_words(part) if not re.fullmatch(r"\d{5}(\d{4})?", w)]
             for part in re.split(r"[,|;\n]|\.\s|\b(?:by|for)\b:?", expected, flags=re.I)]  # parts in any order
    if not missing and all(_in_order(part, label) for part in parts if part):
        return FieldResult(field, Verdict.PASS, "Name and address found on the label.")
    if not missing:  # every word is somewhere, but not together: "HOME" in the logo doesn't fix "SUTTER HILL"
        return FieldResult(field, Verdict.CHECK, "Each word was found on the label, but not together as one statement. "
                           "Please look at the name and address.", code=f"{field.upper()}_SCATTERED")
    if len(missing) < len(want):
        return FieldResult(field, Verdict.CHECK, f"Some words were not found: {', '.join(missing)}.",
                           code=f"{field.upper()}_PARTIAL")
    return FieldResult(field, Verdict.CHECK, f'"{expected}" was not found on the label. Please look.',
                       code=f"{field.upper()}_MISMATCH")
