"""The web app: check one label against its application (DESIGN.md §5). Run: uvicorn app.web.main:app

Nothing is stored on disk and nothing leaves the server: images are read in memory, results are kept in memory
for 30 minutes (at most 200), then dropped.
"""

import io
import json
import os
import threading
import time
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response
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
MAX_IMAGES, MAX_MB, KEEP_S, KEEP_N = 6, 10, 30 * 60, 200
Image.MAX_IMAGE_PIXELS = 40_000_000

state = {"reader": None, "ready": False}
slots = threading.BoundedSemaphore(int(os.environ.get("INTERACTIVE_SLOTS", "2")))
results: "OrderedDict[str, tuple[float, object]]" = OrderedDict()
lock = threading.Lock()


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
templates.env.globals.update(copy=copy)


def _store(res) -> str:
    rid = uuid.uuid4().hex
    now = time.time()
    with lock:
        results[rid] = (now, res)
        for k in [k for k, (t, _) in results.items() if now - t > KEEP_S]:
            del results[k]
        while len(results) > KEEP_N:
            results.popitem(last=False)
    return rid


def _get(rid):
    with lock:
        item = results.get(rid)
        if item and time.time() - item[0] <= KEEP_S:
            results.move_to_end(rid)
            return item[1]
    return None


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


@app.post("/check")
async def check(request: Request):
    if not state["ready"]:
        return templates.TemplateResponse(request, "starting.html", {}, status_code=503)
    data = await request.form()
    sample = data.get("sample")
    if sample in copy.SAMPLES:
        form, images = _sample(sample)
    else:
        form = {k: (data.get(k) or "").strip() for k in ("beverage_type", "brand_name", "fanciful_name", "class_type",
                                                          "abv", "net_contents", "name_address", "source",
                                                          "country_of_origin")}
        uploads = [f for f in data.getlist("images") if getattr(f, "filename", "")]
        errors = []
        if not uploads:
            errors.append(copy.ERRORS["no_images"])
        if len(uploads) > MAX_IMAGES:
            errors.append(copy.ERRORS["too_many"].format(n=len(uploads), max=MAX_IMAGES))
        images = []
        for f in uploads[:MAX_IMAGES]:
            b = await f.read()
            problem = _check_file(f.filename, b)
            if problem:
                errors.append(problem)
            images.append((f.filename, b))
        if form["beverage_type"] not in copy.BEVERAGES:
            errors.append(copy.ERRORS["beverage"])
        if not form["brand_name"]:
            errors.append(copy.ERRORS["brand"])
        if form["abv"]:
            try:
                float(form["abv"].rstrip("%").strip())
            except ValueError:
                errors.append(copy.ERRORS["abv"])
        if errors:
            names = [n for n, _ in images]
            return _render_form(request, form, errors + ([f"Please add your images again: {', '.join(names)}."]
                                                         if names else []), 400)
    application = Application(
        form["beverage_type"], form["brand_name"], form.get("class_type") or None,
        float(form["abv"].rstrip("%").strip()) if form.get("abv") else None, form.get("net_contents") or None,
        form.get("name_address") or None, form.get("source") or "domestic", form.get("country_of_origin") or None,
        form.get("fanciful_name") or None)
    if not slots.acquire(blocking=False):
        return HTMLResponse(f"<p>{copy.ERRORS['busy']}</p>", status_code=503)
    try:
        res = await run_in_threadpool(check_application, state["reader"], application, images)
    finally:
        slots.release()
    res.form = form
    return RedirectResponse(f"/results/{_store(res)}", status_code=303)


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


@app.get("/results/{rid}", response_class=HTMLResponse)
async def show(request: Request, rid: str):
    res = _get(rid)
    if res is None:
        return HTMLResponse('<p>These results have expired. <a href="/">Check a label</a></p>', status_code=404)
    ev = _evidence(res)
    rows = sorted(res.fields, key=lambda f: -SEVERITY[f.verdict])
    counts = {v: sum(1 for f in res.fields if f.verdict == v) for v in Verdict}
    shapes = [fr.shape[:2] for fr in res.reading.frames]
    return templates.TemplateResponse(request, "results.html", {
        "rid": rid, "res": res, "rows": rows, "ev": ev, "counts": counts, "Verdict": Verdict, "shapes": shapes,
        "names": [p.name for p in res.reading.pictures]})


@app.get("/results/{rid}/image/{n}")
async def image(rid: str, n: int):
    res = _get(rid)
    if res is None or not 0 <= n < len(res.reading.frames):
        return Response(status_code=404)
    b = io.BytesIO()
    Image.fromarray(res.reading.frames[n]).save(b, "JPEG", quality=85)
    return Response(b.getvalue(), media_type="image/jpeg")


@app.get("/results/{rid}/crop/{field}")
async def crop(rid: str, field: str):
    res = _get(rid)
    hit = _evidence(res).get(field) if res else None
    if hit is None:
        return Response(status_code=404)
    k, box = hit
    return Response(crop_png(res.reading.frames[k], box), media_type="image/png")
