"""Judge the Government Warning across several independent readings of the same label (RULES.md §5).

Each reading is (engine family, text), e.g. ("onnx", ...) or ("tess", ...). The judge is tolerant of reader
slips but never of a changed wording:
  - Words are compared after case folding with an edit distance in which look-alike characters (o/c/e, l/i/t,
    rn/m, ...) cost 0.3, so "fo" for "to" is a reader slip; "may" vs "can" stays a different word.
    Allowed distance: 0.35 for words of 3 letters or fewer, 1 for 4-7, 2 for 8+.
  - Junk tokens between required words are skipped; two words glued ("MACHINERYAND") or one word split
    ("bev erages") are recognised, a glued token only if each piece passes its own word's check.
  - A required word counts as present if ANY reading has it in its place.
  - A real word (3+ letters) between two required words is an added word: "beverages does not impair" must never
    pass. It is "check", never "nomatch": text printed beside the warning ("ALC/VOL") gets mixed into every reading.
    One seen by a single reading while two other readings show that spot clean is reader noise, and is dismissed.
Verdicts:
  "match"   every required word present and the heading read in capitals;
  "nomatch" two different engine families show the SAME different word (or the same missing word) with the
            required words on both sides intact, or two families read a title-case heading and none capitals;
  "check"   anything else not matching (a person should look);
  "none"    no reading contains the heading.
Measured on dev (READER-OPTIONS.md): 36 of 39 approved warnings match, 0 false "nomatch", every planted
alteration caught. A dropped required word shorter than 3 letters never counts toward "nomatch": readers glue
short words to a neighbour ("DRIVEA CAR"), which once made two engines "agree" on a drop that was not there.
"""

import re
from functools import lru_cache

from .warning import REQUIRED

NUM = "<n>"
CONFUSABLE = str.maketrans({"0": "o", "1": "l", "5": "s", "8": "b", "|": "l", "!": "l", "$": "s"})
SIM = {frozenset(p) for p in ["oc", "ce", "oe", "oa", "ea", "ao", "li", "lt", "it", "lf", "tf", "ij", "lj", "hb", "hn",
                              "uv", "un", "nr", "mn", "vy", "gq", "gy", "sz", "co", "ec", "rt", "ft", "ir", "jl",
                              "bd", "pb", "ue", "ae", "ua", "kx", "wv", "dc", "uo", "go", "gc"]}
MULTI = [("rn", "m"), ("m", "rn"), ("cl", "d"), ("vv", "w"), ("ii", "u"), ("li", "h"), ("ln", "h")]


def tokenize(text):
    text = re.sub(r"(\w)-\s*\n\s*(\w)", r"\1\2", text)
    text = re.sub(r"(?<=[A-Za-z])-(?=[A-Za-z])", "", text)
    return re.findall(r"[A-Za-z0-9$|!]+|[\(\[\{]\s*[\)\]\}]", text)


def norm(w):
    if re.fullmatch(r"[\(\[\{]\s*[\)\]\}]", w):
        return NUM
    return w.casefold().translate(CONFUSABLE)


REQ_RAW = re.findall(r"[A-Za-z0-9]+", REQUIRED)
REQ = [norm(w) for w in REQ_RAW]
NUM_OK = {"l": {"l", "i", "t", "j", "f", "li", "il", "ll", "lj", NUM}, "2": {"2", "z", "?", NUM}}


@lru_cache(maxsize=None)
def wdist(a, b):
    """Edit distance; look-alike substitutions cost 0.3, two-for-one look-alikes ("rn"/"m") 0.5."""
    n, m = len(a), len(b)
    d = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(n + 1):
        d[i][0] = float(i)
    for j in range(m + 1):
        d[0][j] = float(j)
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            ca, cb = a[i - 1], b[j - 1]
            sub = 0.0 if ca == cb else (0.3 if frozenset((ca, cb)) in SIM else 1.0)
            v = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + sub)
            for x, y in MULTI:
                if i >= len(x) and j >= len(y) and a[i - len(x):i] == x and b[j - len(y):j] == y:
                    v = min(v, d[i - len(x)][j - len(y)] + 0.5)
            d[i][j] = v
    return d[n][m]


def limit(w):
    return 0.35 if len(w) <= 3 else 1.0 if len(w) <= 7 else 2.0


def close(want, tok):
    if want in NUM_OK:
        return tok in NUM_OK[want]
    if tok == NUM:
        return False
    return want == tok or (abs(len(want) - len(tok)) <= 2 and wdist(want, tok) <= limit(want) + 1e-9)


def find_heading(toks):
    for i in range(len(toks)):
        if close("government", toks[i]) and i + 1 < len(toks) and close("warning", toks[i + 1]):
            return i, 2
        if len(toks[i]) >= 14 and close("governmentwarning", toks[i]):
            return i, 1
    return None


def merged_ok(words, tok):
    """A glued token matches several required words only if it can be cut so that EACH piece passes its own
    word's check ("maycause" vs "cancause" must fail on "may" vs "can")."""
    if len(words) == 2:
        return any(close(words[0], tok[:c]) and close(words[1], tok[c:]) for c in range(1, len(tok)))
    return any(close(words[0], tok[:a]) and close(words[1], tok[a:b]) and close(words[2], tok[b:])
               for a in range(1, len(tok) - 1) for b in range(a + 1, len(tok)))


