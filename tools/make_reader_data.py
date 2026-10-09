"""Word pictures for training the word reader, cut from practice labels and named from their answer key.

The app's text finder marks every word on the 64 practice labels (data/splits/split.json "dev"), the 85 newest ones
(cola3, data/splits/practice_extra2.json) and the tampered copies of the first 64 (data/tampered); the stock word reader
reads each one. A word picture is kept
when its reading is close to exactly one word of what the label really says (the answer key, or for a tampered
copy the planted text). When the stock reader got it wrong, the picture is named with the true word only if
Tesseract, reading it on its own, agrees; so the lessons are real misreads, never guesses from a nearby word. The final-test
labels and cola2, with the tampered copies (tampered_extra) and photo scenes (scenes_real) made from it, are never
touched: they stay for measuring.

Writes out/reader_train/crops/<label>/<n>.png and out/reader_train/crops.json [{file, text, read, label}].
Usage: python tools/make_reader_data.py
"""

import json
import re
import sys
from pathlib import Path

import cv2
import numpy as np
from onnxtr.utils.geometry import extract_crops

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.ocr.engine import OnnxEngine, tesseract  # noqa: E402
from app.ocr.reader import decode  # noqa: E402

DATA = ROOT / "data"
OUT = ROOT / "out" / "reader_train"


def distance(a, b):
    row = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        prev, row[0] = row[0], i
        for j, cb in enumerate(b, 1):
            prev, row[j] = row[j], min(row[j] + 1, row[j - 1] + 1, prev + (ca != cb))
    return row[-1]


def allowed(n):
    return 1 if n <= 5 else 2 if n <= 10 else 3


def same_case_as(read, word):
    """The true letters, in the reading's capitals pattern; None when that pattern is unclear."""
    letters = [c for c in read if c.isalpha()]
    if not letters or all(c.isupper() for c in letters):
        return word.upper()
    if all(c.islower() for c in letters):
        return word.lower()
    if read[:1].isupper() and all(c.islower() for c in letters[1:]):
        return word[:1].upper() + word[1:].lower()
    return None


def true_word(read, exact, loose):
    """The one answer-key word this reading is close to, or None. Warning words keep their printed capitals;
    other fields' answer keys are not always in printed capitals, so those are compared ignoring capitals."""
    if len(read) < 2:
        return None
    best = sorted((distance(read, w), w, True) for w in exact)
    best += sorted((distance(read.lower(), w.lower()), w, False) for w in loose)
    best.sort(key=lambda x: x[0])
    if not best or best[0][0] > allowed(len(best[0][1])) or best[0][0] * 2 >= len(best[0][1]):
        return None
    if len(best) > 1 and best[1][0] == best[0][0] and best[1][1].lower() != best[0][1].lower():
        return None  # two different words fit equally well
    d, word, is_exact = best[0]
    if is_exact:
        return word
    if read.lower() == word.lower():
        return read
    return same_case_as(read, word)


NOISE = " '\"‘’“”=~|_—"
PUNCT = ".,;:-"


def confirmed(crop, read, word):
    """A misread becomes a lesson only when Tesseract, reading the same picture on its own, sees the true word, and
    the two differ in letters or digits inside the word (a box that cut or added letters at an edge, or a difference
    in punctuation only, is dropped: "ALC./VOL" must never be taught as "ALC/VOL")."""
    if read in word or word in read or re.sub(r"\W", "", read) == re.sub(r"\W", "", word):
        return False
    g = cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY)
    g = cv2.resize(g, None, fx=64 / g.shape[0], fy=64 / g.shape[0], interpolation=cv2.INTER_CUBIC)
    seen = tesseract(cv2.copyMakeBorder(g, 16, 16, 16, 16, cv2.BORDER_REPLICATE), 8).strip().strip(NOISE)
    return seen == word or (seen.strip(PUNCT) == word.strip(PUNCT) and seen.strip(PUNCT) != read.strip(PUNCT))


def words_of(text):
    return [w for w in (text or "").split() if len(w) >= 2]


def label_words(gt, change=None):
    """(exact, loose): the warning as printed, and the other fields' words."""
    loose = []
    for k in ("brand_name", "class_type", "abv_text", "net_contents_text", "name_address_text", "country_of_origin_text"):
        loose += words_of(gt.get(k))
    warning = gt["warning"].get("text_as_printed") or ""
    if change:  # a tampered copy: the planted text replaces the original wherever it was printed
        loose = words_of(" ".join(loose).replace(change["from"], change["to"]))
        warning = warning.replace(change["from"], change["to"])
        if change["from"] not in warning:
            loose += words_of(change["to"])
    return set(words_of(warning)), set(loose) - set(words_of(warning))


def items():
    dev = sorted(x[5:] for name in ("split", "practice_extra2") for x in json.loads((DATA / "splits" / f"{name}.json").read_text())["dev"]
                 if x.startswith("cola_"))
    for i in dev:
        gt = json.loads((DATA / "ground_truth" / f"{i}.json").read_text())
        rec = json.loads((DATA / "cola_samples" / i / "record.json").read_text())
        yield i, [DATA / "cola_samples" / i / im["file"] for im in rec["images"]], label_words(gt)
    for d in sorted((DATA / "tampered").iterdir()):
        if not (d / "item.json").exists():
            continue
        it = json.loads((d / "item.json").read_text())
        base = it["provenance"]["base_id"][5:]
        assert base in dev, f"{d.name} is not made from a practice label"
        gt = json.loads((DATA / "ground_truth" / f"{base}.json").read_text())
        if it["provenance"]["change"].startswith("warning"):
            exact, loose = label_words(gt)
            exact = set(words_of(it["printed"]["warning_text"]))
        else:
            exact, loose = label_words(gt, it["provenance"])
        edited = [d / f for f in it["source"]["edited_images"]]
        yield d.name, edited, (exact, loose)


def main():
    eng = OnnxEngine(pool=1, threads=4)
    rows, kept, seen = [], 0, 0
    for name, files, (exact, loose) in items():
        out = OUT / "crops" / name
        out.mkdir(parents=True, exist_ok=True)
        n = 0
        for f in files:
            pic = decode(f.read_bytes(), f.name)
            for img, size in ((pic.ocr, 768), (pic.full, 1280)):  # the main read, and a sharper zoom-like read
                h, w = img.shape[:2]
                boxes = eng.detect(img, size)
                if not boxes:
                    continue
                rel = np.array([[x0 / w, y0 / h, x1 / w, y1 / h] for x0, y0, x1, y1 in boxes], dtype=np.float32)
                crops = [c for c in extract_crops(img, rel) if min(c.shape[:2]) >= 6]
                crops = [c for c in crops if c.shape[1] / c.shape[0] <= 8]  # wider ones are split before reading
                for crop, (read, conf) in zip(crops, eng.recognise(crops)):
                    seen += 1
                    word = true_word(read, exact, loose)
                    if word is None or (word != read and not confirmed(crop, read, word)):
                        continue
                    n += 1
                    p = out / f"{n}.png"
                    cv2.imwrite(str(p), cv2.cvtColor(crop, cv2.COLOR_RGB2BGR))
                    rows.append({"file": str(p.relative_to(OUT)), "text": word, "read": read, "conf": round(conf, 3),
                                 "label": name})
        kept += n
        print(f"{name}: {n} words", flush=True)
    (OUT / "crops.json").write_text(json.dumps(rows, indent=0))
    wrong = sum(r["text"] != r["read"] for r in rows)
    print(f"kept {kept} of {seen} word pictures; {wrong} were misread by the stock reader")


if __name__ == "__main__":
    main()
