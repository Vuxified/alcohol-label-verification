"""Is "GOVERNMENT WARNING" in bold (27 CFR 16.22(a)(2))? Measured from the picture, not guessed (RULES.md §5.3).

For each word, the ink is separated from the background (Otsu threshold, ink = the smaller class), and the stroke
thickness is estimated as ink area / skeleton length, in pixels. The heading and the text after it are in the same
paragraph at the same type size, so their stroke thickness compares directly. Bold heading = the heading's strokes are clearly thicker than the warning text right after it.
Advisory only: the result is Matches or Please check, never Does not match.
"""

import cv2
import numpy as np
from rapidfuzz import fuzz

HEADING = ("GOVERNMENT", "WARNING")
BODY_WORDS = 8          # how many words after the heading to compare against
MIN_HEIGHT = 10         # px; smaller words are too coarse to measure
# Heading strokes at least this much thicker than the text after it = bold confirmed. Set on the practice labels
# (2026-10-08): generated labels with a regular heading measure 0.98-1.18, with a bold heading 1.46-2.31, so all 8
# regular headings are caught and all 31 bold ones confirmed; real approved labels: 34 of 48 measurable confirmed
# (the rest include labels set entirely in heavy type, which TTB accepts, hence advisory).
BOLD_RATIO = 1.20


def _upper(t: str) -> str:
    return "".join(c for c in t.upper() if c.isalpha())


def stroke_width(gray: np.ndarray) -> float | None:
    """Average stroke thickness in pixels for one word crop, or None if it can't be measured."""
    h = gray.shape[0]
    if h < MIN_HEIGHT or gray.shape[1] < MIN_HEIGHT:
        return None
    _, bw = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if (bw > 0).mean() > 0.5:          # ink is the minority: dark text on light, or light text on dark
        bw = 255 - bw
    ink = int((bw > 0).sum())
    if ink < 20:
        return None
    skel = cv2.ximgproc.thinning(bw) if hasattr(cv2, "ximgproc") else _thin(bw)
    length = int((skel > 0).sum())
    return ink / length if length else None


def _thin(bw: np.ndarray) -> np.ndarray:
    """Morphological skeleton (used when opencv-contrib's thinning is not installed)."""
    skel = np.zeros_like(bw)
    img = bw.copy()
    kernel = cv2.getStructuringElement(cv2.MORPH_CROSS, (3, 3))
    while cv2.countNonZero(img):
        eroded = cv2.erode(img, kernel)
        skel |= cv2.subtract(img, cv2.dilate(eroded, kernel))
        img = eroded
    return skel


def measure(frames: list[np.ndarray], frame_words: list[list]) -> tuple[float, float] | None:
    """-> (heading stroke, body stroke) in pixels from the first picture where both can be measured, or None."""
    for frame, words in zip(frames, frame_words):
        toks = [_upper(w[0]) for w in words]
        for i in range(len(toks) - 1):
            if fuzz.ratio(toks[i], HEADING[0]) >= 85 and fuzz.ratio(toks[i + 1], HEADING[1]) >= 85:
                gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)

                def ratios(ws):
                    out = []
                    for w in ws:
                        x0, y0, x1, y1 = (int(round(v)) for v in w[2])
                        r = stroke_width(gray[max(0, y0):y1, max(0, x0):x1])
                        if r is not None:
                            out.append(r)
                    return out

                head = ratios(words[i:i + 2])
                body = ratios([w for w in words[i + 2:i + 2 + BODY_WORDS] if len(_upper(w[0])) >= 3])
                if len(head) == 2 and len(body) >= 3:
                    return float(np.mean(head)), float(np.median(body))
    return None


def bold_field(frames, frame_words):
    from app.verify.model import FieldResult, Verdict
    m = measure(frames, frame_words)
    if m is None:
        return FieldResult("warning_bold", Verdict.NOT_APPLICABLE,
                           "Bold heading not checked: the warning is too small, sideways or curved to measure.")
    ratio = m[0] / m[1]
    if ratio >= BOLD_RATIO:
        return FieldResult("warning_bold", Verdict.PASS,
                           f'"GOVERNMENT WARNING" is in bold (its strokes are {ratio:.1f}× as thick as the text after it).')
    return FieldResult("warning_bold", Verdict.CHECK,
                       f'"GOVERNMENT WARNING" must be in bold (27 CFR 16.22). Its strokes are {ratio:.1f}× as thick as the '
                       "text after it, which does not clearly show bold. Please look.", code="WARNING_BOLD_UNCONFIRMED")
