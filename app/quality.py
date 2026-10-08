"""Image quality hints (RULES.md §6): say which picture is probably why something could not be read.

These are hints, never verdicts. The pipeline shows them only when some item already says Please check, so a
clear label is never flagged for its pictures. Thresholds were set on the practice images (2026-10-08):
  - Blurry: the strongest edges are weak. Measured as the 99.5th percentile of |Laplacian| at 1000 px. Clean
    TTB label images: 2 of 189 below 15 (one faint scan); real bottle photos: 0 of 44; heavily blurred copies of
    the label images: 129 of 189.
  - Low resolution: the longest side is under 600 px (small print on the warning becomes a few pixels tall).
"""

import cv2
import numpy as np

BLUR_EDGE = 15.0
MIN_SIDE = 600


def edge_strength(rgb: np.ndarray) -> float:
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    s = 1000 / max(g.shape)
    g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA if s < 1 else cv2.INTER_LINEAR)
    return float(np.percentile(np.abs(cv2.Laplacian(g.astype(np.float64), cv2.CV_64F)), 99.5))


def picture_problems(name: str, rgb: np.ndarray) -> list[str]:
    h, w = rgb.shape[:2]
    problems = []
    if max(h, w) < MIN_SIDE:
        problems.append(f"{name} is small ({w}×{h} pixels)")
    elif edge_strength(rgb) < BLUR_EDGE:
        problems.append(f"{name} looks blurry")
    return problems


def quality_note(pictures) -> str | None:
    """One sentence naming the pictures that are likely too poor to read, or None."""
    problems = [p for pic in pictures for p in picture_problems(pic.name, pic.full)]
    if not problems:
        return None
    return ("; ".join(problems).capitalize() + ". A sharper or larger picture may clear the items marked "
            "Please check.")
