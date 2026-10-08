"""The web app: check one label against its application (DESIGN.md §5). Run: uvicorn app.web.main:app

Results are not kept: the results page is returned by the same request, with its pictures built in, so any copy of
the app can answer (AWS Lambda runs several). On a laptop, images are posted with the form and read in memory.
With UPLOAD_BUCKET set (on Lambda, whose requests are capped at 6 MB), the browser uploads each image straight to that
private bucket with a short-lived link, and the bucket deletes it after one day.
"""

import base64
import io
import json
import os
import re
import threading
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from PIL import Image
from starlette.concurrency import run_in_threadpool

from app.evidence import crop_png, locate, locate_warning
from app.ocr.reader import Reader
from app.pipeline import check_application
from app.verify import Application, Verdict
from app.verify.model import SEVERITY

from . import copy

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent.parent / "data"
MAX_IMAGES, MAX_MB, SHOW_SIDE = 6, 10, 1600
BUCKET = os.environ.get("UPLOAD_BUCKET")
UPLOAD_KEY = re.compile(r"uploads/[0-9a-f]{32}/[0-5]")
Image.MAX_IMAGE_PIXELS = 40_000_000

state = {"reader": None, "ready": False}
slots = threading.BoundedSemaphore(int(os.environ.get("INTERACTIVE_SLOTS", "2")))


def _start():
    reader = Reader(cpus=int(os.environ["OCR_CPUS"]) if os.environ.get("OCR_CPUS") else None)
    reader.warm_up()
    state["reader"], state["ready"] = reader, True


@asynccontextmanager
async def lifespan(_):
    threading.Thread(target=_start, daemon=True).start()
    yield


app = FastAPI(title="Label Check", lifespan=lifespan, docs_url=None, redoc_url=None)
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")
templates = Jinja2Templates(directory=ROOT / "templates")
templates.env.globals.update(copy=copy, upload_to_bucket=bool(BUCKET))
s3 = None
if BUCKET:
    import boto3
    s3 = boto3.client("s3")


