"""Turned pictures and sideways text (READER-OPTIONS.md, "Sideways and hard warnings" and "Turn-first").

All decisions use the word boxes of the first read plus the crop-orientation classifier (about 0.1 s):
  - turn_of: is the whole picture turned? Tall boxes (height >= 2.5 x width) as the majority -> sideways, the
    classifier picks 90 vs 270; otherwise the classifier over the widest boxes says upright or upside down.
    Correct on about 90% of 820 turned dev pictures.
  - strip_vote: which way to turn a strip of sideways text on an otherwise upright label.
  - upside_down: whether most wide boxes are upside down.
  - side_read: one detector pass at 1280 px on the picture turned 90 degrees, a 0/180 vote over its longest
    boxes, recognition of those boxes only. Fixed Blue Moon and Stella.
Turns are np.rot90 k values (k=1: 90 degrees counter-clockwise).
"""

import numpy as np

from .engine import OnnxEngine, Text

TALL, WIDE = 2.5, 2.0


def _tall(words, min_side=0):
    return [w[2] for w in words if min(w[2][2] - w[2][0], w[2][3] - w[2][1]) >= min_side
            and (w[2][3] - w[2][1]) >= TALL * max(1e-6, w[2][2] - w[2][0])]


def _wide(words, min_chars=0):
    return [w[2] for w in words if len(w[0]) >= min_chars and (w[2][2] - w[2][0]) >= WIDE * max(1e-6, w[2][3] - w[2][1])]


def _crops(img, boxes, k):
    return [np.ascontiguousarray(np.rot90(img[int(b[1]):int(b[3]) + 1, int(b[0]):int(b[2]) + 1], k)) for b in boxes]


def turn_of(eng: OnnxEngine, img, words, share=0.5, maxn=16) -> int:
    """np.rot90 k that makes the whole picture upright (0 = leave it)."""
    tall = _tall(words, min_side=6)  # sideways words come out as junk like "-", so no character filter
    wide = _wide(words, min_chars=2)
    if not tall and not wide:
        return 0
    if len(tall) / (len(tall) + len(wide)) >= share and len(tall) >= 3:
        boxes = sorted(tall, key=lambda b: -(b[3] - b[1]))[:maxn]
        return 1 if eng.orientation_vote(_crops(img, boxes, 1)) > 0 else 3
    boxes = sorted(wide, key=lambda b: -(b[2] - b[0]))[:maxn]
    return 2 if eng.orientation_vote(_crops(img, boxes, 0)) < 0 else 0


def tall_strip(img, words, margin=0.15):
    """Bounding strip of the tall boxes (5 or more), with a margin. -> (strip, (x0, y0)) or None."""
    tall = _tall(words)
    if len(tall) < 5:
        return None
    H, W = img.shape[:2]
    x0, y0 = min(b[0] for b in tall), min(b[1] for b in tall)
    x1, y1 = max(b[2] for b in tall), max(b[3] for b in tall)
    X0, Y0 = int(max(0, x0 - margin * W)), int(max(0, y0 - margin * H))
    return img[Y0:int(min(H, y1 + margin * H)), X0:int(min(W, x1 + margin * W))], (X0, Y0)


def edge_strips(img, share=0.18):
    """The right and left edges of a wide label, where cans and wraps often print the warning sideways in letters too
    small to find in the whole picture. -> [(strip, (x0, y0))]; none for a tall picture."""
    H, W = img.shape[:2]
    if W <= H:
        return []
    s = max(1, int(W * share))
    return [(img[:, W - s:], (W - s, 0)), (img[:, :s], (0, 0))]


def strip_vote(eng: OnnxEngine, img, words, maxn=16):
    """k (1 or 3) that turns the sideways strip upright, or None with fewer than 5 usable tall boxes."""
    tall = sorted(_tall(words), key=lambda b: -(b[3] - b[1]))[:maxn]
    crops = [c for c in _crops(img, tall, 1) if c.size and min(c.shape[:2]) >= 4]
    if len(crops) < 5:
        return None
    return 1 if eng.orientation_vote(crops) > 0 else 3


def upside_down(eng: OnnxEngine, img, words, maxn=16) -> bool:
    wide = sorted(_wide(words), key=lambda b: -(b[2] - b[0]))[:maxn]
    crops = [c for c in _crops(img, wide, 0) if c.size and min(c.shape[:2]) >= 4]
    return len(crops) >= 3 and eng.orientation_vote(crops) < 0


def _assemble(words):
    """Words -> reading-order lines (group by vertical overlap, sort by x)."""
    lines = []
    for w in sorted(words, key=lambda w: (w[2][1] + w[2][3]) / 2):
        cy, h = (w[2][1] + w[2][3]) / 2, w[2][3] - w[2][1]
        for ln in lines:
            if abs(ln["cy"] - cy) <= 0.5 * max(h, ln["h"]):
                ln["w"].append(w)
                ln["cy"] = float(np.mean([(v[2][1] + v[2][3]) / 2 for v in ln["w"]]))
                break
        else:
            lines.append({"cy": cy, "h": h, "w": [w]})
    lines.sort(key=lambda ln: ln["cy"])
    return [" ".join(v[0] for v in sorted(ln["w"], key=lambda v: v[2][0])) for ln in lines]


def side_read(eng: OnnxEngine, img, det_size=1280, maxn=16):
    """Read a picture whose text runs sideways. -> (Text in the frame of np.rot90(img, k), k)."""
    rot = np.ascontiguousarray(np.rot90(img, 1))
    H, W = rot.shape[:2]
    boxes = [b for b in eng.detect(rot, det_size) if b[2] - b[0] >= 2 and b[3] - b[1] >= 2]
    crops = [rot[int(b[1]):int(np.ceil(b[3])), int(b[0]):int(np.ceil(b[2]))] for b in boxes]
    keep = [i for i, c in enumerate(crops) if c.size and min(c.shape[:2]) >= 3]
    boxes, crops = [boxes[i] for i in keep], [crops[i] for i in keep]
    longest = sorted(range(len(boxes)), key=lambda i: -(boxes[i][2] - boxes[i][0]))[:maxn]
    longest = [i for i in longest if boxes[i][2] - boxes[i][0] >= 2 * (boxes[i][3] - boxes[i][1])]
    flip = bool(longest) and eng.orientation_vote([crops[i] for i in longest]) < 0
    if flip:
        crops = [np.ascontiguousarray(np.rot90(c, 2)) for c in crops]
        boxes = [(W - b[2], H - b[3], W - b[0], H - b[1]) for b in boxes]
    out = eng.recognise(crops)
    words = [(t, float(c), b) for (t, c), b in zip(out, boxes) if t]
    return Text(_assemble(words), words), (3 if flip else 1)
