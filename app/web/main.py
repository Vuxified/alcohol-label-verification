"""The web app: check one label against its application (DESIGN.md §5). Run: uvicorn app.web.main:app

Results are not kept: the results page is returned by the same request, with its pictures built in, so any copy of
the app can answer (AWS Lambda runs several). On a laptop, images are posted with the form and read in memory.
With UPLOAD_BUCKET set (on Lambda, whose requests are capped at 6 MB), the browser uploads each image straight to that
private bucket with a short-lived link, and the bucket deletes it after one day.
"""

import base64
import hashlib
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
from app.typesize import parse_label_height
from app.verify import Application, Verdict
from app.verify.abv import parse_typed_abv
from app.verify.net_contents import parse_typed_net
from app.verify.model import SEVERITY
from app.verify.presence import ON_LABEL, read_values

from . import copy
from .marks import differing_words, warning_marks

ROOT = Path(__file__).resolve().parent
DATA = ROOT.parent.parent / "data"
MAX_IMAGES, MAX_MB, SHOW_SIDE = 6, 20, 1600
BUCKET = os.environ.get("UPLOAD_BUCKET")
UPLOAD_KEY = re.compile(r"uploads/[0-9a-f]{32}/[0-5]")
Image.MAX_IMAGE_PIXELS = 40_000_000
TEXT_FIELDS = ("brand_name", "fanciful_name", "class_type", "name_address", "country_of_origin")  # words get marked

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
# The stylesheet link carries the file's fingerprint, so browsers fetch a new look instead of a kept old copy.
templates.env.globals["css_version"] = hashlib.sha256((ROOT / "static" / "app.css").read_bytes()).hexdigest()[:10]
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
            "country_of_origin": a.get("country_of_origin") or "",
            "label_height": next((f"{im['height_in']:g}" for im in it["images"] if "back" in im["file"]), "")}
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
    out, seen = [], set()
    for key, name in zip(keys, names):
        if not UPLOAD_KEY.fullmatch(key) or key in seen:
            continue
        if len(out) == MAX_IMAGES + 1:  # one more than allowed is enough to report "too many"; never fetch thousands
            break
        seen.add(key)
        out.append((name, s3.get_object(Bucket=BUCKET, Key=key)["Body"].read()))
    return out


async def _read_request(data):
    """The application and images from a submitted form (the page and the batch page send the same fields).
    -> (form, images, errors)."""
    form = {k: (data.get(k) or "").strip() for k in ("beverage_type", "brand_name", "fanciful_name", "class_type",
                                                      "abv", "net_contents", "name_address", "source",
                                                      "country_of_origin", "label_height")}
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
    if form["net_contents"] and form["beverage_type"] in copy.BEVERAGES \
            and parse_typed_net(form["net_contents"], form["beverage_type"]) is None:
        errors.append(copy.ERRORS["net"])
    if form["abv"] and parse_typed_abv(form["abv"]) is None:
        errors.append(copy.ERRORS["abv_proof" if "proof" in form["abv"].lower() else "abv"])
    if form["label_height"] and parse_label_height(form["label_height"]) is None:
        errors.append(copy.ERRORS["height"])
    return form, images, errors


def _application(form) -> Application:
    return Application(
        form["beverage_type"], form["brand_name"], form.get("class_type") or None,
        parse_typed_abv(form["abv"]) if form.get("abv") else None, form.get("net_contents") or None,
        form.get("name_address") or None, form.get("source") or "domestic", form.get("country_of_origin") or None,
        form.get("fanciful_name") or None, parse_label_height(form.get("label_height")))


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


