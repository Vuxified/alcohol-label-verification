"""Is the health warning printed large enough (27 CFR 16.22(b))? Measured from the picture (RULES.md §5.3).

A picture has no size of its own, so this needs the label's real height from the agent (the COLA application lists
"Actual Dimensions" for every label). Then pixels per inch = picture height / label height, and the capital letters of
"GOVERNMENT WARNING" are measured by their ink (from the top of the letters to the bottom). The minimum depends on the
container: 1 mm up to 237 mL, 2 mm up to 3 L, 3 mm above.
Advisory only, like TTB itself (it does not review type size on a COLA): never Does not match.
The rule sets a minimum TYPE size; what a picture shows is the height of the capital letters, which in most fonts is
about 70% of the type size. So the check only answers when both readings of the rule agree:
  Matches       the capitals alone reach the minimum (with 5% for measuring error);
  Please check  the capitals are under 65% of the minimum: too small even as type size;
  Not checked   in between, with the measured size shown (on approved labels most are printed right at the minimum).
"""

import re

import cv2
import numpy as np
from rapidfuzz import fuzz

from app.verify.model import Application, FieldResult, Verdict
from app.verify.net_contents import parse_typed_net

HEADING = ("GOVERNMENT", "WARNING")
PASS_AT = 1.05         # capitals at least this share of the minimum: large enough under either reading of the rule
FLAG_BELOW = 0.65      # capitals under this share: too small even if the minimum is the type size (capitals ~70%)
MIN_INK_PX = 6         # smaller letters are too coarse to measure


def min_height_mm(ml: float) -> int:
    return 1 if ml <= 237 else 2 if ml <= 3000 else 3


def parse_label_height(text: str | None) -> float | None:
    """What the agent typed as the label's height -> inches, or None ("4", "4.5 in", '5"', "4,5")."""
    m = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:in|inch|inches|\"|”)?\.?", (text or "").strip().lower())
    if not m:
        return None
    v = float(m.group(1).replace(",", "."))
    return v if v > 0 else None


def _upper(t: str) -> str:
    return "".join(c for c in t.upper() if c.isalpha())


def ink_height(gray: np.ndarray) -> int | None:
    """Height in pixels of the line of capitals in a word box: the run of inked rows through the box's middle (so a
    neighbouring line caught by a loose box does not count)."""
    if min(gray.shape) < MIN_INK_PX:
        return None
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw > 0).mean() > 0.5:  # ink is the minority
        bw = 255 - bw
    rows = (bw > 0).sum(axis=1) > 0.02 * bw.shape[1]
    mid = len(rows) // 2
    if not rows[mid]:
        return None
    top, bottom = mid, mid
    while top > 0 and rows[top - 1]:
        top -= 1
    while bottom < len(rows) - 1 and rows[bottom + 1]:
        bottom += 1
    h = bottom - top + 1
    return h if h >= MIN_INK_PX else None


def heading_height(frames, frame_words):
    """-> (letter height in px, frame height in px) for the first picture where the heading can be measured."""
    for frame, words in zip(frames, frame_words):
        toks = [_upper(w[0]) for w in words]
        for i in range(len(toks) - 1):
            if fuzz.ratio(toks[i], HEADING[0]) >= 85 and fuzz.ratio(toks[i + 1], HEADING[1]) >= 85:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
                hs = []
                for w in words[i:i + 2]:
                    x0, y0, x1, y1 = (int(round(v)) for v in w[2])
                    h = ink_height(gray[max(0, y0):y1, max(0, x0):x1])
                    if h:
                        hs.append(h)
                if len(hs) == 2:
                    return float(np.mean(hs)), frame.shape[0]
    return None


def size_field(frames, frame_words, app: Application) -> FieldResult:
    if not app.label_height_in:
        return FieldResult("warning_size", Verdict.NOT_APPLICABLE,
                           "Type size not checked: give the label's height to check it.")
    ml = parse_typed_net(app.net_contents, app.beverage_type) if app.net_contents else None
    if not ml:
        return FieldResult("warning_size", Verdict.NOT_APPLICABLE,
                           "Type size not checked: the minimum depends on the net contents, which were not given.")
    m = heading_height(frames, frame_words)
    if m is None:
        return FieldResult("warning_size", Verdict.NOT_APPLICABLE,
                           "Type size not checked: the warning heading is too small, sideways or curved to measure.")
    mm = m[0] / (m[1] / app.label_height_in) * 25.4
    need = min_height_mm(ml)
    if mm >= need * PASS_AT:
        return FieldResult("warning_size", Verdict.PASS,
                           f"Warning capitals are about {mm:.1f} mm tall (at least {need} mm needed for this container).")
    if mm >= need * FLAG_BELOW:
        return FieldResult("warning_size", Verdict.NOT_APPLICABLE,
                           f"Type size not confirmed: the warning's capitals measure about {mm:.1f} mm, close to the "
                           f"{need} mm minimum type size for this container (27 CFR 16.22), which a picture cannot settle.")
    return FieldResult("warning_size", Verdict.CHECK,
                       f'"GOVERNMENT WARNING" capitals measure about {mm:.1f} mm tall on a {app.label_height_in:g}-inch '
                       f"label, smaller than the {need} mm minimum type size for this container allows (27 CFR 16.22). "
                       "Please check the printed size.", code="WARNING_TYPE_SIZE")
