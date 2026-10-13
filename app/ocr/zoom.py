"""Zoom-in re-read of the Government Warning paragraph.

The warning is the smallest text on most labels, so after the first read we find its paragraph, crop it from the
full-resolution image, straighten it if it is tilted, and read it again larger:
  1. find_region: seed at the heading ("GOVERNMENT WARNING") or 2+ anchor words (surgeon, pregnancy, ...),
     grow through nearby lines of similar height.
  2. A generous crop (1.5 region widths each side, 8 lines below), capitals scaled to 32 px, read by OnnxTR.
  3. The paragraph is re-found in that sharper reading, then a tight crop with capitals at 44 px is read by
     Tesseract twice in parallel: Otsu threshold, page mode 6; adaptive threshold, page mode 3.
  4. Before 2-3: if the crop is tilted by 1 degree or more (projection-profile search, about 25 ms), rotate it.
  5. In the tight crop, a block of text printed beside the warning on its own lines (an address, a story in a
     column next to it) is painted over first (beside_warning), so it is not read as words added to the warning.
Region and word coordinates are pixels of the image they came from; `scale` maps them to the full-res image.
"""

import re

import cv2
import numpy as np

from app.verify.warning_judge import REQ, close, norm

HGAP = 1.5
ANCHORS = ["surgeon", "pregnancy", "machinery", "consumption", "beverages", "alcoholic", "defects", "impairs",
           "according", "general", "operate", "problems", "ability"]
GEN_W, GEN_DOWN = 1.5, 8
CAP_GENEROUS, CAP_TIGHT, DET_PER_CAP, DET_MAX = 32, 44, 16, 1024
TESS_PAIRS = (("otsu_auto", 6), ("adapt_auto", 3))
MIN_DESKEW_DEG = 1.0


def _toks(words):
    return [norm(re.sub(r"[^A-Za-z0-9]", "", w[0])) for w in words]


def _seeds(words):
    toks = _toks(words)
    head = [i for i, t in enumerate(toks) if len(t) >= 5 and (close("government", t) or close("warning", t)
                                                              or close("governmentwarning", t))]
    anch = [i for i, t in enumerate(toks) if len(t) >= 5 and any(close(a, t) for a in ANCHORS)]
    return head, anch


def _order_by_dist(boxes, r):
    x0, y0, x1, y1 = r
    return sorted(range(len(boxes)), key=lambda i: max(y0 - boxes[i][3], boxes[i][1] - y1, 0) +
                  0.3 * max(x0 - boxes[i][2], boxes[i][0] - x1, 0))


def _valid(words, r, lh, head):
    """Keep a region only if it holds the heading pair or 2+ anchor words (not e.g. 'safety warnings')."""
    x0, y0, x1, y1 = r
    inside = [w for w in words if x0 - 1 <= (w[2][0] + w[2][2]) / 2 <= x1 + 1 and y0 - 1 <= (w[2][1] + w[2][3]) / 2 <= y1 + 1]
    t = _toks(inside)
    pair = any(close("government", a) and close("warning", b) for a, b in zip(t, t[1:])) or \
        any(len(a) >= 14 and close("governmentwarning", a) for a in t)
    nanch = sum(1 for a in t if len(a) >= 5 and any(close(x, a) for x in ANCHORS))
    if not (pair or nanch >= 2):
        return None
    return x0, y0, x1, y1, lh, ("heading" if head else "anchors")


def find_region(words):
    """-> (x0, y0, x1, y1, line_height, kind) in the words' pixel coordinates, or None."""
    if not words:
        return None
    head, anch = _seeds(words)
    if not head and len(anch) < 2:
        return None
    boxes = [w[2] for w in words]
    hts = [b[3] - b[1] for b in boxes]
    lh = float(np.median([hts[i] for i in (anch or head)]))
    if lh <= 0:
        return None
    start = head[0] if head else anch[0]
    sx0, sy0, sx1, sy1 = boxes[start]
    for i in head + anch:
        x0, y0, x1, y1 = boxes[i]
        if y0 < sy1 + 12 * lh and y1 > sy0 - 12 * lh and x0 < sx1 + 25 * lh and x1 > sx0 - 25 * lh:
            sx0, sy0, sx1, sy1 = min(sx0, x0), min(sy0, y0), max(sx1, x1), max(sy1, y1)
    if not head and len([i for i in anch if boxes[i][0] >= sx0 and boxes[i][2] <= sx1]) < 2:
        return None
    ux0, uy0, ux1, uy1 = sx0, sy0, sx1, sy1
    top_limit = (boxes[head[0]][1] - 0.5 * lh) if head else (sy0 - 3 * lh)
    budget = 80  # the warning is ~42 words; stop before swallowing the whole label

    def inside():
        return sum(1 for b in boxes if ux0 - 1 <= (b[0] + b[2]) / 2 <= ux1 + 1 and uy0 - 1 <= (b[1] + b[3]) / 2 <= uy1 + 1)

    changed = True
    while changed:
        changed = False
        for i in _order_by_dist(boxes, (ux0, uy0, ux1, uy1)):
            x0, y0, x1, y1 = boxes[i]
            if x0 >= ux0 and x1 <= ux1 and y0 >= uy0 and y1 <= uy1:
                continue
            h = y1 - y0
            if h > 2.2 * lh or h < 0.4 * lh or y0 < top_limit:
                continue
            vgap = max(uy0 - y1, y0 - uy1, 0)
            hov = min(x1, ux1) - max(x0, ux0)
            hgap = max(ux0 - x1, x0 - ux1, 0)
            inside_rows = y0 >= uy0 - 0.3 * lh and y1 <= uy1 + 0.3 * lh
            if (vgap <= 1.2 * lh and hov >= 0.5 * (x1 - x0)) or (inside_rows and hgap <= HGAP * lh):
                old = (ux0, uy0, ux1, uy1)
                ux0, uy0, ux1, uy1 = min(ux0, x0), min(uy0, y0), max(ux1, x1), max(uy1, y1)
                if inside() > budget:
                    return _valid(words, old, lh, head)
                changed = True
                break
    return _valid(words, (ux0, uy0, ux1, uy1), lh, head)


