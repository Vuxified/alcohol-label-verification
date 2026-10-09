"""Fine-tune the word reader on label words, then export it for the app (ONNX, same shape as the stock model).

The word reader is OnnxTR's crnn_mobilenet_v3_small; the same network with the same weights exists in docTR
(PyTorch), so it is trained there and exported back. Training words come from three places:
  1. real word pictures cut from the 64 practice labels and their tampered copies (tools/make_reader_data.py),
  2. damaged copies of those (blur, low resolution, JPEG, noise, black-and-white, inverted, slight turn),
  3. words drawn in many fonts: label words, the warning, numbers and units, and MISSPELLED words and random
     letters, so the reader learns to read letters as printed instead of guessing a familiar word.
Checks before and after: real words from 1 in 6 practice labels, never trained on, the same damaged, and drawn words in
fonts not trained on (correct and misspelled). The newer practice labels and the final test are never used here;
tools/evaluate.py measures the app with the new reader on those.

Setup (separate from the app):  python3.12 -m venv .venv-train && .venv-train/bin/pip install -r requirements-train.txt
Usage: .venv-train/bin/python tools/train_reader.py [--epochs 8]   -> out/reader_train/words.onnx + report.json
"""

import argparse
import hashlib
import json
import multiprocessing
import os
import random
import re
import string
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
import torch
from doctr.models import crnn_mobilenet_v3_small
from doctr.models.utils import export_model_to_onnx
from onnxtr.models.preprocessor import PreProcessor
from onnxtr.models.recognition.models.crnn import default_cfgs
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
OUT = ROOT / "out" / "reader_train"
CFG = default_cfgs["crnn_mobilenet_v3_small"]
VOCAB = CFG["vocab"]
PRE = PreProcessor(CFG["input_shape"][1:], batch_size=4096, mean=CFG["mean"], std=CFG["std"], preserve_aspect_ratio=True)

SYS = Path(os.environ.get("MAC_FONTS", "/System/Library/Fonts"))  # macOS fonts (copied alongside on a training server)
FONTS = sorted(str(p) for p in (ROOT / "tools" / "fonts").glob("*.tt[fc]")) + [str(SYS / "Supplemental" / f) for f in (
    "Arial.ttf", "Arial Bold.ttf", "Arial Narrow.ttf", "Arial Black.ttf", "Georgia.ttf", "Georgia Bold Italic.ttf",
    "Times New Roman.ttf", "Times New Roman Bold.ttf", "Courier New.ttf", "Courier New Bold.ttf", "Impact.ttf",
    "Trebuchet MS.ttf", "Verdana Bold.ttf", "Tahoma.ttf", "Baskerville.ttc", "Futura.ttc", "GillSans.ttc",
    "AmericanTypewriter.ttc", "Cochin.ttc", "Bodoni 72.ttc", "Brush Script.ttf", "Chalkduster.ttf", "Herculanum.ttf",
    "Papyrus.ttc", "Trattatello.ttf", "Skia.ttf")] + [str(SYS / f) for f in ("Helvetica.ttc", "Avenir Next Condensed.ttc",
                                                                             "Palatino.ttc", "MarkerFelt.ttc")]
CHECK_FONTS = [str(SYS / "Supplemental" / f) for f in ("Didot.ttc", "Rockwell.ttc", "Copperplate.ttc", "Hoefler Text.ttc",
                                                        "Verdana.ttf")] + [str(SYS / "Optima.ttc")]
WARNING = ("GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during "
           "pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability "
           "to drive a car or operate machinery, and may cause health problems.")
NUMBERS = ["ALC.", "ALC", "VOL.", "VOL", "ALC/VOL", "ALC./VOL.", "Alc.", "Vol.", "BY", "PROOF", "Proof", "mL", "ML", "ml",
           "L", "LITER", "LITERS", "FL.", "FL", "OZ.", "OZ", "FL.OZ.", "PINT", "PINTS", "GALLONS", "YEAR", "YEARS", "OLD",
           "AGED", "NET", "CONTENTS", "NET CONTENTS:", "CONTAINS", "SULFITES", "PRODUCT", "OF", "IMPORTED", "BOTTLED"]


def base_of(label):
    return label[5:].split("__")[0] if label.startswith("cola_") else label


def checked_label(base):
    """1 in 6 practice labels are kept out of training to check on (chosen by a fixed hash, not by look)."""
    return int(hashlib.sha1(base.encode()).hexdigest(), 16) % 6 == 0


def in_vocab(word):
    return bool(word) and all(c in VOCAB for c in word) and len(word) <= 24


