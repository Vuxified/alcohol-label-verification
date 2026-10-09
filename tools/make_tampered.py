"""Plant one realistic mistake on real TTB-approved label artwork, so the app is tested on real labels, not only ours.

Source: the practice labels only (the "cola_*" ids in data/splits/split.json "dev"); the held-out labels are never
opened. For each label the app's own reader finds the text to change (word boxes from Reader.read, plus a sharper
1536-px pass of the same engine for small type). The old characters are painted out from the surrounding background
(cv2 inpaint) and the new ones drawn at the same height and colour: a glyph copied from elsewhere on the same label
when that character is there (it is then the label's own font), otherwise rendered in the closest-looking font
(tools/fonts and system fonts, picked by overlap with the original word).

Changes (one per item): abv (one digit), proof (no longer 2 x ABV), net (750 mL -> 700 mL and the like; both units
when the label states two), warning_word ("may" -> "can", ...), warning_delete (one word removed, the rest of the
line closed up), warning_titlecase ("Government Warning"), brand_number ("19 Crimes" -> "12 Crimes"), brand_word
(one word of the brand changed).

Every tampered label is then read again by the app's reader: the item is kept only if the planted text is read and the
original value is no longer read anywhere (otherwise it tests nothing, or the label honestly still shows the right
value). The expected verdict and finding code come from the app's own rules applied to the planted text alone.

Output: data/tampered/<cola_id>__<change>/{tampered and untouched images, item.json, preview.png (before | after)},
data/tampered/manifest.csv and data/tampered/report.json (what was made, skipped, dropped, and the app's verdicts).

The second set (--set extra) is built the same way from the 78 extra practice labels in
data/splits/practice_extra.json and written to data/tampered_extra/: the 64 original practice labels may later be used
to train the reader, and then only the extra set stays a fair test.

Every kept item's preview.png was looked at; the few with a visible flaw are listed in REJECTED below and are replaced
by spare items of the same kind (--reselect redoes only that choice, from the staged items in out/).

Usage: python tools/make_tampered.py [--set dev|extra] [--target 100] [--only 24009001000331,...] [--cpus 4]
       python tools/make_tampered.py --set dev --reselect     # re-pick the kept items after a review
"""

import argparse
import csv
import io
import json
import re
import shutil
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ocr.reader import Reader  # noqa: E402
from app.pipeline import check_application  # noqa: E402
from app.verify import Application, Verdict  # noqa: E402
from app.verify.abv import check_abv, check_proof, find_abv, find_proof  # noqa: E402
from app.verify.model import SEVERITY  # noqa: E402
from app.verify.net_contents import check_net_contents, find_amounts, parse_typed_net  # noqa: E402
from app.verify.text import match_text, normalize  # noqa: E402

DATA = ROOT / "data"
OUT = DATA / "tampered"
LOOKALIKE = {frozenset(p) for p in ("08", "17", "38", "56", "68", "14", "89", "58")}  # as app/verify/text.py
SPIRITS_ML = {3750, 3000, 2000, 1800, 1750, 1500, 1000, 945, 900, 750, 720, 710, 700, 570, 500, 475, 375, 355, 350,
              331, 250, 200, 187, 100, 50}
WINE_ML = {3000, 2250, 1800, 1500, 1000, 750, 720, 700, 620, 600, 568, 550, 500, 473, 375, 360, 355, 330, 300, 250, 200,
           187, 180, 100, 50}
CHANGES = ["abv", "proof", "net", "warning_word", "warning_delete", "warning_titlecase", "brand_number", "brand_word"]
WORD_SWAPS = [("may", "can", "and can cause"), ("should", "must", "women must not"),
              ("impairs", "affects", "beverages affects your")]
DELETIONS = [("not", "should drink"), ("health", "cause problems"), ("birth", "risk of defects"),
             ("alcoholic", "drink beverages")]
BRAND_SWAPS = {"royal": "regal", "moon": "mood", "goose": "horse", "nevada": "madre", "roses": "ravens",
               "silver": "golden", "ultra": "ultima", "extra": "light", "blue": "red", "home": "hill", "morgan": "morris",
               "beam": "bear", "crawford": "cranford", "adams": "evans", "artois": "aurora", "reserve": "reserva",
               "tea": "tee", "light": "lite", "bros": "boys", "goose ": "horse", "margherita": "marina",
               "crimes": "crowns", "estates": "estate", "winery": "cellars", "tail": "tale", "jackson": "johnson"}
# Looked at by eye (preview.png): items whose edit is visibly wrong are not used.
REJECTED = {
    "cola_23354001000635__warning_titlecase": "the line under the heading was smeared",
    "cola_24011001000341__warning_titlecase": "only GOVERNMENT was re-cased (WARNING stayed in capitals)",
    "cola_24107001001085__warning_titlecase": "only WARNING was re-cased (GOVERNMENT stayed in capitals)",
    "cola_24129001000620__brand_word": "closing up the line garbled the next word (lifestyle)",
    # extra set
    "cola_25212001000725__warning_titlecase": "the tail of the g in Warning was cut off (reads Warnina)",
    "cola_25293001000020__abv": "the decimal point was lost (12 2%)",
    "cola_25344001000949__net": "the new digits are spaced apart (7 2 0ml)",
    "cola_26169001000018__warning_titlecase": "only WARNING was re-cased (GOVERNMENT stayed in capitals)",
    "cola_26155001000642__warning_word": "the text beside the warning (CONTAINS SULFITES) was smeared",
    "cola_25344001000949__warning_word": "a stray colon was left after the closed-up line",
    "cola_26169001000018__warning_word": "the closed-up line ends in a doubled full stop",
    "cola_26196001000791__net": "the new 2 is visibly heavier than the other digits",
}
DESCENDERS = set("gjpqy,;")
MIN_FONT_IOU = 0.5   # a drawn word must overlap the original's ink this well in the chosen font, or it is skipped

FONT_DIRS = [ROOT / "tools" / "fonts", Path("/System/Library/Fonts/Supplemental"), Path("/System/Library/Fonts"),
             Path("/Library/Fonts"), Path("/usr/share/fonts")]
FONT_FILES = [("Helvetica.ttc", (0, 1)), ("HelveticaNeue.ttc", (0, 1, 4)), ("Arial.ttf", (0,)),
              ("Arial Bold.ttf", (0,)), ("Arial Narrow.ttf", (0,)), ("Arial Narrow Bold.ttf", (0,)),
              ("Futura.ttc", (0, 2, 4)), ("GillSans.ttc", (0, 1)), ("Georgia.ttf", (0,)), ("Georgia Bold.ttf", (0,)),
              ("Times New Roman.ttf", (0,)), ("Times New Roman Bold.ttf", (0,)), ("Avenir Next Condensed.ttc", (0, 2)),
              ("DIN Condensed Bold.ttf", (0,)), ("DIN Alternate Bold.ttf", (0,)), ("Optima.ttc", (0, 1)),
              ("Palatino.ttc", (0, 1)), ("Didot.ttc", (0, 1)), ("Copperplate.ttc", (0, 1)), ("Impact.ttf", (0,)),
              ("Oswald[wght].ttf", (0,)), ("LibreFranklin[wght].ttf", (0,)), ("BebasNeue-Regular.ttf", (0,)),
              ("OldStandard-Regular.ttf", (0,)), ("OldStandard-Bold.ttf", (0,)), ("Cinzel[wght].ttf", (0,)),
              ("PlayfairDisplay[wght].ttf", (0,)), ("DejaVuSans.ttf", (0,)), ("DejaVuSans-Bold.ttf", (0,))]


