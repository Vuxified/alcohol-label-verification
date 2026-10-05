# Label Check: one container, CPU only, no network calls at run time (models are built in).
# Runs as an ordinary web server, and on AWS Lambda through the Lambda Web Adapter extension.
FROM python:3.12-slim

COPY --from=public.ecr.aws/awsguru/aws-lambda-adapter:0.9.1 /lambda-adapter /opt/extensions/lambda-adapter

RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    OMP_THREAD_LIMIT=1 \
    ONNXTR_CACHE_DIR=/opt/models \
    PORT=8080 \
    AWS_LWA_READINESS_CHECK_PATH=/readyz \
    AWS_LWA_ASYNC_INIT=true

WORKDIR /srv
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app
COPY tools/make_dynamic_det.py ./tools/make_dynamic_det.py
# Download the stock models once, make the detector size-flexible, then drop the build-only package.
RUN pip install --no-cache-dir onnx \
 && python tools/make_dynamic_det.py \
 && python -c "from onnxtr.models import recognition, classification; recognition.crnn_mobilenet_v3_small(); classification.mobilenet_v3_small_crop_orientation()" \
 && pip uninstall -y onnx \
 && chmod -R a+rX /opt/models

# Sample labels for the "Try it without uploading" buttons (generated for this project).
COPY data/synthetic/syn_spirits_00_none ./data/synthetic/syn_spirits_00_none
COPY data/synthetic/syn_malt_01_warning_titlecase ./data/synthetic/syn_malt_01_warning_titlecase

RUN useradd --system --uid 10001 app
USER app
EXPOSE 8080
CMD ["sh", "-c", "uvicorn app.web.main:app --host 0.0.0.0 --port ${PORT}"]