COLUMN_GAP = 0.8  # line heights of clear space between the warning's words and a block beside it (a word space is less)
_WARNING_WORDS = {w for w in REQ if len(w) >= 4}


def _warning_like(tok):
    return len(tok) >= 4 and any(close(w, tok) for w in _WARNING_WORDS)


def beside_warning(words, region):
    """Boxes (words' pixel coordinates) of text printed beside the warning on its own lines: an address or a story
    in a column next to it. A word counts when warning words share its line with a clear gap between them (COLUMN_GAP)
    and it doesn't look like a warning word; only a block of 3+ such words on 2+ lines is returned. A word added to
    the warning sits a word space from its neighbours, so it is never among them."""
    x0, y0, x1, y1, lh = region[:5]
    inside = [(t, w[2]) for t, w in zip(_toks(words), words)
              if x0 - 1 <= (w[2][0] + w[2][2]) / 2 <= x1 + 1 and y0 - 1 <= (w[2][1] + w[2][3]) / 2 <= y1 + 1]
    warn = [b for t, b in inside if _warning_like(t)]
    if len(warn) < 8:
        return []
    gap = COLUMN_GAP * lh

    def same_line(a, b):
        return min(a[3], b[3]) - max(a[1], b[1]) >= 0.5 * min(a[3] - a[1], b[3] - b[1])

    def apart(a, b):  # horizontal space between two boxes (0 when they overlap)
        return max(b[0] - a[2], a[0] - b[2], 0)

    out = []
    for t, b in inside:
        if _warning_like(t):
            continue
        line = [w for _, w in inside if same_line(w, b)]
        chain = [w for w in warn if same_line(w, b)]  # the warning on this line, grown through word spaces:
        if not chain:                                 # "drive a car or" stays whole, short words and all
            continue
        grown = True
        while grown:
            more = [w for w in line if w not in chain and any(apart(w, c) < gap for c in chain)]
            chain += more
            grown = bool(more)
        if b not in chain:
            out.append(b)
    rows = {round(((b[1] + b[3]) / 2) / (0.6 * lh)) for b in out}
    return out if len(out) >= 3 and len(rows) >= 2 else []


