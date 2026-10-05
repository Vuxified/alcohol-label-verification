"""Make the text detector accept any input size (run once, at build time).

OnnxTR's db_mobilenet_v3_large graph has a fixed 1024 x 1024 input, so every label was squashed into a square
mostly made of padding. Marking height and width as dynamic lets the reader size the input to the label's own
shape (768 px on the long side), which measured 2.7x faster and found more warning headings
(.planning/research/READER-OPTIONS.md). Only the input/output shape declarations change; the weights do not.

Usage: python tools/make_dynamic_det.py      -> app/models/db_mobilenet_v3_large_dyn.onnx
Needs the `onnx` package (requirements-tools.txt); the app itself does not.
"""

from pathlib import Path

import onnx
from onnxtr.models import detection

OUT = Path(__file__).resolve().parent.parent / "app" / "models" / "db_mobilenet_v3_large_dyn.onnx"


def main():
    src = detection.db_mobilenet_v3_large().model_path  # downloads the stock model into OnnxTR's cache once
    m = onnx.load(src)
    dims = m.graph.input[0].type.tensor_type.shape.dim
    dims[2].dim_param, dims[3].dim_param = "height", "width"
    for out in m.graph.output:
        od = out.type.tensor_type.shape.dim
        if len(od) == 4:
            od[2].dim_param, od[3].dim_param = "oh", "ow"
    del m.graph.value_info[:]  # let ONNX Runtime re-infer the inner shapes
    OUT.parent.mkdir(parents=True, exist_ok=True)
    onnx.save(m, OUT)
    print("wrote", OUT)


if __name__ == "__main__":
    main()
