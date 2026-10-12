"""Read every image of one application within the time limit (docs/APPROACH.md).

Order of work (each extra pass runs only when its trigger fires):
  1. Main read: every image in parallel, OnnxTR at a 768-px aspect-fit detector input.
  2. Turn check: a picture turned sideways or upside down is turned back and read again (its first reading is
     kept too, so a wrong turn can never lose text).
  3. If the warning heading is still not found: a sideways read (a strip of tall text, or one 1280-px pass over
     the front picture) and an upside-down read; each one that finds the warning gets the zoom re-read.
  4. If the warning does not yet match: the zoom re-read of the warning paragraph (zoom.py), straightened.
  5. If brand, alcohol or net contents are not matched: Tesseract over each whole picture (1400 px); and for
     dark pictures (35%+ dark pixels) an inverted OnnxTR read.
Two clocks: passes for the other fields may start until 2.9 s and are dropped after 3.3 s; the warning passes
may start until 4.6 s and are dropped after 5.0 s. Whatever is dropped can only lead to "Please check".
"""

import io
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

import numpy as np
from PIL import Image, ImageOps

from app.verify.warning_judge import judge

from . import sideways, zoom
from .engine import OnnxEngine, Text, tesseract

os.environ.setdefault("OMP_THREAD_LIMIT", "1")
FIELDS_START, FIELDS_STOP = 2.9, 3.3
WARNING_START, WARNING_STOP = 4.6, 5.0
OCR_MAX_SIDE = 2000
TESS_FULL_SIDE = 1400
DARK_SHARE = 0.35


@dataclass
class Reading:
    """One text reading: which picture, which engine family ("onnx" / "tess"), which pass."""
    image: int
    family: str
    tag: str
    text: str
    words: list = field(default_factory=list)   # (text, conf, box px) in the frame of `frame`
    turn: int = 0                                # np.rot90 k applied to the picture before this reading


@dataclass
class Picture:
    name: str
    full: np.ndarray        # full resolution, EXIF-upright, RGB
    ocr: np.ndarray         # long side <= 2000 px
    dark_share: float


@dataclass
class ApplicationReading:
    pictures: list[Picture]
    readings: list[Reading]
    turns: list[int]
    frames: list = field(default_factory=list)       # each picture as finally read (turned upright), <= 2000 px
    frame_words: list = field(default_factory=list)  # the main reading's words, in frame pixels
    passes: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    timing: dict = field(default_factory=dict)
    seconds: float = 0.0

    def lines(self) -> list[str]:
        """All text, picture by picture, an empty line between pictures (the rules never join across pictures)."""
        out = []
        for i in range(len(self.pictures)):
            for r in self.readings:
                if r.image == i:
                    out.extend(r.text.splitlines())
            out.append("")
        return out

    def warning_readings(self):
        return [(r.family, r.text) for r in self.readings]


def _good_words(t: Text) -> int:
    """Words that look really read: 3+ letters, mostly letters, confidence 0.5+."""
    return sum(1 for w, c, _ in t.words if c >= 0.5 and len(w) >= 3 and sum(ch.isalpha() for ch in w) >= 0.7 * len(w))


def decode(data: bytes, name: str) -> Picture:
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(data)))
    if img.mode in ("RGBA", "LA", "P"):
        img = img.convert("RGBA")
        bg = Image.new("RGBA", img.size, "white")
        img = Image.alpha_composite(bg, img)
    img = img.convert("RGB")
    full = np.asarray(img)
    small = img.copy()
    small.thumbnail((OCR_MAX_SIDE, OCR_MAX_SIDE))
    g = np.asarray(img.convert("L").resize((256, 256))) / 255.0
    return Picture(name, full, np.asarray(small), float((g < DARK_SHARE).mean()))


