"""Time the OCR step on real COLA label images.

Loads the model once (as the server will), then reads each image and reports per-image
latency. --threads limits CPU threads to approximate a small cloud instance.

Usage: python tools/benchmark_ocr.py [--threads 2] [--limit 40] [--max-side 1600] [--8bit]
"""

import argparse
import json
import statistics
import time
from pathlib import Path

import numpy as np
import onnxruntime as ort
from onnxtr.models import EngineConfig, ocr_predictor
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parent.parent


def load(path, max_side):
    img = ImageOps.exif_transpose(Image.open(path)).convert("RGB")
    img.thumbnail((max_side, max_side))
    return np.asarray(img)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--threads", type=int, default=0, help="0 = all cores")
    ap.add_argument("--limit", type=int, default=40)
    ap.add_argument("--max-side", type=int, default=1600)
    ap.add_argument("--8bit", dest="eight_bit", action="store_true")
    ap.add_argument("--det", default="fast_base", help="detector, e.g. fast_base, fast_small, db_mobilenet_v3_large")
    ap.add_argument("--reco", default="crnn_vgg16_bn", help="recognizer, e.g. crnn_vgg16_bn, crnn_mobilenet_v3_small")
    ap.add_argument("--straight", action="store_true", help="assume upright text (skips per-word rotation)")
    args = ap.parse_args()

    opts = ort.SessionOptions()
    if args.threads:
        opts.intra_op_num_threads = args.threads
        opts.inter_op_num_threads = 1
    # CPU only: matches the cloud server, and the Mac CoreML provider fails on these models
    cfg = EngineConfig(providers=["CPUExecutionProvider"], session_options=opts)
    t0 = time.perf_counter()
    model = ocr_predictor(det_arch=args.det, reco_arch=args.reco,
                          det_engine_cfg=cfg, reco_engine_cfg=cfg, clf_engine_cfg=cfg, load_in_8_bit=args.eight_bit,
                          assume_straight_pages=args.straight, detect_orientation=False)
    print(f"model load: {time.perf_counter() - t0:.2f} s")

    paths = []
    for rec in sorted((ROOT / "data" / "cola_samples").glob("*/record.json")):
        r = json.loads(rec.read_text())
        paths += [rec.parent / i["file"] for i in r["images"]]
    paths = paths[: args.limit]

    model([load(paths[0], args.max_side)])  # warm-up, as the server does at startup
    times, words = [], []
    for p in paths:
        img = load(p, args.max_side)
        t = time.perf_counter()
        doc = model([img])
        times.append(time.perf_counter() - t)
        words.append(sum(len(l.words) for b in doc.pages[0].blocks for l in b.lines))
    times.sort()
    p95 = times[int(len(times) * 0.95) - 1]
    print(f"images: {len(times)}  threads: {args.threads or 'all'}  {args.det} + {args.reco}  "
          f"straight: {args.straight}  8-bit: {args.eight_bit}  max side: {args.max_side}px")
    print(f"per image  median {statistics.median(times):.2f} s   p95 {p95:.2f} s   max {times[-1]:.2f} s")
    print(f"words found per image (median): {statistics.median(words):.0f}")


if __name__ == "__main__":
    main()