def align(reading):
    """Per required word: index of the token that holds it, or None. -> (slots, toks), or None without a heading."""
    toks = [norm(w) for w in tokenize(reading)]
    h = find_heading(toks)
    if h is None:
        return None
    s, n = h
    slots = [s, s + 1] if n == 2 else [s, s]
    ends = list(slots)  # last token used by each required word (a split word uses two)
    j, i = s + n, 2
    while i < len(REQ):
        hit = None
        for k in range(j, min(j + 6, len(toks))):
            t = toks[k]
            if close(REQ[i], t):
                hit = (k, 1, 1)
                break
            for m in (2, 3):
                if i + m <= len(REQ) and not any(w in NUM_OK for w in REQ[i:i + m]) and merged_ok(REQ[i:i + m], t):
                    hit = (k, m, 1)
                    break
            if hit:
                break
            if k + 1 < len(toks) and len(REQ[i]) >= 5 and REQ[i] not in NUM_OK:
                cat = t + toks[k + 1]
                if abs(len(cat) - len(REQ[i])) <= 2 and wdist(REQ[i], cat) <= limit(REQ[i]):
                    hit = (k, 1, 2)
                    break
        if hit is None:
            slots.append(None)
            ends.append(None)
            i += 1
        else:
            k, m, used = hit
            slots.extend([k] * m)
            ends.extend([k + used - 1] * m)
            i += m
            j = k + used
    return slots, toks, ends


def extra_words(al):
    """Words a reading shows between two consecutive required words: {(position, word)}. Only real words count
    (3+ letters, letters only); stray marks and 1-2 letter fragments are reader noise."""
    slots, toks, ends = al
    out = set()
    for i in range(2, len(slots) - 1):
        a, b = ends[i], slots[i + 1]
        if a is None or b is None or b <= a + 1:
            continue
        out |= {(i, t) for t in toks[a + 1:b] if t.isalpha() and len(t) >= 3}
    return out


def clean_gaps(al):
    """Positions where a reading shows two consecutive required words side by side, with nothing between them."""
    slots, ends = al[0], al[2]
    return {i for i in range(2, len(slots) - 1)
            if ends[i] is not None and slots[i + 1] is not None and slots[i + 1] == ends[i] + 1}


def heading_caps(reading):
    """True / False whether the heading is read in capitals; None without a heading."""
    raw = tokenize(reading)
    h = find_heading([norm(w) for w in raw])
    if h is None:
        return None
    s, n = h
    letters = [c for c in "".join(raw[s:s + n]) if c.isalpha()]
    return sum(c.isupper() for c in letters) / max(1, len(letters)) >= 0.9


def slot_evidence(al, i):
    """What a reading shows where required word i should be: ("sub", token) | ("drop",) | None. Only when the two
    required words on each side are matched, in order, with nothing between them."""
    slots, toks = al[0], al[1]
    ctx_l = [slots[p] for p in range(i - 2, i)]
    ctx_r = [slots[p] for p in range(i + 1, min(i + 3, len(slots)))]
    if i < 2 or len(ctx_r) < 2 or None in ctx_l or None in ctx_r:
        return None
    if ctx_l[1] - ctx_l[0] > 1 or ctx_r[1] - ctx_r[0] > 1:
        return None
    prev, nxt = ctx_l[1], ctx_r[0]
    gap = nxt - prev - 1
    if gap == 0:
        return None if len(REQ[i]) < 3 else ("drop",)  # short words get glued to a neighbour by readers
    if gap == 1:
        t = toks[prev + 1]
        if len(t) >= 2 and t.isalpha():
            return ("sub", t)
    return None


def judge_detail(readings):
    """readings: list of (family, text). -> dict with the evidence behind the verdict:
    found (heading in any reading), missing (required words no reading has), words_strong (two families show the
    same different / missing word), caps (per-reading heading-in-capitals flags), caps_strong."""
    readings = [(f, t) for f, t in readings if t]
    pairs = [(f, align(t)) for f, t in readings]
    pairs = [(f, a) for f, a in pairs if a is not None]
    if not pairs:
        return {"found": False, "missing": [], "words_strong": False, "caps": [], "caps_strong": False}
    missing = [i for i in range(len(REQ)) if all(a[0][i] is None for _, a in pairs)]
    words_strong = False
    for i in missing:
        ev = [(f, slot_evidence(a, i)) for f, a in pairs]
        ev = [(f, e) for f, e in ev if e and (e[0] == "drop" or len(e[1]) >= 3)]
        for e in {e for _, e in ev}:
            if len({f for f, x in ev if x == e}) >= 2:
                words_strong = True
    # An added word seen by only one reading, where two other readings show that very spot clean, is reader noise
    # ("thf", "kof"). A really inserted word is in most readings, so it is never dismissed this way.
    seen = [extra_words(a) for _, a in pairs]
    clean = [clean_gaps(a) for _, a in pairs]
    extra = {x for x in set().union(*seen)
             if sum(x in e for e in seen) > 1 or sum(x[0] in c for c in clean) < 2}
    capf = [(f, heading_caps(t)) for f, t in readings]
    caps = [c for _, c in capf if c is not None]
    caps_strong = bool(caps) and not any(caps) and len({f for f, c in capf if c is False}) >= 2
    return {"found": True, "missing": [REQ_RAW[i] for i in missing], "words_strong": words_strong,
            "extra": sorted({w for _, w in extra}),
            "caps": caps, "caps_strong": caps_strong}


def judge(readings):
    """readings: list of (family, text). -> (verdict, reasons)."""
    d = judge_detail(readings)
    if not d["found"]:
        return "none", []
    caps_bad = bool(d["caps"]) and not any(d["caps"])
    if not d["missing"] and not d["extra"] and not caps_bad:
        return "match", []
    why = list(d["missing"]) + [f"+{w}" for w in d["extra"]] + (["<heading not in capitals>"] if caps_bad else [])
    return ("nomatch" if d["words_strong"] or d["caps_strong"] else "check"), why