def misspell(word, rng):
    """One planted typo: a changed, dropped, added or swapped letter (kept in the word's capitals)."""
    letters = string.ascii_uppercase if word.isupper() else string.ascii_lowercase
    i = rng.randrange(len(word))
    k = rng.randrange(4)
    if k == 0:
        out = word[:i] + rng.choice(letters.replace(word[i], "")) + word[i + 1:]
    elif k == 1 and len(word) > 3:
        out = word[:i] + word[i + 1:]
    elif k == 2:
        out = word[:i] + rng.choice(letters) + word[i:]
    else:
        i = min(i, len(word) - 2)
        out = word[:i] + word[i + 1] + word[i] + word[i + 2:]
    return out if out != word else misspell(word, rng)


def number(rng):
    a = rng.choice([4.2, 5, 5.5, 7.5, 9, 11.5, 12, 12.5, 13.5, 14, 14.5, 15, 40, 43, 45, 47.5, 50, 57])
    a = round(a + rng.choice([0, 0, 0.1, -0.1, 0.5, 1, -1, 2]), 1)
    return rng.choice([f"{a}%", f"{a}%", f"{a:g}%", f"{a}", f"{a:g}% ALC/VOL", f"{round(a * 2):d}", f"({round(a * 2):d}",
                       f"{rng.choice([187, 200, 355, 375, 473, 500, 650, 700, 750, 1000, 1750])}",
                       f"{rng.choice([187, 355, 375, 750])}mL", f"{rng.choice([1, 1.5, 1.75, 3])}L",
                       f"{rng.choice([8.4, 11.2, 12, 16, 16.9, 19.2, 22, 24, 25.4, 32])}", str(rng.randrange(1990, 2027)),
                       str(rng.randrange(2, 30)), str(rng.randrange(10, 999))])


def word_list(bases):
    """Words that appear on the training labels, with their capitals as printed where known."""
    words = set(WARNING.split()) | set(WARNING.upper().split()) | set(NUMBERS)
    for b in bases:
        gt = json.loads((DATA / "ground_truth" / f"{b}.json").read_text())
        for k in ("brand_name", "class_type", "abv_text", "net_contents_text", "name_address_text", "country_of_origin_text"):
            words |= set((gt.get(k) or "").split())
        words |= set((gt["warning"].get("text_as_printed") or "").split())
    return sorted(w for w in words if in_vocab(w))


def text_for(words, rng):
    """What to draw: a label word (40%), a misspelled one (25%), a number (20%) or random characters (15%)."""
    r = rng.random()
    if r < 0.40:
        w = rng.choice(words)
    elif r < 0.65:
        w = misspell(rng.choice([w for w in words if sum(c.isalpha() for c in w) >= 3] or ["WARNING"]), rng)
    elif r < 0.85:
        w = number(rng)
    else:
        pool = rng.choice([string.ascii_uppercase, string.ascii_lowercase, string.ascii_letters + string.digits,
                           string.ascii_uppercase + string.digits + "%.,-/()"])
        w = "".join(rng.choice(pool) for _ in range(rng.randrange(2, 10)))
    c = rng.random()
    if c < 0.15:
        w = w.upper()
    elif c < 0.25:
        w = w.lower()
    elif c < 0.32:
        w = w.title()
    return w if in_vocab(w) else "WARNING"


def draw(text, font_path, rng):
    """A tight word picture, like the text finder's crop: ink on a plain, textured or shaded background."""
    size = rng.randrange(22, 72)
    try:
        font = ImageFont.truetype(font_path, size)
    except OSError:
        font = ImageFont.truetype(FONTS[0], size)
    ink = rng.randrange(0, 90)
    paper = rng.randrange(150, 256)
    if rng.random() < 0.3:
        ink, paper = paper, ink  # light text on dark
    tint = np.array([rng.randrange(-40, 41) for _ in range(3)])
    stroke = 1 if rng.random() < 0.15 else 0
    x0, y0, x1, y1 = font.getbbox(text, stroke_width=stroke)
    pad = [int(size * rng.uniform(0.02, 0.25)) for _ in range(4)]
    w, h = x1 - x0 + pad[0] + pad[2], y1 - y0 + pad[1] + pad[3]
    img = Image.new("L", (max(w, 4), max(h, 4)), paper)
    ImageDraw.Draw(img).text((pad[0] - x0, pad[1] - y0), text, fill=ink, font=font, stroke_width=stroke, stroke_fill=ink)
    a = np.asarray(img).astype(np.float32)
    if rng.random() < 0.5:  # shading or paper texture
        a += np.linspace(rng.uniform(-30, 30), rng.uniform(-30, 30), a.shape[1])[None, :]
        a += np.random.default_rng(rng.randrange(1 << 30)).normal(0, rng.uniform(0, 8), a.shape)
    rgb = np.clip(a[..., None] + tint[None, None, :], 0, 255).astype(np.uint8)
    return rgb