def _fonts():
    out = []
    for name, idxs in FONT_FILES:
        path = next((d / name for d in FONT_DIRS if (d / name).exists()), None)
        if path is None:
            continue
        for i in idxs:
            for wght in ((400, 700) if "[wght]" in name else (None,)):
                try:
                    ImageFont.truetype(str(path), 40, index=i)
                    out.append((str(path), i, wght))
                except OSError:
                    pass
    return out


FONTS = _fonts()
_FONT_CACHE = {}


def font(spec, px):
    key = (spec, px)
    if key not in _FONT_CACHE:
        path, i, wght = spec
        f = ImageFont.truetype(path, px, index=i)
        if wght:
            f.set_variation_by_axes([wght])
        _FONT_CACHE[key] = f
    return _FONT_CACHE[key]


def render(text, spec, px=120):
    """-> (alpha 0..1, baseline row, ink bbox (x0, y0, x1, y1)) of `text` drawn with its left baseline at (pad, base)."""
    f = font(spec, px)
    pad = px // 2
    w = int(f.getlength(text)) + 2 * pad
    img = Image.new("L", (w, 3 * px), 0)
    base = int(1.8 * px)
    ImageDraw.Draw(img).text((pad, base), text, font=f, fill=255, anchor="ls")
    a = np.asarray(img, np.float32) / 255
    ys, xs = np.nonzero(a > 0.5)
    if not len(xs):
        return None
    return a, base, (xs.min(), ys.min(), xs.max() + 1, ys.max() + 1)


# ---------------------------------------------------------------- ink analysis on the label picture
@dataclass
class Glyph:
    x0: int
    y0: int
    x1: int
    y1: int   # ink box, full-image pixels (x1, y1 exclusive)


@dataclass
class Ink:
    """The ink of one region: background colour, distance-from-background map, threshold, glyph runs."""
    x0: int
    y0: int
    dist: np.ndarray
    t: float
    t_ink: float
    bg: np.ndarray
    runs: list

    def alpha(self, img_crop_dist):
        return np.clip((img_crop_dist - 0.75 * self.t) / max(1.0, self.t_ink - 0.75 * self.t), 0, 1)