class Reader:
    def __init__(self, cpus: int | None = None, threads: int = 2):
        self.cpus = cpus or max(2, min(8, os.cpu_count() or 4))
        self.threads = threads
        self.eng = OnnxEngine(pool=max(1, self.cpus // threads), threads=threads)
        self.ex = ThreadPoolExecutor(max_workers=16)
        self._cond = threading.Condition()
        self._free = [self.cpus]
        self._waiting = []
        self._seq = [0]
        self._local = threading.local()

    # ---- CPU tokens with priority: warning-chain work gets the CPU first (measured config "prio")
    def _limited(self, n, fn, *a):
        n = min(n, self.cpus)
        pr = getattr(self._local, "prio", 1)
        with self._cond:
            self._seq[0] += 1
            me = (pr, self._seq[0])
            self._waiting.append(me)
            self._cond.wait_for(lambda: self._free[0] >= n and min(self._waiting) == me)
            self._waiting.remove(me)
            self._free[0] -= n
            self._cond.notify_all()
        try:
            return fn(*a)
        finally:
            with self._cond:
                self._free[0] += n
                self._cond.notify_all()

    def _submit(self, clock, t0, prio, fn, *a):
        """Run fn on the executor unless its clock's start cut-off has passed by the time it gets CPU."""
        start = FIELDS_START if clock == "fields" else WARNING_START

        def run():
            self._local.prio = prio
            try:
                if time.perf_counter() - t0 > start:
                    return None
                return fn(*a)
            finally:
                self._local.prio = 1
        return self.ex.submit(run)

    def _onnx(self, img, size=768):
        return self._limited(self.threads, self.eng.read, img, size)

    def _tess(self, img, psm):
        return self._limited(1, tesseract, img, psm)

    def warm_up(self):
        """Load every predictor and Tesseract once (startup self-test)."""
        img = np.full((200, 600, 3), 255, np.uint8)
        list(self.ex.map(lambda _: self.eng.read(img), range(self.eng.q.qsize())))
        tesseract(img, 6)

    # ---- one application
    def read(self, images: list[tuple[str, bytes]], fields_ok=None) -> ApplicationReading:
        """images: [(name, bytes)]. fields_ok(lines) -> True when brand, alcohol and net contents all match
        (decides the whole-label Tesseract and inverted passes); None treats them as not matched."""
        t0 = time.perf_counter()
        pics = list(self.ex.map(lambda nb: decode(nb[1], nb[0]), images))
        arrs = [p.ocr for p in pics]
        fulls = [p.full for p in pics]
        mains = list(self.ex.map(lambda a: self._onnx(a), arrs))
        timing = {"main": round(time.perf_counter() - t0, 3)}
        readings = [Reading(i, "onnx", "main", "\n".join(m.lines), m.words) for i, m in enumerate(mains)]

        # 2. turn check; the first reading of a turned picture is kept
        turns = list(self.ex.map(lambda i: self._limited(self.threads, sideways.turn_of, self.eng, arrs[i],
                                                         mains[i].words), range(len(arrs))))
        todo = [i for i, k in enumerate(turns) if k]
        turned = list(self.ex.map(lambda i: self._onnx(np.ascontiguousarray(np.rot90(arrs[i], turns[i]))), todo))
        for i, m in zip(todo, turned):
            readings.append(Reading(i, "onnx", "turned", "\n".join(m.lines), m.words, turns[i]))
            if _good_words(m) > _good_words(mains[i]):  # keep the turn only if it reads better
                arrs[i] = np.ascontiguousarray(np.rot90(arrs[i], turns[i]))
                fulls[i] = np.ascontiguousarray(np.rot90(fulls[i], turns[i]))
                mains[i] = m
            else:
                turns[i] = 0  # an upright label with a sideways strip: stay upright, the strip pass handles it
        timing["turn"] = round(time.perf_counter() - t0, 3)

        out = ApplicationReading(pics, readings, [k * 90 for k in turns], list(arrs), [m.words for m in mains])
        verdict = judge(out.warning_readings())[0]
        fields_good = bool(fields_ok and fields_ok(out.lines()))
        jobs = []  # (tag, clock, future, meta)

        def add(tag, clock, prio, fn, *a, meta=None):
            jobs.append((tag, clock, self._submit(clock, t0, prio, fn, *a), meta))

        # 3. sideways and upside down, when the heading was not found
        if verdict == "none":
            strip_k = None
            for k, m in enumerate(mains):
                found = sideways.tall_strip(arrs[k], m.words)
                if found:
                    strip_k, (strip, off) = k, found
                    break
            if strip_k is not None:
                rot = self._limited(self.threads, sideways.strip_vote, self.eng, arrs[strip_k], mains[strip_k].words)
                for r in ((rot,) if rot else (1, 3)):
                    add(f"sideways-strip{r * 90}:{strip_k}", "warning", 0, self._onnx,
                        np.ascontiguousarray(np.rot90(strip, r)), 1024 if rot else 768,
                        meta=(strip_k, r, off, strip.shape[:2]))
            else:
                k = sorted(range(len(pics)), key=lambda i: ("brand" not in pics[i].name.lower()
                                                            and "front" not in pics[i].name.lower(),
                                                            len(mains[i].words)))[0]
                add(f"sideways-hi:{k}", "warning", 0, lambda img: self._limited(self.threads, sideways.side_read,
                                                                               self.eng, img), arrs[k],
                    meta=(k, None, (0, 0), arrs[k].shape[:2]))
            for k, a in enumerate(arrs):  # a narrow sideways strip at a side edge (cans, wraps), read bottom to top:
                for side, (strip, off) in zip(("right", "left"), sideways.edge_strips(a)):  # 10 of 11 found that way
                    turned = np.ascontiguousarray(np.rot90(strip, 3))
                    add(f"edge-{side}:{k}", "warning", 0, self._onnx, turned,
                        min(2048, max(32, max(turned.shape[:2]) // 32 * 32)), meta=(k, 3, off, strip.shape[:2]))
            for k, m in enumerate(mains):
                if self._limited(self.threads, sideways.upside_down, self.eng, arrs[k], m.words):
                    add(f"flip180:{k}", "warning", 0, self._onnx, np.ascontiguousarray(np.rot90(arrs[k], 2)),
                        meta=(k, 2, (0, 0), arrs[k].shape[:2]))

        # 5. whole-label Tesseract and inverted reads for the other fields
        if not fields_good:
            for k, a in enumerate(arrs):
                small = Image.fromarray(a)
                small.thumbnail((TESS_FULL_SIDE, TESS_FULL_SIDE))
                add(f"tesseract-full:{k}", "fields", 1, self._tess, np.asarray(small), 3)
        if not fields_good or verdict != "match":
            for k, p in enumerate(pics):
                if p.dark_share >= DARK_SHARE:
                    add(f"inverted:{k}", "fields", 1, self._onnx, 255 - arrs[k])

        # 4. zoom re-read of the warning paragraph on the upright reads
        if verdict != "match":
            for k, m in enumerate(mains):
                reg = zoom.find_region(m.words)
                if reg:
                    add(f"zoom:{k}", "warning", 0, self._zoom, fulls[k], fulls[k].shape[0] / arrs[k].shape[0], reg)

        # collect, with the zoom stage after each sideways read that found the paragraph
        for tag, clock, fut, meta in jobs:
            res = self._get(fut, clock, t0, tag, out)
            if res is None:
                continue
            self._add(out, tag, res)
            if meta is not None:
                k, rot, (ox, oy), (sh, sw) = meta
                if isinstance(res, tuple):  # side_read returns (Text, k)
                    res, rot = res
                reg = zoom.find_region(res.words)
                if reg:
                    s = fulls[k].shape[0] / arrs[k].shape[0]
                    fy0, fx0 = int(oy * s), int(ox * s)
                    sub = fulls[k][fy0:fy0 + int(round(sh * s)), fx0:fx0 + int(round(sw * s))]
                    fut2 = self._submit("warning", t0, 0, self._zoom, np.ascontiguousarray(np.rot90(sub, rot)), s, reg)
                    res2 = self._get(fut2, "warning", t0, f"zoom:{tag}", out)
                    if res2 is not None:
                        self._add(out, f"zoom:{tag}", res2)
        out.timing = timing
        out.seconds = round(time.perf_counter() - t0, 3)
        return out

    def _zoom(self, full, scale, region):
        tess = lambda img, psm: self.ex.submit(self._limited, 1, tesseract, img, psm)
        res = zoom.deskew_two_step(full, scale, region, lambda img, d: self._onnx(img, d), tess)
        return {k: (v.result() if hasattr(v, "result") else v) for k, v in res.items()}

    def _get(self, fut, clock, t0, tag, out):
        stop = FIELDS_STOP if clock == "fields" else WARNING_STOP
        try:
            res = fut.result(timeout=max(0.0, stop - (time.perf_counter() - t0)))
        except Exception:
            out.dropped.append(tag)
            return None
        if res is None:
            out.dropped.append(tag)
        else:
            out.passes.append(tag)
            out.timing[tag] = round(time.perf_counter() - t0, 3)
        return res

    @staticmethod
    def _add(out, tag, res):
        k = int(tag.rsplit(":", 1)[1]) if tag.rsplit(":", 1)[-1].isdigit() else 0
        if isinstance(res, tuple):
            res = res[0]
        if isinstance(res, Text):
            out.readings.append(Reading(k, "onnx", tag, "\n".join(res.lines), res.words))
        elif isinstance(res, str):
            out.readings.append(Reading(k, "tess", tag, res))
        elif isinstance(res, dict):  # zoom: {sub-tag: text}
            for sub, text in res.items():
                out.readings.append(Reading(k, "tess" if "tess" in sub else "onnx", f"{tag}/{sub}", text))