def damage(img, rng):
    """Turn a clean word picture into one like a photo, a small print, a scan or the app's black-and-white re-read."""
    h, w = img.shape[:2]
    if rng.random() < 0.3:  # slight turn or slant
        m = cv2.getRotationMatrix2D((w / 2, h / 2), rng.uniform(-3, 3), 1.0)
        m[0, 1] += rng.uniform(-0.15, 0.15)
        img = cv2.warpAffine(img, m, (w, h), borderMode=cv2.BORDER_REPLICATE)
    if rng.random() < 0.3:  # a little more margin, as a looser box would give
        p = [rng.randrange(0, max(1, h // 4)) for _ in range(4)]
        img = cv2.copyMakeBorder(img, p[0], p[1], p[2], p[3], cv2.BORDER_REPLICATE)
    if rng.random() < 0.4:  # low resolution
        th = rng.randrange(9, 24)
        if th < img.shape[0]:
            s = th / img.shape[0]
            small = cv2.resize(img, (max(2, round(img.shape[1] * s)), th), interpolation=cv2.INTER_AREA)
            img = cv2.resize(small, (img.shape[1], img.shape[0]), interpolation=rng.choice([cv2.INTER_LINEAR, cv2.INTER_CUBIC]))
    if rng.random() < 0.3:
        img = cv2.GaussianBlur(img, (0, 0), rng.uniform(0.4, 1.4))
    if rng.random() < 0.3:  # contrast and brightness
        img = np.clip(img.astype(np.float32) * rng.uniform(0.5, 1.3) + rng.uniform(-40, 40), 0, 255).astype(np.uint8)
    if rng.random() < 0.25:
        img = np.clip(img + np.random.default_rng(rng.randrange(1 << 30)).normal(0, rng.uniform(3, 14), img.shape),
                      0, 255).astype(np.uint8)
    if rng.random() < 0.3:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, rng.randrange(15, 70)])
        img = cv2.imdecode(buf, cv2.IMREAD_UNCHANGED)
        img = img if img.ndim == 3 else cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)
    r = rng.random()
    if r < 0.12:  # the zoom re-read's black-and-white versions (app/ocr/zoom.py binarize)
        g = cv2.cvtColor(img, cv2.COLOR_RGB2GRAY)
        if np.median(g) < 110:
            g = 255 - g
        if rng.random() < 0.5:
            _, g = cv2.threshold(g, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        else:
            g = cv2.adaptiveThreshold(cv2.GaussianBlur(g, (3, 3), 0), 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                      cv2.THRESH_BINARY, 31, 10)
        img = cv2.cvtColor(g, cv2.COLOR_GRAY2RGB)
    elif r < 0.2:  # the inverted pass
        img = 255 - img
    return np.ascontiguousarray(img)


REAL, WORDS = [], []  # set before the drawing workers start, which inherit them


def make(job):
    """One training picture: a real word (often damaged), a real misread (always damaged), or a drawn word."""
    kind, i, seed = job
    rng = random.Random(seed)
    if kind == "real":
        im, t = REAL[i]
        return (damage(im, rng) if rng.random() < 0.7 else im), t
    if kind == "misread":
        im, t = REAL[i]
        return damage(im, rng), t
    t = text_for(WORDS, rng)
    im = draw(t, rng.choice(FONTS), rng)
    return (damage(im, rng) if rng.random() < 0.8 else im), t


def load(path):
    return cv2.cvtColor(cv2.imread(str(OUT / path)), cv2.COLOR_BGR2RGB)


def batches(samples, size):
    for i in range(0, len(samples), size):
        yield samples[i:i + size]


def tensor(imgs):
    """The app's own resize, padding and scaling (OnnxTR), turned from channels-last to the model's layout."""
    return torch.from_numpy(np.ascontiguousarray(np.concatenate(PRE(imgs), axis=0).transpose(0, 3, 1, 2)))


def same(read, true):
    """Right the way the app judges words: punctuation and capitals don't change a word ("ml" = "mL", "N.Y" = "N.Y.").
    The warning heading's capitals are checked on their own (heading_ok)."""
    return re.sub(r"\W", "", read).lower() == re.sub(r"\W", "", true).lower()


def reads(model, samples, device, conf=False):
    model.eval()
    out = []
    with torch.no_grad():
        for b in batches(samples, 512):
            out += model(tensor([im for im, _ in b]).to(device), return_preds=True)["preds"]
    return out if conf else [p for p, _ in out]


def pair(a, b):
    """The app's two-reader setup: for each word, the reading of whichever reader is more confident."""
    return [x[0] if x[1] >= y[1] else y[0] for x, y in zip(a, b)]


def accuracy(model, samples, device):
    return sum(same(p, t) for p, (_, t) in zip(reads(model, samples, device), samples)) / max(1, len(samples))


def heading_ok(preds, samples):
    """The warning heading read in the capitals it is printed in."""
    pairs = [(p, t) for p, (_, t) in zip(preds, samples) if re.sub(r"\W", "", t).upper() in ("GOVERNMENT", "WARNING")]
    return sum(re.sub(r"\W", "", p) == re.sub(r"\W", "", t) for p, t in pairs), len(pairs)


def onnx_accuracy(path, samples):
    sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
    from onnxtr.models.recognition.models.crnn import CRNNPostProcessor
    post = CRNNPostProcessor(VOCAB)
    right = 0
    for b in batches(samples, 512):
        logits = sess.run(None, {"input": tensor([im for im, _ in b]).numpy()})[0]
        right += sum(same(p, t) for (p, _), (_, t) in zip(post(logits), b))
    return right / max(1, len(samples))


def checks(rows, words, rng):
    """Fixed check sets, made once with their own random seed."""
    real = [(load(r["file"]), r["text"]) for r in rows if checked_label(base_of(r["label"]))]
    fixed = [(load(r["file"]), r["text"]) for r in rows if checked_label(base_of(r["label"])) and r["read"] != r["text"]]
    damaged = [(damage(im, rng), t) for im, t in real]
    drawn_ok, drawn_typo = [], []
    for _ in range(1500):
        w = rng.choice(words)
        drawn_ok.append((draw(w, rng.choice(CHECK_FONTS), rng), w))
        t = misspell(rng.choice([x for x in words if sum(c.isalpha() for c in x) >= 4]), rng)
        drawn_typo.append((draw(t, rng.choice(CHECK_FONTS), rng), t))
    return {"real words (labels not trained on)": real, "  of which the stock reader misread": fixed,
            "the same, damaged": damaged, "drawn words, new fonts": drawn_ok, "drawn MISSPELLED words, new fonts": drawn_typo}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=6)
    ap.add_argument("--lr", type=float, default=3e-5)
    ap.add_argument("--batch", type=int, default=128)
    ap.add_argument("--cap", type=int, default=2, help="at most this many pictures of one word from one label "
                    "(and its tampered copies), so the warning's repeated words don't crowd out the rest")
    ap.add_argument("--keep", type=float, default=1.0, help="weight of 'don't forget': stay close to the stock "
                    "reader's own reading of every training picture (0 = off)")
    ap.add_argument("--partner", action="store_true", help="judge rounds by the pair (stock + this reader, more "
                    "confident reading per word), as the app uses it")
    ap.add_argument("--device", default="cuda" if torch.cuda.is_available() else "cpu",
                    help="cuda or cpu (Apple's mps collapsed mid-training here)")
    args = ap.parse_args()
    random.seed(0)
    torch.manual_seed(0)
    rng = random.Random(0)
    device = args.device

    rows = [r for r in json.loads((OUT / "crops.json").read_text()) if in_vocab(r["text"])]
    train, seen = [], {}
    for r in rows:  # misreads always kept; other words capped per label
        if checked_label(base_of(r["label"])):
            continue
        key = (base_of(r["label"]), r["text"])
        seen[key] = seen.get(key, 0) + 1
        if r["read"] != r["text"] or seen[key] <= args.cap:
            train.append(r)
    bases = sorted({base_of(r["label"]) for r in train})
    words = word_list(bases)
    check = checks(rows, words, random.Random(12345))
    print(f"{len(train)} real training words from {len(bases)} labels ({sum(r['read'] != r['text'] for r in train)} "
          f"stock misreads); {len(words)} label words for drawing; device {device}")
    print("check sets:", {k: len(v) for k, v in check.items()})
    REAL.extend((load(r["file"]), r["text"]) for r in train)
    WORDS.extend(words)
    misread = [i for i, r in enumerate(train) if r["read"] != r["text"]]
    pool = multiprocessing.get_context("fork").Pool(max(1, os.cpu_count() - 1))

    model = crnn_mobilenet_v3_small(pretrained=True).to(device)
    teacher = crnn_mobilenet_v3_small(pretrained=True).to(device).eval()
    for q in teacher.parameters():
        q.requires_grad_(False)
    report = {"stock": {k: accuracy(model, v, device) for k, v in check.items()}}
    real_check = check["real words (labels not trained on)"]
    stock_conf = reads(model, real_check, device, conf=True)
    stock_reads = [p for p, _ in stock_conf]
    typo_check = check["drawn MISSPELLED words, new fonts"]
    stock_typo = reads(model, typo_check, device, conf=True)
    stock_ok = [same(p, t) for p, (_, t) in zip(stock_reads, real_check)]
    report["stock"]["warning heading in capitals"] = heading_ok(stock_reads, real_check)
    print("stock  ", report["stock"], flush=True)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    per_epoch = 3 * len(REAL) // 2  # two real words for every drawn one: drawn words teach, real words anchor
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, args.lr, total_steps=args.epochs * (per_epoch // args.batch + 1),
                                                pct_start=0.1)
    best, best_state = (0, 0.0), None
    for epoch in range(1, args.epochs + 1):
        model.train()
        for m in model.modules():  # keep the stock reader's brightness statistics: damaged training pictures would drift them
            if isinstance(m, torch.nn.BatchNorm2d):
                m.eval()
        jobs = [("real", i, rng.randrange(1 << 30)) for i in range(len(REAL))]
        jobs += [("misread", i, rng.randrange(1 << 30)) for i in misread * 4]  # the real misreads, seen more often
        jobs += [("drawn", 0, rng.randrange(1 << 30)) for _ in range(per_epoch - len(jobs))]
        samples = pool.map(make, jobs, chunksize=256)
        rng.shuffle(samples)
        total = 0.0
        for b in batches(samples, args.batch):
            x = tensor([im for im, _ in b]).to(device)
            out = model(x, target=[t for _, t in b], return_model_output=True)
            loss = out["loss"]
            if args.keep:  # don't forget: per character position, stay near what the stock reader would say
                with torch.no_grad():
                    ref = torch.softmax(teacher(x, return_model_output=True)["out_map"], -1)
                loss = loss + args.keep * torch.nn.functional.kl_div(torch.log_softmax(out["out_map"], -1), ref,
                                                                     reduction="batchmean") / ref.shape[1]
            opt.zero_grad()
            loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 5)
            opt.step()
            sched.step()
            total += loss.item() * len(b)
        scores = {k: accuracy(model, v, device) for k, v in check.items()}
        new_reads = reads(model, real_check, device, conf=True)
        if args.partner:
            new_reads = pair(stock_conf, new_reads)
            scores["drawn MISSPELLED words, new fonts"] = sum(
                same(p, t) for p, (_, t) in zip(pair(stock_typo, reads(model, typo_check, device, conf=True)), typo_check)
            ) / len(typo_check)
        else:
            new_reads = [p for p, _ in new_reads]
        new_ok = [same(p, t) for p, (_, t) in zip(new_reads, real_check)]
        scores["fixed"] = sum(n and not o for o, n in zip(stock_ok, new_ok))
        scores["broke"] = sum(o and not n for o, n in zip(stock_ok, new_ok))
        scores["warning heading in capitals"] = heading_ok(new_reads, real_check)
        report[f"epoch {epoch}"] = scores
        print(f"epoch {epoch} loss {total / len(samples):.3f}", scores, flush=True)
        # keep the epoch that fixes the most more held-back real words than it breaks, never reading the warning heading
        # or misspelled words worse than the stock reader
        score = (scores["fixed"] - scores["broke"], scores["the same, damaged"])
        if (scores["fixed"] > scores["broke"] and score > best
                and scores["warning heading in capitals"][0] >= report["stock"]["warning heading in capitals"][0]
                and scores["drawn MISSPELLED words, new fonts"] >= report["stock"]["drawn MISSPELLED words, new fonts"] - 0.002):
            best, best_state = score, {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
            report["kept"] = f"epoch {epoch}"
    if best_state is None:
        print("No epoch fixed more words than it broke without reading the heading or misspelled words worse: nothing exported.")
        (OUT / "report.json").write_text(json.dumps(report, indent=1))
        return
    export = crnn_mobilenet_v3_small(pretrained=False, exportable=True)
    export.load_state_dict(best_state)
    path = Path(export_model_to_onnx(export.eval(), str(OUT / "words"), dummy_input=torch.rand((1, 3, 32, 128))))
    report["onnx"] = {k: onnx_accuracy(path, v) for k, v in check.items()}
    print("kept", report["kept"], "exported", path, {k: f"{v:.3f}" for k, v in report["onnx"].items()})
    (OUT / "report.json").write_text(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