def binarize(rgb, how):
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    if how.endswith("auto") and np.median(g) < 110:  # light text on dark: make it dark on light
        g = 255 - g
    if how.startswith("otsu"):
        _, g = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    elif how.startswith("adapt"):  # a barcode in the crop made Otsu erase light-grey text
        g = cv2.adaptiveThreshold(cv2.GaussianBlur(g, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY, 31, 10)
    return g


def crop_box(full, box, f, max_side=3000):
    """Crop full[box] and scale by f (at most 4x and max_side). -> (crop, f_used, (X0, Y0))."""
    H, W = full.shape[:2]
    X0, Y0, X1, Y1 = max(0, int(box[0])), max(0, int(box[1])), min(W, int(box[2])), min(H, int(box[3]))
    crop = full[Y0:Y1, X0:X1]
    if crop.size == 0:
        return None, 1.0, (X0, Y0)
    f = min(f, 4.0, max_side / max(crop.shape[:2]))
    if abs(f - 1) > 0.05:
        crop = cv2.resize(crop, None, fx=f, fy=f, interpolation=cv2.INTER_CUBIC if f > 1 else cv2.INTER_AREA)
    else:
        f = 1.0
    return np.ascontiguousarray(crop), f, (X0, Y0)


def generous_box(region, scale):
    x0, y0, x1, y1, lh = region[:5]
    w = x1 - x0
    return ((x0 - GEN_W * w) * scale, (y0 - 1.5 * lh) * scale, (x1 + GEN_W * w) * scale,
            (y1 + GEN_DOWN * lh) * scale), lh * scale


def tight_box(region, scale=1.0, margin_lh=1.5):
    x0, y0, x1, y1, lh = region[:5]
    m = margin_lh * lh + 0.02 * max(x1 - x0, y1 - y0)
    return ((x0 - m) * scale, (y0 - m) * scale, (x1 + m) * scale, (y1 + m) * scale), lh * scale


def two_step(full, scale, region, onnx_read, tess_read):
    """Generous crop read by OnnxTR, then a tight crop read by Tesseract. onnx_read(img, det_size) -> Text;
    tess_read(img, psm) -> future or str. Returns {tag: text or future}."""
    out = {}
    gbox, lh_full = generous_box(region, scale)
    g, fg, (gx, gy) = crop_box(full, gbox, CAP_GENEROUS / max(1.0, 0.7 * lh_full))
    if g is None:
        return out
    det = min(DET_MAX, max(32, int(round(max(g.shape[:2]) * DET_PER_CAP / CAP_GENEROUS / 32)) * 32))
    o = onnx_read(g, det)
    out["zoom-onnx"] = "\n".join(o.lines)
    r2 = find_region(o.words)
    if r2:  # map generous-crop coordinates back to full resolution
        x0, y0, x1, y1, lh2, _ = r2
        tbox, lh_t = tight_box((gx + x0 / fg, gy + y0 / fg, gx + x1 / fg, gy + y1 / fg, lh2 / fg))
        beside = beside_warning(o.words, r2)
    else:
        tbox, lh_t = tight_box(region, scale)
        beside = []
    t, ft, (tx, ty) = crop_box(full, tbox, CAP_TIGHT / max(1.0, 0.7 * lh_t))
    if t is None:
        return out
    if beside:  # paint the side text over with the crop's background before Tesseract reads it
        t = t.copy()
        bg = np.median(t.reshape(-1, t.shape[2]) if t.ndim == 3 else t, axis=0).astype(t.dtype)
        for b in beside:
            X0, Y0 = int(((gx + b[0] / fg) - tx) * ft), int(((gy + b[1] / fg) - ty) * ft)
            X1, Y1 = int(np.ceil(((gx + b[2] / fg) - tx) * ft)), int(np.ceil(((gy + b[3] / fg) - ty) * ft))
            t[max(0, Y0):max(0, Y1), max(0, X0):max(0, X1)] = bg
    for how, psm in TESS_PAIRS:
        out[f"zoom-tess-{how}-psm{psm}"] = tess_read(binarize(t, how), psm)
    return out


def _profile_score(b, ang):
    h, w = b.shape
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    p = cv2.warpAffine(b, M, (w, h), flags=cv2.INTER_NEAREST, borderValue=0).sum(1, dtype=np.float64)
    return float(((p[1:] - p[:-1]) ** 2).sum())


def skew_angle(rgb, long_side=600, rng=8.0):
    """Angle (degrees) whose horizontal row profile is sharpest, searched -8..8 then +-0.5 at 0.1."""
    g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY)
    s = long_side / max(g.shape)
    if s < 1:
        g = cv2.resize(g, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    _, b = cv2.threshold(g, 0, 1, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    if b.mean() > 0.5:
        b = 1 - b
    b = b.astype(np.uint8)
    best = max(np.arange(-rng, rng + 1e-6, 0.5), key=lambda a: _profile_score(b, a))
    return float(max(np.arange(best - 0.5, best + 0.5 + 1e-6, 0.1), key=lambda a: _profile_score(b, a)))


def deskew_two_step(full, scale, region, onnx_read, tess_read):
    """two_step on a generous crop first rotated by its own tilt when |tilt| >= MIN_DESKEW_DEG."""
    gbox, _ = generous_box(region, scale)
    H, W = full.shape[:2]
    X0, Y0 = max(0, int(gbox[0])), max(0, int(gbox[1]))
    X1, Y1 = min(W, int(gbox[2])), min(H, int(gbox[3]))
    raw = full[Y0:Y1, X0:X1]
    if raw.size == 0:
        return {}
    ang = skew_angle(raw)
    if abs(ang) < MIN_DESKEW_DEG:
        return two_step(full, scale, region, onnx_read, tess_read)
    h, w = raw.shape[:2]
    M = cv2.getRotationMatrix2D((w / 2, h / 2), ang, 1.0)
    rot = cv2.warpAffine(np.ascontiguousarray(raw), M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    x0, y0, x1, y1, lh = region[:5]
    pts = np.array([[x0, y0], [x1, y0], [x0, y1], [x1, y1]], dtype=np.float64) * scale - [X0, Y0]
    q = pts @ M[:, :2].T + M[:, 2]
    reg = (q[:, 0].min(), q[:, 1].min(), q[:, 0].max(), q[:, 1].max(), lh * scale) + tuple(region[5:])
    out = two_step(np.ascontiguousarray(rot), 1.0, reg, onnx_read, tess_read)
    return {k + "-deskew": v for k, v in out.items()}
