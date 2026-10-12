"""Where on the label each answer came from: a box on one picture, and a crop to show the agent.

locate() searches the main reading's words of each picture for the run of consecutive words that best matches the
text a rule reported ("found"), and returns the box around them. The warning's box is its paragraph (zoom.py).
Boxes are in the pixels of the picture as it was read (turned upright when the upload was turned).
"""

import io

import numpy as np
from PIL import Image
from rapidfuzz import fuzz

from app.ocr import zoom
from app.verify.text import normalize

MIN_SCORE = 80


def locate(text: str, frame_words: list[list]) -> tuple[int, tuple] | None:
    """-> (picture index, (x0, y0, x1, y1)) of the best match for `text`, or None."""
    want = normalize(text or "")
    if not want:
        return None
    n = len(want.split())
    best = (0.0, None)
    for k, words in enumerate(frame_words):
        toks = [normalize(w[0]) for w in words]
        for size in range(max(1, n - 1), n + 3):
            for i in range(0, max(0, len(words) - size) + 1):
                window = " ".join(t for t in toks[i:i + size] if t)
                if not window:
                    continue
                score = fuzz.ratio(want, window)
                if score > best[0]:
                    boxes = [w[2] for w in words[i:i + size]]
                    best = (score, (k, (min(b[0] for b in boxes), min(b[1] for b in boxes),
                                        max(b[2] for b in boxes), max(b[3] for b in boxes))))
    return best[1] if best[0] >= MIN_SCORE else None


def locate_warning(frame_words: list[list]) -> tuple[int, tuple] | None:
    for k, words in enumerate(frame_words):
        reg = zoom.find_region(words)
        if reg:
            return k, reg[:4]
    return None


def crop_png(frame: np.ndarray, box: tuple, pad: float = 0.15, max_w: int = 480) -> bytes:
    x0, y0, x1, y1 = box
    px, py = (x1 - x0) * pad + 4, (y1 - y0) * pad + 4
    H, W = frame.shape[:2]
    img = Image.fromarray(frame[max(0, int(y0 - py)):min(H, int(y1 + py)), max(0, int(x0 - px)):min(W, int(x1 + px))])
    if img.width > max_w:
        img = img.resize((max_w, max(1, round(img.height * max_w / img.width))))
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()