def _check_file(name: str, data: bytes) -> str | None:
    if len(data) > MAX_MB * 1024 * 1024:
        return copy.ERRORS["too_big"].format(name=name, mb=len(data) / 1024 / 1024, max=MAX_MB)
    if data[:5] == b"%PDF-":
        return copy.ERRORS["pdf"].format(name=name)
    if data[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1", b"ftypheif"):
        return copy.ERRORS["heic"].format(name=name)
    try:
        with Image.open(io.BytesIO(data)) as im:
            if im.format not in ("JPEG", "PNG", "WEBP", "MPO"):
                return copy.ERRORS["bad_type"].format(name=name)
            im.verify()
    except Exception:
        return copy.ERRORS["unreadable"].format(name=name)
    return None


def _sample(key):
    item = DATA / "synthetic" / copy.SAMPLES[key][1]
    it = json.loads((item / "item.json").read_text())
    a = it["application"]
    form = {"beverage_type": a["beverage_type"], "brand_name": a["brand_name"], "class_type": a.get("class_type") or "",
            "abv": "" if a.get("abv") is None else f"{a['abv']:g}", "net_contents": a.get("net_contents") or "",
            "name_address": a.get("name_address") or "", "source": a.get("source", "domestic"),
            "country_of_origin": a.get("country_of_origin") or ""}
    images = [(im["file"], (item / im["file"]).read_bytes()) for im in it["images"]]
    return form, images


def _render_form(request, form=None, errors=None, status=200):
    return templates.TemplateResponse(request, "index.html", {"form": form or {}, "errors": errors or []},
                                      status_code=status)


@app.get("/", response_class=HTMLResponse)
async def index(request: Request):
    return _render_form(request)


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/readyz")
async def readyz():
    return Response('{"ready": true}' if state["ready"] else '{"ready": false}', media_type="application/json",
                    status_code=200 if state["ready"] else 503)


@app.get("/upload-links")
async def upload_links(n: int = 1):
    """One short-lived upload link per image (only when UPLOAD_BUCKET is set)."""
    if not BUCKET or not 1 <= n <= MAX_IMAGES:
        return Response(status_code=404)
    folder = uuid.uuid4().hex
    return JSONResponse([s3.generate_presigned_post(
        BUCKET, f"uploads/{folder}/{i}", Conditions=[["content-length-range", 1, MAX_MB * 1024 * 1024]], ExpiresIn=300)
        for i in range(n)])


def _uploaded(keys, names):
    """(name, bytes) for each image the browser put in the bucket."""
    out = []
    for key, name in zip(keys, names):
        if not UPLOAD_KEY.fullmatch(key):
            continue
        out.append((name, s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()))
    return out


async def _read_request(data):
    """The application and images from a submitted form (the page and the batch page send the same fields).
    -> (form, images, errors)."""
    form = {k: (data.get(k) or "").strip() for k in ("beverage_type", "brand_name", "fanciful_name", "class_type",
                                                      "abv", "net_contents", "name_address", "source",
                                                      "country_of_origin")}
    if BUCKET and data.getlist("upload_keys"):
        received = await run_in_threadpool(_uploaded, data.getlist("upload_keys"), data.getlist("upload_names"))
    else:
        received = [(f.filename, await f.read()) for f in data.getlist("images") if getattr(f, "filename", "")]
    errors = []
    if not received:
        errors.append(copy.ERRORS["no_images"])
    if len(received) > MAX_IMAGES:
        errors.append(copy.ERRORS["too_many"].format(n=len(received), max=MAX_IMAGES))
    images = []
    for name, b in received[:MAX_IMAGES]:
        problem = _check_file(name, b)
        if problem:
            errors.append(problem)
        images.append((name, b))
    if form["beverage_type"] not in copy.BEVERAGES:
        errors.append(copy.ERRORS["beverage"])
    if not form["brand_name"]:
        errors.append(copy.ERRORS["brand"])
    if form["abv"]:
        try:
            float(form["abv"].rstrip("%").strip())
        except ValueError:
            errors.append(copy.ERRORS["abv"])
    return form, images, errors


def _application(form) -> Application:
    return Application(
        form["beverage_type"], form["brand_name"], form.get("class_type") or None,
        float(form["abv"].rstrip("%").strip()) if form.get("abv") else None, form.get("net_contents") or None,
        form.get("name_address") or None, form.get("source") or "domestic", form.get("country_of_origin") or None,
        form.get("fanciful_name") or None)


async def _run(application, images):
    """-> CheckResult, or None when this copy of the app is already checking its limit of labels."""
    if not slots.acquire(blocking=False):
        return None
    try:
        return await run_in_threadpool(check_application, state["reader"], application, images)
    finally:
        slots.release()


@app.post("/check")
async def check(request: Request):
    if not state["ready"]:
        return templates.TemplateResponse(request, "starting.html", {}, status_code=503)
    data = await request.form()
    sample = data.get("sample")
    if sample in copy.SAMPLES:
        form, images = _sample(sample)
    else:
        form, images, errors = await _read_request(data)
        if errors:
            names = [n for n, _ in images]
            return _render_form(request, form, errors + ([f"Please add your images again: {', '.join(names)}."]
                                                         if names else []), 400)
    res = await _run(_application(form), images)
    if res is None:
        return HTMLResponse(f"<p>{copy.ERRORS['busy']}</p>", status_code=503)
    res.form = form
    return await run_in_threadpool(_results_page, request, res)


@app.post("/api/check")
async def api_check(request: Request):
    """One application, as JSON (used by the batch page). 503 means try again shortly."""
    if not state["ready"]:
        return JSONResponse({"error": "starting"}, status_code=503)
    form, images, errors = await _read_request(await request.form())
    if errors:
        return JSONResponse({"error": " ".join(errors)}, status_code=400)
    res = await _run(_application(form), images)
    if res is None:
        return JSONResponse({"error": "busy"}, status_code=503)
    return {"overall": res.overall.value, "seconds": res.seconds, "notes": res.notes,
            "fields": [{"field": f.field, "verdict": f.verdict.value, "code": f.code, "reason": f.reason}
                       for f in res.fields]}


@app.get("/batch", response_class=HTMLResponse)
async def batch(request: Request):
    return templates.TemplateResponse(request, "batch.html", {})


def _evidence(res):
    """Field -> (picture index, box) for the rows that have something to show."""
    out = {}
    for f in res.fields:
        if f.field.startswith("warning"):
            hit = locate_warning(res.reading.frame_words)
        else:
            hit = locate(f.found, res.reading.frame_words) if f.found else None
        if hit:
            out[f.field] = hit
    return out


def _data_url(img: Image.Image, fmt: str) -> str:
    b = io.BytesIO()
    img.save(b, fmt, **({"quality": 85} if fmt == "JPEG" else {}))
    return f"data:image/{fmt.lower()};base64,{base64.b64encode(b.getvalue()).decode()}"


def _results_page(request, res):
    ev = _evidence(res)
    rows = sorted(res.fields, key=lambda f: -SEVERITY[f.verdict])
    counts = {v: sum(1 for f in res.fields if f.verdict == v) for v in Verdict}
    shapes = [fr.shape[:2] for fr in res.reading.frames]
    pics = []
    for fr in res.reading.frames:
        img = Image.fromarray(fr)
        img.thumbnail((SHOW_SIDE, SHOW_SIDE))  # boxes still line up: the overlay uses the full-size coordinates
        pics.append(_data_url(img, "JPEG"))
    crops = {field: _data_url(Image.open(io.BytesIO(crop_png(res.reading.frames[k], box))), "PNG")
             for field, (k, box) in ev.items()}
    return templates.TemplateResponse(request, "results.html", {
        "res": res, "rows": rows, "ev": ev, "counts": counts, "Verdict": Verdict, "shapes": shapes,
        "names": [p.name for p in res.reading.pictures], "pics": pics, "crops": crops})