def otsu(v):
    v = np.clip(v, 0, 441).astype(np.uint8 if v.max() < 256 else np.uint16)
    v8 = np.clip(v, 0, 255).astype(np.uint8)
    t, _ = cv2.threshold(v8.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return float(t)


def analyse(img, box, pad=3):
    H, W = img.shape[:2]
    x0, y0 = max(0, int(box[0]) - pad), max(0, int(box[1]) - pad)
    x1, y1 = min(W, int(np.ceil(box[2])) + pad), min(H, int(np.ceil(box[3])) + pad)
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    crop = img[y0:y1, x0:x1].astype(np.float32)
    border = np.concatenate([crop[0], crop[-1], crop[:, 0], crop[:, -1]])
    bg = np.median(border, axis=0)
    dist = np.linalg.norm(crop - bg, axis=2)
    t = max(otsu(dist), 35.0)
    mask = dist > t
    if mask.sum() < 6:
        return None
    t_ink = float(np.percentile(dist[mask], 70))
    # the text band: the rows holding most of the ink (drops bits of the lines above and below)
    rows = mask.sum(1)
    on = rows > max(1, 0.08 * rows.max())
    bands, start = [], None
    for i, v in enumerate(list(on) + [False]):
        if v and start is None:
            start = i
        if not v and start is not None:
            bands.append((start, i))
            start = None
    b0, b1 = max(bands, key=lambda b: rows[b[0]:b[1]].sum())
    m = np.zeros_like(mask)
    m[b0:b1] = mask[b0:b1]
    cols = m.sum(0)
    runs, start = [], None
    for i, v in enumerate(list(cols > 0) + [False]):
        if v and start is None:
            start = i
        if not v and start is not None:
            ys = np.nonzero(m[:, start:i].any(1))[0]
            runs.append([start, ys.min(), i, ys.max() + 1, int(m[:, start:i].sum())])
            start = None
    if not runs:
        return None
    big = max(r[4] for r in runs)
    runs = [Glyph(r[0] + x0, r[1] + y0, r[2] + x0, r[3] + y0) for r in runs if r[4] >= 0.03 * big]
    return Ink(x0, y0, dist, t, t_ink, bg, runs)


def word_groups(ink, height):
    """Split runs into words at gaps wider than a third of the text height."""
    groups, cur = [], [ink.runs[0]]
    for a, b in zip(ink.runs, ink.runs[1:]):
        if b.x0 - a.x1 > max(2, 0.33 * height):
            groups.append(cur)
            cur = []
        cur.append(b)
    return groups + [cur]


def bbox(glyphs):
    return (min(g.x0 for g in glyphs), min(g.y0 for g in glyphs), max(g.x1 for g in glyphs), max(g.y1 for g in glyphs))


# ---------------------------------------------------------------- one label picture being edited
@dataclass
class Word:
    text: str
    conf: float
    box: tuple   # full-image px of the (turned) picture
    src: str = "hi"  # which reading: "hi" (1536 px) or "main" (the app's 768-px main read)


class Pic:
    def __init__(self, name, data, full, k, words):
        self.name, self.data, self.k = name, data, k
        self.orig = full
        self.img = full.copy()
        self.words = words
        self.changed = []   # boxes that were edited

    def line_of(self, w, same_height=True):
        cy, h = (w.box[1] + w.box[3]) / 2, w.box[3] - w.box[1]
        return sorted([o for o in self.words if o.src == w.src and abs((o.box[1] + o.box[3]) / 2 - cy) < 0.4 * h
                       and (not same_height or abs((o.box[3] - o.box[1]) - h) < 0.35 * h)], key=lambda o: o.box[0])

    def word_ink(self, w):
        """-> (Ink of the line around w, the glyph runs of w) using ink gaps, not the detector's overlapping boxes."""
        line = [o for o in self.line_of(w) if o.box[2] > w.box[0] - 3 * (w.box[3] - w.box[1])
                and o.box[0] < w.box[2] + 3 * (w.box[3] - w.box[1])]
        ux0, ux1 = min(o.box[0] for o in line + [w]), max(o.box[2] for o in line + [w])
        ink = analyse(self.img, (ux0, w.box[1], ux1, w.box[3]))
        if ink is None:
            return None, None
        # the glyphs whose centre lies inside the detector's box (its boxes overlap a little, centres do not)
        best = [g for g in ink.runs if w.box[0] <= (g.x0 + g.x1) / 2 <= w.box[2]]
        if not best:
            return None, None
        return ink, best


def char_runs(text, runs):
    """Map characters to glyph runs when it is unambiguous (one run per character)."""
    chars = [c for c in text if not c.isspace()]
    return list(zip(chars, runs)) if len(chars) == len(runs) else None


def glyph_patch(img, ink, g):
    crop = img[g.y0:g.y1, g.x0:g.x1].astype(np.float32)
    d = np.linalg.norm(crop - ink.bg, axis=2)
    return crop, ink.alpha(d)


def erase(img, glyphs, pad=2, ref=None):
    """Paint the glyphs out from the surrounding background (inpainting the ink pixels only). Each glyph's box is
    grown a little up and down, so the overshoot of round letters (O, 0, S) above and below the line goes too."""
    x0, y0, x1, y1 = bbox(glyphs)
    H, W = img.shape[:2]
    m = 12
    X0, Y0, X1, Y1 = max(0, x0 - m), max(0, y0 - m), min(W, x1 + m), min(H, y1 + m)
    region = img[Y0:Y1, X0:X1]
    mask = np.zeros(region.shape[:2], np.uint8)
    # the background colour and threshold of the whole word or line (a tight box around one letter cuts through
    # its neighbours, and their ink would tint the estimate)
    ink = ref if ref is not None else analyse(img, (x0, y0, x1, y1), pad=pad + 1)
    bg = ink.bg if ink is not None else np.median(region.reshape(-1, 3), 0)
    t = 0.45 * (ink.t if ink is not None else 40)
    for g in glyphs:
        ey = max(2, round(0.12 * (g.y1 - g.y0)))
        gy0, gy1 = max(Y0, g.y0 - ey), min(Y1, g.y1 + ey)
        gx0, gx1 = max(X0, g.x0 - 1), min(X1, g.x1 + 1)
        sub = region[gy0 - Y0:gy1 - Y0, gx0 - X0:gx1 - X0].astype(np.float32)
        mask[gy0 - Y0:gy1 - Y0, gx0 - X0:gx1 - X0] = (np.linalg.norm(sub - bg, axis=2) > t) * 255
    mask = cv2.dilate(mask, np.ones((2 * pad + 1, 2 * pad + 1), np.uint8))
    # neighbouring letters must not bleed into the fill: hide all other ink behind the background colour first
    other = np.linalg.norm(region.astype(np.float32) - bg, axis=2) > t
    other = cv2.dilate(other.astype(np.uint8), np.ones((3, 3), np.uint8)).astype(bool) & (mask == 0)
    tmp = region.copy()
    tmp[other] = bg
    filled = cv2.inpaint(np.ascontiguousarray(tmp), mask, 3, cv2.INPAINT_TELEA)
    region[mask > 0] = filled[mask > 0]


def ink_colour(img, ink, glyphs):
    vals = []
    for g in glyphs:
        crop, a = glyph_patch(img, ink, g)
        vals.append(crop[a > 0.9])
    v = np.concatenate(vals) if vals else np.zeros((0, 3))
    return np.median(v, 0) if len(v) else (255 - ink.bg)


def composite(img, x, y, alpha, colour=None, src=None):
    """Blend a glyph (alpha, and either one colour or source pixels) into img with its top-left at (x, y)."""
    H, W = img.shape[:2]
    h, w = alpha.shape
    if x < 0 or y < 0 or x + w > W or y + h > H:
        return False
    region = img[y:y + h, x:x + w].astype(np.float32)
    top = src if src is not None else np.broadcast_to(np.asarray(colour, np.float32), region.shape)
    a = alpha[..., None]
    img[y:y + h, x:x + w] = np.clip(region * (1 - a) + top * a, 0, 255).astype(np.uint8)
    return True


def best_font(img, ink, glyphs, text):
    """The font whose rendering of `text` overlaps the real ink best (both squeezed to the same box)."""
    x0, y0, x1, y1 = bbox(glyphs)
    if x1 - x0 < 3 or y1 - y0 < 3:
        return FONTS[0], 0.0
    sub = ink.dist[y0 - ink.y0:y1 - ink.y0, x0 - ink.x0:x1 - ink.x0] > ink.t
    best = (FONTS[0], -1.0)
    for spec in FONTS:
        r = render(text, spec)
        if r is None:
            continue
        a, _, (rx0, ry0, rx1, ry1) = r
        rr = cv2.resize(a[ry0:ry1, rx0:rx1], (x1 - x0, y1 - y0), interpolation=cv2.INTER_AREA) > 0.5
        iou = (rr & sub).sum() / max(1, (rr | sub).sum())
        if iou > best[1]:
            best = (spec, float(iou))
    return best


def baseline_of(glyphs, text):
    """Bottom of the glyphs that sit on the line (descenders such as g, y and commas left out)."""
    pairs = char_runs(text, glyphs)
    if pairs:
        bottoms = [g.y1 for c, g in pairs if c not in DESCENDERS and c not in "()" and c.isalnum()]
        if bottoms:
            return int(np.median(bottoms))
    return int(np.median([g.y1 for g in glyphs]))


def draw_text(img, ink, old_glyphs, old_text, new_text, x_left, colour, spec, max_w=None):
    """Render new_text in `spec`, scaled like old_text was, with its left edge at x_left on the old baseline."""
    r_old = render(old_text, spec)
    r_new = render(new_text, spec)
    if r_old is None or r_new is None:
        return None
    a_o, base_o, (ox0, oy0, ox1, oy1) = r_old
    x0, y0, x1, y1 = bbox(old_glyphs)
    base = baseline_of(old_glyphs, old_text)
    sy = (base - y0) / max(1, base_o - oy0)
    sx = (x1 - x0) / max(1, ox1 - ox0)
    a_n, base_n, (nx0, ny0, nx1, ny1) = r_new
    if max_w and (nx1 - nx0) * sx > max_w:
        sx = max_w / (nx1 - nx0)
    crop = a_n[ny0:ny1, nx0:nx1]
    w, h = max(1, round((nx1 - nx0) * sx)), max(1, round((ny1 - ny0) * sy))
    a = np.clip(cv2.resize(crop, (w, h), interpolation=cv2.INTER_AREA), 0, 1)
    top = base - round((base_n - ny0) * sy)
    return (x_left, top, w, h) if composite(img, int(x_left), int(top), a, colour) else None


def library(pic, near_box, height, exclude=None):
    """Glyphs of known characters elsewhere on the picture at the same text height: char -> [(Ink, Glyph, baseline)]."""
    lib = defaultdict(list)
    cy = (near_box[1] + near_box[3]) / 2
    for w in sorted(pic.words, key=lambda o: abs((o.box[1] + o.box[3]) / 2 - cy)):
        if w is exclude or w.conf < 0.8 or not (0.85 * height <= w.box[3] - w.box[1] <= 1.15 * height):
            continue
        ink, glyphs = pic.word_ink(w)
        pairs = char_runs(w.text, glyphs) if glyphs else None
        if not pairs:
            continue
        gh = max(g.y1 for g in glyphs) - min(g.y0 for g in glyphs)
        base = baseline_of(glyphs, w.text)
        for c, g in pairs:
            lib[c].append((ink, g, base, gh))
        if len(lib) > 40:
            break
    return lib


# ---------------------------------------------------------------- the edits
def replace_chars(pic, w, subs):
    """subs: {char index in w.text: new char}. Each old glyph is painted out and the new one put in its place."""
    ink, glyphs = pic.word_ink(w)
    if not glyphs:
        return "word ink not found"
    chars = [c for c in w.text if not c.isspace()]
    targets = {}
    for i, new in subs.items():
        if len(glyphs) == len(chars):
            g = glyphs[i]
        elif i < len(chars) / 2 and i < len(glyphs):
            g = glyphs[i]
        elif len(chars) - i <= len(glyphs):
            g = glyphs[len(glyphs) - (len(chars) - i)]
        else:
            return "glyphs and letters do not line up"
        gw, gh = g.x1 - g.x0, g.y1 - g.y0
        if not (0.12 * gh <= gw <= 1.05 * gh):
            return "glyph is not a single digit"
        targets[i] = g
    gh_word = max(g.y1 for g in glyphs) - min(g.y0 for g in glyphs)
    lib = library(pic, w.box, w.box[3] - w.box[1])
    colour = ink_colour(pic.img, ink, glyphs)
    spec = None
    plans = []
    for i, g in targets.items():
        new = subs[i]
        src = [(si, sg, sb, sh) for si, sg, sb, sh in lib.get(new, []) if abs(sh - gh_word) <= 0.1 * gh_word
               and np.linalg.norm(si.bg - ink.bg) < 30
               and abs((sg.y1 - sg.y0) - (g.y1 - g.y0)) <= max(2, 0.1 * (g.y1 - g.y0))]
        plans.append((g, new, src[0] if src else None))
    patches = []
    for g, new, src in plans:   # read the source glyphs before anything is painted out
        if src:
            si, sg, _, _ = src
            crop, a = glyph_patch(pic.img, si, sg)
            patches.append((g, new, (crop.copy(), a.copy())))
        else:
            patches.append((g, new, None))
    erase(pic.img, [g for g, _, _ in plans], ref=ink)
    for g, new, patch in patches:
        if patch:
            crop, a = patch
            h, wd = a.shape
            x = round((g.x0 + g.x1) / 2 - wd / 2)
            ok = composite(pic.img, x, g.y1 - h, a, colour)
        else:
            if spec is None:
                spec, iou = best_font(pic.img, ink, glyphs, "".join(chars))
                if iou < MIN_FONT_IOU:
                    return "no font close enough to the label's"
            ok = draw_digit(pic.img, g, chars[[k for k, t in targets.items() if t is g][0]], new, colour, spec)
        if not ok:
            return "could not draw the new character"
        pic.changed.append((g.x0, g.y0, g.x1, g.y1))
    return None


def draw_digit(img, g, old, new, colour, spec):
    ro, rn = render(old, spec), render(new, spec)
    if ro is None or rn is None:
        return False
    _, _, (ox0, oy0, ox1, oy1) = ro
    a_n, _, (nx0, ny0, nx1, ny1) = rn
    sy = (g.y1 - g.y0) / max(1, oy1 - oy0)
    sx = (g.x1 - g.x0) / max(1, ox1 - ox0) if old not in "1.:" else sy
    sx = float(np.clip(sx, 0.6 * sy, 1.5 * sy))
    w, h = max(1, round((nx1 - nx0) * sx)), max(1, round((ny1 - ny0) * sy))
    a = np.clip(cv2.resize(a_n[ny0:ny1, nx0:nx1], (w, h), interpolation=cv2.INTER_AREA), 0, 1)
    return composite(img, round((g.x0 + g.x1) / 2 - w / 2), g.y1 - h, a, colour)


def right_of(pic, w):
    h = w.box[3] - w.box[1]
    # any height: "(1)" is often boxed taller than the words around it
    return [o for o in pic.line_of(w, same_height=False) if o.box[0] > w.box[2] - 0.2 * h and o is not w
            and (o.box[3] - o.box[1]) < 2.2 * h]


def close_up(pic, w, old_x1, new_x1):
    """Move the rest of w's line sideways so the next word keeps its spacing after w's new end (new_x1)."""
    right = right_of(pic, w)
    delta = int(round(old_x1 - new_x1))
    if not right or abs(delta) < 2:
        return None
    ink_r, first = pic.word_ink(right[0])
    if not first:
        return "next word not found"
    nx0 = bbox(first)[0]
    H, W = pic.img.shape[:2]
    end = min(W, int(max(o.box[2] for o in right)) + 2)
    # only the rows of this line's ink, so the lines above and below are not dragged along
    line_runs = [g for g in ink_r.runs if g.x0 >= nx0 - 1] or first
    # cut the strip at the emptiest rows just above and below this line's letters
    gh = int(np.median([g.y1 - g.y0 for g in line_runs]))
    ym0, ym1 = int(np.median([g.y0 for g in line_runs])), int(np.median([g.y1 for g in line_runs]))
    band = np.linalg.norm(pic.img[:, nx0:end].astype(np.float32) - ink_r.bg, axis=2) > ink_r.t
    rows = band.sum(1)
    up = range(max(0, ym0 - gh // 3), ym0 + 1)
    down = range(ym1, min(H, ym1 + gh // 3 + 1))
    top = min(up, key=lambda r: (rows[r], -r)) if len(up) else max(0, ym0 - 1)
    bot = (min(down, key=lambda r: (rows[r], r)) + 1) if len(down) else min(H, ym1 + 1)
    if delta < 0:  # wider: no room to move into, leave the line as it is
        return None
    strip = pic.img[top:bot, nx0 - 1:end].copy()
    pic.img[top:bot, nx0 - 1 - delta:end - delta] = strip
    tail = analyse(pic.img, (end - delta - 1, top, end, bot), pad=0)
    if tail is not None and tail.runs:
        erase(pic.img, tail.runs, ref=ink_r)
    pic.changed.append((int(new_x1), top, end, bot))
    return None


def replace_word(pic, w, new_text, keep_first=False, x_start=None, close=False):
    """Replace a whole word: glyphs copied from the same picture when every letter is there at the same size,
    else rendered in the font that looks most like the word. keep_first keeps the word's own first letter
    ("G" of GOVERNMENT); x_start moves the word; close moves the rest of the line to keep the spacing.
    -> (error or None, new right edge)."""
    ink, glyphs = pic.word_ink(w)
    if not glyphs:
        return "word ink not found", None
    old = w.text
    x0, y0, x1, y1 = bbox(glyphs)
    gh = y1 - y0
    base = baseline_of(glyphs, old)
    colour = ink_colour(pic.img, ink, glyphs)
    gap = int(np.median([b.x0 - a.x1 for a, b in zip(glyphs, glyphs[1:])])) if len(glyphs) > 1 else 2
    gap = max(1, gap)
    right = right_of(pic, w)
    if right:
        _, nxt = pic.word_ink(right[0])
        room = (bbox(nxt)[0] - x0) if nxt else None
    else:
        room = None
    start = x0 if x_start is None else int(x_start)
    first = None
    keep_first = keep_first and bool(char_runs(old, glyphs))  # only when the first glyph is surely one letter
    if keep_first:
        crop, a = glyph_patch(pic.img, ink, glyphs[0])
        first = (crop.copy(), a.copy(), glyphs[0])
    body_new = new_text[1:] if keep_first else new_text
    lib = library(pic, w.box, w.box[3] - w.box[1], exclude=w)
    cap_h = gh if re.sub(r"[^A-Za-z0-9]", "", old).isupper() else None
    srcs = []
    for c in body_new:
        cands = [s_ for s_ in lib.get(c, []) if (not (cap_h and (c.isupper() or c.isdigit()))
                 or abs((s_[1].y1 - s_[1].y0) - cap_h) <= 0.12 * cap_h) and np.linalg.norm(s_[0].bg - ink.bg) < 30]
        srcs.append(cands[0] if cands else None)
    patches = None
    if body_new and all(srcs):
        patches = [((s_[0], s_[1]), s_[1].y1 - s_[2]) for s_ in srcs]
        patches = [(tuple(v.copy() for v in glyph_patch(pic.img, si, sg)), off) for (si, sg), off in patches]
    spec = None
    if patches is None:
        spec, iou = best_font(pic.img, ink, glyphs, old)
        if iou < MIN_FONT_IOU:
            return "no font close enough to the label's", None
    erase(pic.img, glyphs, ref=ink)
    x = start
    if first:
        crop, a, g = first
        if not composite(pic.img, int(x), g.y1 - a.shape[0], a, src=crop):
            return "could not draw the new word", None
        x += a.shape[1] + gap
    if patches:
        widths = sum(a.shape[1] for (_, a), _ in patches)
        if len(body_new) == len(old if not keep_first else old[1:]) and len(patches) > 1:
            # same number of letters: the same overall width as the old word, by adjusting the letter spacing
            gap = float(np.clip(((x1 - x0) - (x - start) - widths) / (len(patches) - 1), 0, gap))
        total = widths + gap * (len(patches) - 1)
        squeeze = 1.0
        fit = (x1 - x0) + 0.35 * (room - (x1 - x0)) - (x - start) if room else None
        if fit and x_start is None and total > fit:   # keep most of the space before the next word
            squeeze = fit / total
            if squeeze < 0.8:
                return "the new word does not fit", None
        for (crop, a), off in patches:
            if squeeze < 1:
                nw = max(1, round(a.shape[1] * squeeze))
                crop = cv2.resize(crop, (nw, a.shape[0]), interpolation=cv2.INTER_AREA)
                a = cv2.resize(a, (nw, a.shape[0]), interpolation=cv2.INTER_AREA)
            # the copied letter's shape, in this word's own ink colour (the source may sit on another tint)
            if not composite(pic.img, int(round(x)), int(base + off - a.shape[0]), a, colour):
                return "could not draw the new word", None
            x += a.shape[1] + gap * squeeze
        x -= gap * squeeze
    elif body_new:
        max_w = ((x1 - x0) + 0.35 * (room - (x1 - x0)) - (x - start)) if room and x_start is None else None
        res = draw_text(pic.img, ink, glyphs, old, body_new, x, colour, spec, max_w)
        if res is None:
            return "could not draw the new word", None
        x = res[0] + res[2]
    pic.changed.append((min(x0, start), y0, max(x1, int(x)), y1))
    if close:
        err = close_up(pic, w, x1, x)
        if err:
            return err, None
    return None, int(x)


def delete_word(pic, w):
    """Remove a word and close up the rest of the line."""
    ink, glyphs = pic.word_ink(w)
    if not glyphs:
        return "word ink not found"
    x0, y0, x1, y1 = bbox(glyphs)
    erase(pic.img, glyphs, ref=ink)
    pic.changed.append((x0, y0, x1, y1))
    right = right_of(pic, w)
    if right:
        _, nxt = pic.word_ink(right[0])
        if not nxt:
            return "next word not found"
        # the next word moves to where the deleted one started
        return close_up(pic, w, bbox(nxt)[0], x0)
    return None


# ---------------------------------------------------------------- planning one label's changes
def number_tokens(s):
    return [(m.group(0), m.start()) for m in re.finditer(r"\d+(?:[.,]\d+)?", s)]


def find_number_words(pics, num, context):
    """Words holding `num` as a whole number, with `context` (a regex) in the same word or a neighbour."""
    hits = []
    pat = re.compile(rf"(?<![\d.,]){re.escape(num)}(?![\d]|[.,]\d)")
    for p in pics:
        ws = sorted(p.words, key=lambda o: (round(o.box[1] / max(1, o.box[3] - o.box[1])), o.box[0]))
        for w in p.words:
            m = pat.search(w.text)
            if not m:
                continue
            line = p.line_of(w, same_height=False)
            i = line.index(w) if w in line else -1
            near = " ".join(o.text for o in line[max(0, i - 1):i + 2]) if i >= 0 else w.text
            if re.search(context, near, re.I) and not re.search(r"\bper\b|serving|average|analysis", near, re.I):
                hits.append((p, w, m.start()))
        del ws
    # the 768-px and 1536-px readings see the same word twice: keep one box per place
    out = []
    for p, w, s in sorted(hits, key=lambda h: -h[1].conf):
        if not any(q is p and _iou(w.box, v.box) > 0.3 for q, v, _ in out):
            out.append((p, w, s))
    return out


def _iou(a, b):
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    u = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - ix * iy
    return ix * iy / u if u > 0 else 0


def digit_options(num, ok):
    """Numbers with one digit of `num` changed (never a pair readers confuse), nearest first, filtered by ok(value)."""
    out = []
    for i, c in enumerate(num):
        if not c.isdigit():
            continue
        for d in "0123456789":
            if d == c or frozenset((c, d)) in LOOKALIKE or (i == 0 and d == "0"):
                continue
            new = num[:i] + d + num[i + 1:]
            v, v0 = float(new.replace(",", ".")), float(num.replace(",", "."))
            if ok(v, v0):
                out.append((abs(v - v0), i, new))
    return [(i, new) for _, i, new in sorted(out)]


def prefer_present(options, num, hits):
    """Options whose new digits already appear on the same line(s) first: they can be copied, not drawn."""
    near = "".join(o.text for p, w, _ in hits for o in p.line_of(w) if o.conf >= 0.8)
    new_digits = lambda new: [b for a, b in zip(num, new) if a != b]
    point = num.find(".") if "." in num else num.find(",") if "," in num else len(num)
    # a whole-number change first (45 -> 40, 13.5 -> 14.5), then one whose digit can be copied
    return sorted(options, key=lambda o: (o[0] > point, not all(d in near for d in new_digits(o[1]))))


def worst(results):
    return max((r.verdict for r in results), key=lambda v: SEVERITY[v])


def expected_from(results):
    bad = [r for r in results if r.verdict in (Verdict.FAIL, Verdict.CHECK)]
    if not bad or any(r.verdict == Verdict.PASS and r.code is None and False for r in results):
        return None
    return {"overall": worst(bad).value, "findings": [r.code for r in bad if r.code]}


def application_of(rec, gt):
    imported = rec.get("source") == "imported"
    return Application(rec["product_type"] or "spirits", gt["brand_name"], gt.get("class_type"), gt.get("abv"),
                       gt.get("net_contents_text"), gt.get("name_address_text"), rec.get("source", "domestic"),
                       gt.get("country_of_origin_text") if imported else None)


def plan_abv(gt, app, pics, kind):
    if kind == "proof":
        if not gt.get("proof") or app.beverage_type != "spirits":
            return None, "no proof on this label"
        value, ctx = float(gt["proof"]), r"proof"
        rng = lambda v, v0: 0 < abs(v - v0) <= 6 and abs(v - 2 * (app.abv or 0)) > 0.5
    else:
        if app.abv is None or app.abv < 0.5:
            return None, "no alcohol content to change"
        value, ctx = float(app.abv), r"%|alc|vol"
        lo, hi = {"spirits": (20, 70), "wine": (7, 20), "malt": (3, 12)}[app.beverage_type]
        if app.abv < lo:
            lo, hi = app.abv * 0.6, app.abv * 1.6
        rng = lambda v, v0: lo <= v <= hi and 0 < abs(v - v0) <= 3
    src = gt.get("abv_text") or ""
    nums = [n for n, _ in number_tokens(src) if abs(float(n.replace(",", ".")) - value) < 0.01]
    if not nums:
        nums = [f"{value:g}"]
    num = nums[0]
    hits = find_number_words(pics, num, ctx)
    if not hits:
        return None, f'the reader did not find "{num}" next to {ctx.replace("|", "/")}'
    for i, new in prefer_present(digit_options(num, rng), num, hits):
        new_text = src.replace(num, new, 1) if num in src else new
        if kind == "proof":
            lines = [new_text if "proof" in new_text.lower() else f"{src} {new} PROOF"]
            res = [check_proof(app, lines)]
        else:
            lines = [new_text] + ([f"{gt['proof']:g} PROOF"] if gt.get("proof") and "proof" not in src.lower() else [])
            res = [check_abv(app, lines)] + ([check_proof(app, lines)] if app.beverage_type == "spirits" else [])
        exp = expected_from(res)
        if exp and res[0].verdict != Verdict.PASS:
            frm, to = (src or num, new_text) if kind == "abv" else (f"{num} PROOF", f"{new} PROOF")
            return {"hits": hits, "num": num, "new": new, "digit": i, "from": frm, "to": to,
                    "expected": exp}, None
    return None, "no safe one-digit change"


def plan_net(gt, app, pics):
    src = gt.get("net_contents_text") or ""
    toks = number_tokens(src)
    if not toks or app.beverage_type == "malt" and len(toks) > 2 or len(toks) > 2:
        return None, "net contents with several numbers"
    expected_ml = parse_typed_net(src, app.beverage_type)
    fills = {"spirits": SPIRITS_ML, "wine": WINE_ML}.get(app.beverage_type)
    unit_ctx = r"m\s*l|ml|\bl\b|\d\s*l\b|cl|oz|fl|gal|pint|liter|litre"
    found = []
    for num, _ in toks:
        hits = find_number_words(pics, num, unit_ctx)
        if not hits:
            return None, f'the reader did not find "{num}" next to a unit'
        found.append((num, hits))
    malt_pairs = {"12": ("16", {"355": "473"}), "16": ("12", {"473": "355"})}
    candidates = []
    if app.beverage_type == "malt" and toks[0][0] in malt_pairs:
        new0, extra = malt_pairs[toks[0][0]]
        mp = {toks[0][0]: new0} | {t: extra[t] for t, _ in toks[1:] if t in extra}
        if len(mp) == len(toks):
            candidates.append(mp)
    if len(toks) == 1:
        num = toks[0][0]

        def ok(v, v0):
            if fills is None:
                return 0 < abs(v - v0) <= 0.5 * v0
            ml = parse_typed_net(src.replace(num, f"{v:g}", 1), app.beverage_type)
            return ml is not None and 0 < abs(ml - (expected_ml or 0))

        opts = digit_options(num, ok)
        std = [o for o in opts if fills and parse_typed_net(src.replace(num, o[1], 1), app.beverage_type)
               and any(abs(parse_typed_net(src.replace(num, o[1], 1), app.beverage_type) - f) < 1 for f in fills)]
        candidates += [{num: new} for _, new in std + [o for o in opts if o not in std]]
    for mp in candidates:
        new_text = src
        for a, b in mp.items():
            new_text = re.sub(rf"(?<![\d.,]){re.escape(a)}(?![\d])", b, new_text, count=1)
        res = check_net_contents(app, [new_text])
        if res.verdict in (Verdict.FAIL, Verdict.CHECK) and res.code == "NET_CONTENTS_MISMATCH":
            return {"found": found, "map": mp, "from": src, "to": new_text,
                    "expected": {"overall": res.verdict.value, "findings": [res.code]}}, None
    return None, "no one-digit change gives a clearly different size"


def apply_number(plan_hits, num, new):
    """Change every reading of `num` (in the words found) to `new`, digit by digit."""
    done = 0
    for p, w, start in plan_hits:
        subs = {}
        chars = [c for c in w.text if not c.isspace()]
        offset = len([c for c in w.text[:start] if not c.isspace()])
        for j, (a, b) in enumerate(zip(num, new)):
            if a != b:
                subs[offset + j] = b
        if any(chars[i] != num[i - offset] for i in subs):
            return f'reader text "{w.text}" does not line up'
        err = replace_chars(p, w, subs)
        if err:
            return err
        done += 1
    return None if done else "nothing changed"


def find_words(pics, word, after=None, before=None, only_warning=False):
    """Words equal to `word` (case and trailing punctuation ignored), optionally preceded/followed by given words."""
    out = []
    for p in pics:
        for w in p.words:
            if re.sub(r"[^a-z0-9']", "", w.text.lower()) != word:
                continue
            line = p.line_of(w)
            i = line.index(w) if w in line else -1
            prev = re.sub(r"[^a-z]", "", line[i - 1].text.lower()) if i > 0 else None
            nxt = re.sub(r"[^a-z]", "", line[i + 1].text.lower()) if 0 <= i < len(line) - 1 else None
            if after and prev not in (None, after):
                continue
            if before and nxt not in (None, before):
                continue
            out.append((p, w))
    dedup = []
    for p, w in sorted(out, key=lambda h: -h[1].conf):
        if not any(q is p and _iou(w.box, v.box) > 0.3 for q, v in dedup):
            dedup.append((p, w))
    return dedup


def case_like(src, new):
    if src.isupper():
        return new.upper()
    if src[:1].isupper():
        return new[:1].upper() + new[1:]
    return new


CONTEXT = {"may": ("and", "cause"), "should": ("women", "not"), "impairs": ("beverages", "your"),
           "not": ("should", "drink"), "health": ("cause", "problems"), "birth": ("of", "defects"),
           "alcoholic": ("drink", "beverages")}


def make_change(change, rec, gt, app, pics, variant):
    """Edit the pictures in place; -> (provenance from/to, expected, check spec) or raises Skip."""
    if change in ("abv", "proof"):
        plan, why = plan_abv(gt, app, pics, change)
        if not plan:
            raise Skip(why)
        err = apply_number(plan["hits"], plan["num"], plan["new"])
        if err:
            raise Skip(err)
        check = ("proof", float(plan["num"]), float(plan["new"])) if change == "proof" else \
            ("abv", float(plan["num"].replace(",", ".")), float(plan["new"].replace(",", ".")))
        return plan["from"], plan["to"], plan["expected"], check
    if change == "net":
        plan, why = plan_net(gt, app, pics)
        if not plan:
            raise Skip(why)
        for num, hits in plan["found"]:
            err = apply_number(hits, num, plan["map"][num])
            if err:
                raise Skip(err)
        old_ml = parse_typed_net(plan["from"], app.beverage_type)
        new_ml = parse_typed_net(plan["to"], app.beverage_type)
        return plan["from"], plan["to"], plan["expected"], ("net", old_ml, new_ml)
    if not gt["warning"].get("present"):
        if change.startswith("warning"):
            raise Skip("no warning on this label")
    if change == "warning_word":
        for k in range(len(WORD_SWAPS)):
            old, new, phrase = WORD_SWAPS[(variant + k) % len(WORD_SWAPS)]
            hits = find_words(pics, old, *CONTEXT[old])
            if len(hits) == 1:
                p, w = hits[0]
                err, _ = replace_word(p, w, case_like(re.sub(r"[^A-Za-z]", "", w.text), new), close=True)
                if err:
                    raise Skip(err)
                return old, new, {"overall": "fail", "findings": ["WARNING_TEXT_ALTERED"]}, ("phrase", phrase)
        raise Skip("the warning words to change were not found by the reader")
    if change == "warning_delete":
        for k in range(len(DELETIONS)):
            old, phrase = DELETIONS[(variant + k) % len(DELETIONS)]
            hits = find_words(pics, old, *CONTEXT[old])
            if len(hits) == 1:
                p, w = hits[0]
                err = delete_word(p, w)
                if err:
                    raise Skip(err)
                return old, "", {"overall": "fail", "findings": ["WARNING_TEXT_ALTERED"]}, ("phrase", phrase)
        raise Skip("the warning words to delete were not found by the reader")
    if change == "warning_titlecase":
        gov = find_words(pics, "government", before="warning")
        if len(gov) != 1:
            raise Skip("the warning heading was not found by the reader")
        p, w = gov[0]
        line = p.line_of(w)
        i = line.index(w)
        if i + 1 >= len(line) or not line[i + 1].text.upper().startswith("WARNING"):
            raise Skip("the warning heading words were not found together")
        w2 = line[i + 1]
        tail = w2.text[len("WARNING"):]
        _, g1 = p.word_ink(w)
        _, g2 = p.word_ink(w2)
        if not g1 or not g2:
            raise Skip("heading words not found")
        space = bbox(g2)[0] - bbox(g1)[2]
        old_end = bbox(g2)[2]
        err, end = replace_word(p, w, "Government", keep_first=True)
        if err:
            raise Skip(err)
        # "Warning:" one space after the narrower "Government", and the rest of the line closed up behind it
        err, end2 = replace_word(p, w2, "Warning" + tail, keep_first=True, x_start=end + space)
        if err:
            raise Skip(err)
        err = close_up(p, w2, old_end, end2)
        if err:
            raise Skip(err)
        return "GOVERNMENT WARNING", "Government Warning", {"overall": "fail", "findings": ["WARNING_NOT_CAPS"]}, \
            ("titlecase", None)
    if change == "brand_number":
        nums = number_tokens(gt["brand_name"])
        if not nums:
            raise Skip("no number in the brand name")
        num = nums[0][0]
        rest = re.sub(r"[^a-z ]", "", gt["brand_name"].lower()).split()
        hits = find_number_words(pics, num, "|".join(re.escape(r) for r in rest[:2]) or ".")
        if not hits:
            raise Skip(f'the reader did not find "{num}" in the brand')
        for i, new in digit_options(num, lambda v, v0: 0 < abs(v - v0)):
            new_brand = gt["brand_name"].replace(num, new, 1)
            res = match_text("brand_name", gt["brand_name"], [new_brand])
            if res.code == "BRAND_NAME_NUMBER_DIFFERS":
                err = apply_number(hits, num, new)
                if err:
                    raise Skip(err)
                return gt["brand_name"], new_brand, {"overall": res.verdict.value, "findings": [res.code]}, \
                    ("brand", new_brand)
        raise Skip("no clear one-digit change")
    if change == "brand_word":
        words = re.sub(r"[^a-z' ]", " ", gt["brand_name"].lower()).split()
        if len(words) < 2:
            raise Skip("one-word brand")
        for bw in sorted(words, key=lambda x: -len(x)):
            if bw not in BRAND_SWAPS:
                continue
            hits = find_words(pics, bw)
            if not hits:
                continue
            new = BRAND_SWAPS[bw]
            new_brand = re.sub(rf"\b{re.escape(bw)}\b", lambda m: case_like(m.group(0), new), gt["brand_name"],
                               count=1, flags=re.I)
            res = match_text("brand_name", gt["brand_name"], [new_brand])
            if res.verdict == Verdict.PASS:
                continue
            for p, w in hits:
                err, _ = replace_word(p, w, case_like(re.sub(r"[^A-Za-z]", "", w.text), new), close=True)
                if err:
                    raise Skip(err)
            return gt["brand_name"], new_brand, {"overall": res.verdict.value, "findings": [res.code]}, \
                ("brand", new_brand)
        raise Skip("no brand word found by the reader that has a swap")
    raise Skip(f"unknown change {change}")


class Skip(Exception):
    pass


# ---------------------------------------------------------------- verification: is the planted text read?
def squash(t):
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9%. ]", " ", t.lower())).strip()


def verify_reading(check, gt, app, reading):
    texts = [r.text for r in reading.readings]
    lines = reading.lines()
    kind = check[0]
    if kind == "abv":
        vals = {round(r.value, 2) for t in texts for r in find_abv(" ".join(t.splitlines()))}
        if round(check[2], 2) not in vals:
            return "the new alcohol content is not read"
        if round(check[1], 2) in vals:
            return "the original alcohol content is still read on the label"
    elif kind == "proof":
        vals = {p for t in texts for p in find_proof(" ".join(t.splitlines()))}
        if check[2] not in vals:
            return "the new proof is not read"
        if check[1] in vals:
            return "the original proof is still read on the label"
    elif kind == "net":
        mls = [a.ml for t in texts for a in find_amounts(" ".join(t.splitlines()))]
        if not any(abs(m - check[2]) <= max(1.5, 0.004 * check[2]) for m in mls):
            return "the new net contents are not read"
        if any(abs(m - check[1]) <= max(1.5, 0.004 * check[1]) for m in mls):
            return "the original net contents are still read on the label"
    elif kind == "phrase":
        if not any(check[1] in squash(t) for t in texts):
            return f'"{check[1]}" is not read'
    elif kind == "titlecase":
        if not any(re.search(r"Gov[a-z]{4,}t", t) or re.search(r"Warn[a-z]{2,}", t) for t in texts):
            return "the title-case heading is not read"
    elif kind == "brand":
        if match_text("brand_name", check[1], lines).verdict != Verdict.PASS and \
                normalize(check[1]).replace(" ", "") not in normalize(" ".join(lines)).replace(" ", ""):
            return "the new brand name is not read"
        if match_text("brand_name", gt["brand_name"], lines).verdict == Verdict.PASS:
            return "the original brand name is still read on the label"
    return None


# ---------------------------------------------------------------- driver
def load_label(reader, lid):
    folder = DATA / "cola_samples" / lid
    rec = json.loads((folder / "record.json").read_text())
    gt = json.loads((DATA / "ground_truth" / f"{lid}.json").read_text())
    images = [(im["file"], (folder / im["file"]).read_bytes()) for im in rec["images"]]
    ar = reader.read(images)
    pics = []
    for i, (name, data) in enumerate(images):
        k = ar.turns[i] // 90
        full = np.ascontiguousarray(np.rot90(ar.pictures[i].full, k))
        frame = ar.frames[i]
        s = full.shape[0] / frame.shape[0]
        hi = reader.eng.read(frame, 1536).words
        # both readings are kept (each reads some words better); a word's line is taken from its own reading
        words = [Word(t, c, tuple(v * s for v in b), "hi") for t, c, b in hi if t.strip()]
        words += [Word(t, c, tuple(v * s for v in b), "main") for t, c, b in ar.frame_words[i] if t.strip()]
        pics.append(Pic(name, data, full, k, words))
    return rec, gt, images, pics


def encode(pic):
    img = Image.fromarray(np.ascontiguousarray(np.rot90(pic.img, -pic.k)))
    b = io.BytesIO()
    if pic.name.lower().endswith((".jpg", ".jpeg")):
        img.save(b, "JPEG", quality=95)
    else:
        img.save(b, "PNG")
    return b.getvalue()


def preview(pics):
    tiles = []
    for p in pics:
        for (x0, y0, x1, y1) in p.changed[:3]:
            h = y1 - y0
            m = int(max(12, 1.5 * h))
            H, W = p.img.shape[:2]
            X0, Y0, X1, Y1 = max(0, x0 - 4 * m), max(0, y0 - m), min(W, x1 + 4 * m), min(H, y1 + m)
            a, b = p.orig[Y0:Y1, X0:X1], p.img[Y0:Y1, X0:X1]
            scale = max(1.0, 90 / max(1, Y1 - Y0))
            sz = (round((X1 - X0) * scale), round((Y1 - Y0) * scale))
            a, b = cv2.resize(a, sz), cv2.resize(b, sz)
            sep = np.full((sz[1], 8, 3), 255, np.uint8)
            sep[:, 3:5] = (200, 0, 0)
            tiles.append(np.concatenate([a, sep, b], 1))
    if not tiles:
        return None
    w = max(t.shape[1] for t in tiles)
    rows = [np.pad(t, ((0, 10), (0, w - t.shape[1]), (0, 0)), constant_values=255) for t in tiles]
    img = Image.fromarray(np.concatenate(rows, 0))
    if img.width > 1600:
        img = img.resize((1600, round(img.height * 1600 / img.width)))
    b = io.BytesIO()
    img.save(b, "PNG")
    return b.getvalue()


def restage(stage, reader):
    """Rows of every item made earlier: from stage/made.json, or rebuilt from the last report and the staged folders
    (kept items are copied back into the stage first, so a re-pick can choose among all of them)."""
    if (stage / "made.json").exists():
        d = json.loads((stage / "made.json").read_text())
        return d["made"], d["skipped"], d["dropped"]
    rep = json.loads((OUT / "report.json").read_text())
    for r in rep["kept"]:
        if not (stage / r["id"]).exists():
            shutil.copytree(OUT / r["id"], stage / r["id"])
    made = list(rep["kept"])
    for iid in rep["made_but_left_out_for_balance"]:
        it = json.loads((stage / iid / "item.json").read_text())
        pv = it["provenance"]
        made.append({"id": iid, "base": pv["base_id"][5:], "change": pv["change"],
                     "type": it["application"]["beverage_type"], "from": pv["from"], "to": pv["to"],
                     "expected": it["expected"], "app_overall": None, "app_fields": None,
                     "edited": it["source"]["edited_images"]})
    return made, rep["skipped"], rep["dropped_unreadable"]


def check_spare(row, folder, reader):
    it = json.loads((folder / "item.json").read_text())
    a = it["application"]
    app = Application(a["beverage_type"], a["brand_name"], a.get("class_type"), a.get("abv"), a.get("net_contents"),
                      a.get("name_address"), a.get("source", "domestic"), a.get("country_of_origin"))
    res = check_application(reader, app, [(im["file"], (folder / im["file"]).read_bytes()) for im in it["images"]])
    row["app_overall"] = res.overall.value
    row["app_fields"] = {f.field: [f.verdict.value, f.code] for f in res.fields}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--set", default="dev", choices=["dev", "extra"])
    ap.add_argument("--target", type=int, default=0, help="items to keep (default 100 for dev, 80 for extra)")
    ap.add_argument("--only", default="")
    ap.add_argument("--changes", default=",".join(CHANGES))
    ap.add_argument("--cpus", type=int, default=4)
    ap.add_argument("--reselect", action="store_true", help="only re-pick the kept items from the staged ones")
    args = ap.parse_args()
    split = json.loads((DATA / "splits" / "split.json").read_text())
    held = set(split["heldout"])
    global OUT
    if args.set == "extra":
        pool = json.loads((DATA / "splits" / "practice_extra.json").read_text())["dev"]
        OUT = DATA / "tampered_extra"
    else:
        pool = split["dev"]
    args.target = args.target or (80 if args.set == "extra" else 100)
    ids = sorted(x[5:] for x in pool if x.startswith("cola_") and x not in held)
    if args.only:
        ids = [i for i in ids if i in args.only.split(",")]
    changes = args.changes.split(",")
    reader = Reader(cpus=args.cpus)
    reader.warm_up()
    stage = ROOT / "out" / f"tampered_stage_{args.set}"
    made, skipped, dropped = [], [], []
    if args.reselect:
        made, skipped, dropped = restage(stage, reader)
        ids = []
    else:
        shutil.rmtree(stage, ignore_errors=True)
        stage.mkdir(parents=True)
    for n, lid in enumerate(ids, 1):
        rec, gt, images, pics0 = load_label(reader, lid)
        app = application_of(rec, gt)
        for v, change in enumerate(changes):
            pics = [Pic(p.name, p.data, p.orig, p.k, p.words) for p in pics0]
            iid = f"cola_{lid}__{change}"
            try:
                frm, to, expected, check = make_change(change, rec, gt, app, pics, n + v)
            except Skip as e:
                skipped.append({"id": iid, "why": str(e)})
                continue
            except Exception as e:  # a layout the edit code does not handle: skip the label for this change
                skipped.append({"id": iid, "why": f"edit failed: {type(e).__name__}: {e}"})
                continue
            new_images = [(p.name, encode(p) if p.changed else p.data) for p in pics]
            res = check_application(reader, app, new_images)
            why = verify_reading(check, gt, app, res.reading)
            verdicts = {f.field: [f.verdict.value, f.code] for f in res.fields}
            row = {"id": iid, "base": lid, "change": change, "type": app.beverage_type, "from": frm, "to": to,
                   "expected": expected, "app_overall": res.overall.value, "app_fields": verdicts,
                   "edited": [p.name for p in pics if p.changed]}
            print(f"[{n}/{len(ids)}] {iid}: {frm!r} -> {to!r} " + (f"DROPPED ({why})" if why else
                  f"ok, app says {res.overall.value} {[(k, v) for k, v in verdicts.items() if v[0] != 'pass']}"),
                  flush=True)
            if why:
                row["why"] = why
                dropped.append(row)
                continue
            d = stage / iid
            d.mkdir()
            for name, data in new_images:
                (d / name).write_bytes(data)
            pv = preview(pics)
            if pv:
                (d / "preview.png").write_bytes(pv)
            item = {
                "id": iid,
                "images": [{k: im[k] for k in ("file", "image_type", "width_in", "height_in") if k in im}
                           for im in rec["images"]],
                "source": {"type": "tampered", "license": "TTB Public COLA Registry image (public record), with one "
                                                          "change planted for testing by tools/make_tampered.py",
                           "ttb_id": lid, "edited_images": row["edited"]},
                "application": {"beverage_type": app.beverage_type, "brand_name": app.brand_name,
                                "class_type": app.class_type, "abv": app.abv, "proof": gt.get("proof"),
                                "net_contents": app.net_contents, "source": app.source,
                                "country_of_origin": app.country_of_origin, "name_address": app.name_address,
                                "label_width_in": rec["images"][0].get("width_in")},
                "printed": {"brand_name": to if change.startswith("brand") else gt["brand_name"],
                            "class_type": gt.get("class_type"),
                            "abv": float(check[2]) if change == "abv" else gt.get("abv"),
                            "proof": float(check[2]) if change == "proof" else gt.get("proof"),
                            "net_contents": to if change == "net" else gt.get("net_contents_text"),
                            "warning_text": gt["warning"].get("text_as_printed"),
                            "warning_heading_bold": gt["warning"].get("heading_looks_bold") == "yes",
                            "warning_cap_mm": None},
                "expected": expected,
                "provenance": {"base_id": f"cola_{lid}", "change": change, "from": frm, "to": to},
            }
            (d / "item.json").write_text(json.dumps(item, indent=2, ensure_ascii=False))
            made.append(row)

    if not args.reselect:
        (stage / "made.json").write_text(json.dumps({"made": made, "skipped": skipped, "dropped": dropped},
                                                    ensure_ascii=False))
    # keep about --target items, balanced across change types and labels; never a rejected one
    by_change = defaultdict(list)
    for r in made:
        if r["id"] not in REJECTED:
            by_change[r["change"]].append(r)
    picked, per_label = [], Counter()
    while len(picked) < args.target and any(by_change.values()):
        for ch in changes:
            pool = sorted(by_change[ch], key=lambda r: per_label[r["base"]])
            if pool and len(picked) < args.target:
                r = pool[0]
                by_change[ch].remove(r)
                picked.append(r)
                per_label[r["base"]] += 1
    left_out = [r["id"] for rs in by_change.values() for r in rs]
    if not args.only:
        shutil.rmtree(OUT, ignore_errors=True)
    OUT.mkdir(parents=True, exist_ok=True)
    for r in picked:
        if r.get("app_overall") is None:  # a spare that was never checked by the app (older stage): check it now
            check_spare(r, stage / r["id"], reader)
        shutil.rmtree(OUT / r["id"], ignore_errors=True)
        shutil.copytree(stage / r["id"], OUT / r["id"])
    with open(OUT / "manifest.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["id", "beverage_type", "base_id", "change", "from", "to", "expected",
                                          "finding", "app_overall"])
        w.writeheader()
        for r in sorted(picked, key=lambda r: r["id"]):
            w.writerow({"id": r["id"], "beverage_type": r["type"], "base_id": f"cola_{r['base']}", "change": r["change"],
                        "from": r["from"], "to": r["to"], "expected": r["expected"]["overall"],
                        "finding": " ".join(r["expected"]["findings"]), "app_overall": r["app_overall"]})
    report = {"kept": sorted(picked, key=lambda r: r["id"]), "dropped_unreadable": dropped, "skipped": skipped,
              "made_but_left_out_for_balance": left_out,
              "rejected_on_review": {i: why for i, why in REJECTED.items() if any(r["id"] == i for r in made)}}
    (OUT / "report.json").write_text(json.dumps(report, indent=1, ensure_ascii=False))
    print(f"\nkept {len(picked)} (made {len(made)}, left out for balance {len(left_out)}), "
          f"dropped {len(dropped)} (planted text not read), skipped {len(skipped)}")
    print("per change:", dict(Counter(r["change"] for r in picked)))
    print("per type:", dict(Counter(r["type"] for r in picked)))


if __name__ == "__main__":
    main()
