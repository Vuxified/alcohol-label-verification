"""The two reading engines: OnnxTR (docTR models on ONNX Runtime) and Tesseract. CPU only, no network.

OnnxTR runs as a pool of predictors (one per concurrent image) with the dynamic-size text detector, so each
image is detected at its own shape with a 768-px long side (READER-OPTIONS.md: 2.7x faster than the stock
1024 x 1024 square, and more warning headings found). A word is (text, confidence, (x0, y0, x1, y1) in pixels
of the image that was read).
"""

import os
import queue
import shutil
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import onnxruntime as ort
import onnxtr.models.engine as _engine
import pytesseract
from onnxtr.models import EngineConfig, crop_orientation_predictor, ocr_predictor, recognition_predictor
from onnxtr.models import detection, recognition

MODEL = Path(__file__).resolve().parent.parent / "models" / "db_mobilenet_v3_large_dyn.onnx"
RECOGNIZER = "crnn_mobilenet_v3_small"
# A second word reader, trained on label words (tools/train_reader.py, docs/APPROACH.md). LABEL_WORD_MODEL="" runs the
# stock reader alone (for comparison runs), or names another trained file.
WORDS = os.environ.get("LABEL_WORD_MODEL", str(Path(__file__).with_name("words_labels.onnx")))

Word = tuple  # (text: str, conf: float, box: (x0, y0, x1, y1))


class _Meta:
    def __init__(self, m):
        self.name, self.type = m.name, m.type
        self.shape = [1 if s in ("height", "width") else s for s in m.shape]


class _Session(ort.InferenceSession):
    """OnnxTR's Engine reads int(input.shape[-1]) at load; report 1 for the dynamic height/width so it loads.
    Pinned to onnxtr==0.9.0; startup runs a self-test read (Reader.warm_up)."""

    def get_inputs(self):
        return [_Meta(m) for m in super().get_inputs()]


_engine.InferenceSession = _Session


def _config(threads):
    opts = ort.SessionOptions()
    opts.intra_op_num_threads = threads
    opts.inter_op_num_threads = 1
    return EngineConfig(providers=["CPUExecutionProvider"], session_options=opts)


class _Pair:
    """Two word readers on every word: the reading of whichever is more confident is kept (the stock reader stays
    right on ordinary type, the trained one on the display fonts labels use)."""

    def __init__(self, stock, trained):
        self.stock, self.trained = stock, trained

    def __call__(self, crops, **kwargs):
        a, b = self.stock(crops, **kwargs), self.trained(crops, **kwargs)
        return [x if x[1] >= y[1] else y for x, y in zip(a, b)]


@dataclass
class Text:
    lines: list[str]
    words: list[Word]


class OnnxEngine:
    def __init__(self, pool: int = 2, threads: int = 2):
        if not MODEL.exists():
            raise FileNotFoundError(f"{MODEL} is missing; run: python tools/make_dynamic_det.py")
        self.threads = threads
        self.q: queue.Queue = queue.Queue()
        for _ in range(pool):
            cfg = _config(threads)
            det = detection.db_mobilenet_v3_large(model_path=str(MODEL), engine_cfg=cfg)
            p = ocr_predictor(det_arch=det, reco_arch=RECOGNIZER, det_engine_cfg=cfg, reco_engine_cfg=cfg,
                              clf_engine_cfg=cfg, assume_straight_pages=True, detect_orientation=False)
            if WORDS:
                if not Path(WORDS).exists():
                    raise FileNotFoundError(f"{WORDS} is missing; make it with tools/train_reader.py")
                trained = recognition_predictor(recognition.crnn_mobilenet_v3_small(model_path=WORDS, engine_cfg=cfg),
                                                engine_cfg=cfg)
                p.reco_predictor = _Pair(p.reco_predictor, trained)
            self.q.put(p)
        self.orientation = crop_orientation_predictor(engine_cfg=_config(threads))

    def read(self, img: np.ndarray, det_size: int = 768) -> Text:
        """Detect at an aspect-fit input with long side det_size (multiples of 32), recognise, return lines + words."""
        p = self.q.get()
        try:
            h, w = img.shape[:2]
            s = det_size / max(h, w)
            th, tw = max(32, round(h * s / 32) * 32), max(32, round(w * s / 32) * 32)
            rz = p.det_predictor.pre_processor.resize
            rz.size = rz.output_size = (th, tw)
            rz.preserve_aspect_ratio = False  # stretch: OnnxTR's padding removal assumes a square target
            doc = p([img])
        finally:
            self.q.put(p)
        lines, words = [], []
        for block in doc.pages[0].blocks:
            for ln in block.lines:
                lines.append(" ".join(wd.value for wd in ln.words))
                for wd in ln.words:
                    g = np.array(wd.geometry).reshape(-1, 2)
                    (x0, y0), (x1, y1) = g.min(0), g.max(0)
                    words.append((wd.value, float(wd.confidence), (x0 * w, y0 * h, x1 * w, y1 * h)))
        return Text(lines, words)

    def detect(self, img: np.ndarray, det_size: int) -> list[tuple]:
        """Detector only: word boxes in pixels."""
        p = self.q.get()
        try:
            h, w = img.shape[:2]
            s = det_size / max(h, w)
            th, tw = max(32, round(h * s / 32) * 32), max(32, round(w * s / 32) * 32)
            rz = p.det_predictor.pre_processor.resize
            rz.size = rz.output_size = (th, tw)
            rz.preserve_aspect_ratio = False
            out = p.det_predictor([img])[0]
        finally:
            self.q.put(p)
        return [(b[0] * w, b[1] * h, b[2] * w, b[3] * h) for b in out]

    def recognise(self, crops: list[np.ndarray]) -> list[tuple[str, float]]:
        p = self.q.get()
        try:
            return p.reco_predictor(crops) if crops else []
        finally:
            self.q.put(p)

    def orientation_vote(self, crops: list[np.ndarray]) -> float:
        """> 0: the crops read upright; < 0: upside down (confidence-weighted share)."""
        crops = [c for c in crops if c.size and min(c.shape[:2]) >= 4]
        if not crops:
            return 0.0
        _, cls, conf = self.orientation(crops)
        return sum((1 if c == 0 else -1 if c == 180 else 0) * p for c, p in zip(cls, conf)) / len(crops)


TESSERACT = shutil.which("tesseract")
if TESSERACT:
    pytesseract.pytesseract.tesseract_cmd = TESSERACT


def tesseract(img: np.ndarray, psm: int) -> str:
    """Tesseract 5 LSTM, one thread (set OMP_THREAD_LIMIT=1 in the process environment)."""
    return pytesseract.image_to_string(img, config=f"--oem 1 --psm {psm}")