@app.post("/api/read")
async def api_read(request: Request):
    """Values read from the label pictures, to fill in the blank boxes of the form ("Fill in from the label").
    Suggestions only: the agent checks each one against the application."""
    if not state["ready"]:
        return JSONResponse({"error": "starting"}, status_code=503)
    form, images, errors = await _read_request(await request.form())
    errors = [e for e in errors if e != copy.ERRORS["beverage"]]
    if errors:
        return JSONResponse({"error": " ".join(errors)}, status_code=400)
    if not slots.acquire(blocking=False):
        return JSONResponse({"error": "busy"}, status_code=503)
    try:
        reading = await run_in_threadpool(state["reader"].read, images)
    finally:
        slots.release()
    kind = form["beverage_type"] if form["beverage_type"] in copy.BEVERAGES else None
    values = read_values(reading.lines(), kind)
    text = " ".join(reading.lines())[:4000]  # the batch page pairs leftover pictures by what they say
    return values | {"text": text}


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
    side = SHOW_SIDE if len(res.reading.frames) <= 2 else 1200 if len(res.reading.frames) <= 4 else 1000
    for fr in res.reading.frames:  # smaller pictures when there are many: Lambda responses are capped at 6 MB
        img = Image.fromarray(fr)
        img.thumbnail((side, side))  # boxes still line up: the overlay uses the full-size coordinates
        pics.append(_data_url(img, "JPEG"))
    crops = {field: _data_url(Image.open(io.BytesIO(crop_png(res.reading.frames[k], box))), "PNG")
             for field, (k, box) in ev.items()}
    asked = _asked(res.form)
    attention = [f for f in rows if f.verdict in (Verdict.FAIL, Verdict.CHECK)]
    diffs = {f.field: differing_words(asked.get(f.field), f.found) for f in attention if f.field in TEXT_FIELDS}
    plain = {}
    for f in attention:  # say a near match in plain words: "The label shows 12 where the application says 10."
        d = diffs.get(f.field)
        if d and (f.code or "").endswith(("_NEAR_MATCH", "_NUMBER_DIFFERS", "_WORD_DIFFERS")):
            a, b = [" ".join(w for w, differs in side if differs) for side in d]
            if a and b:
                plain[f.field] = copy.NEAR_MATCH.format(label=b, app=a)
    warning = next((f for f in attention if f.field == "warning_text" and f.code != "WARNING_MISSING"), None)
    return templates.TemplateResponse(request, "results.html", {
        "res": res, "rows": rows, "ev": ev, "counts": counts, "alone": not res.form.get("brand_name"), "ON_LABEL": ON_LABEL, "Verdict": Verdict, "shapes": shapes,
        "names": [p.name for p in res.reading.pictures], "pics": pics, "crops": crops, "asked": asked,
        "attention": attention, "matched": [f for f in rows if f not in attention], "diffs": diffs, "plain": plain,
        "warning_parts": warning_marks(res.reading.warning_readings()) if warning else None})



def _asked(form) -> dict:
    """What the application says, per result row, shown beside what the label shows."""
    abv = f'{parse_typed_abv(form["abv"]):g}' if form.get("abv") else ""
    return {"brand_name": form.get("brand_name"), "fanciful_name": form.get("fanciful_name"),
            "class_type": form.get("class_type"), "abv": f"{abv}%" if abv else None,
            "proof": f"{2 * float(abv):g} Proof, if shown (twice the alcohol content)"
                     if abv and form.get("beverage_type") == "spirits" else None,
            "net_contents": form.get("net_contents"), "name_address": form.get("name_address"),
            "country_of_origin": form.get("country_of_origin"),
            "warning_text": "The exact wording required by 27 CFR 16.21",
            "warning_caps": '"GOVERNMENT WARNING" in capital letters', "warning_bold": '"GOVERNMENT WARNING" in bold',
            "warning_size": "Warning letters at least the minimum height for the container (27 CFR 16.22)",
            "abv_minimum": "The rule for the class (27 CFR 5.142-5.151)", "bonded": "50% alcohol, 100 proof (27 CFR 5.88)",
            "wine_terms": "The rules for wine (27 CFR 4.6, 4.21, 4.36)", "malt_terms": "The rules for these words (27 CFR 7.65)"}
