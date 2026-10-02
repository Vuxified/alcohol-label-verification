"""Local review page for the answer key (data/ground_truth/*.json).

Shows each real COLA label next to its drafted answers. The reviewer fixes any field and
clicks "Save — this is correct", which writes the file back with reviewed: true.
Labels with judgment calls are shown first. Runs on this computer only; nothing leaves it.

Usage: python tools/review_answer_key.py   then open http://localhost:8765
"""

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
TRUTH = ROOT / "data" / "ground_truth"
COLA = ROOT / "data" / "cola_samples"
PORT = 8765

FIELDS = ["brand_name", "class_type", "abv", "abv_text", "proof", "net_contents_text",
          "net_contents_ml", "name_address_text", "country_of_origin_text"]
WARNING_FIELDS = ["present", "matches_required_text", "heading_all_caps", "heading_looks_bold",
                  "whole_warning_bold", "orientation", "text_as_printed"]


def priority(item):
    """Labels most likely to need a human look come first."""
    w = item["warning"]
    score = 0
    score += 5 if w.get("matches_required_text") is False else 0
    score += 5 if not w.get("present") else 0
    score += 3 if item.get("unreadable_fields") else 0
    score += 2 if item.get("abv") is None or item.get("net_contents_ml") is None else 0
    score += min(len(item.get("hard_cases", [])), 3)
    return (item.get("reviewed", False), -score, item["id"])


def items():
    data = [json.loads(p.read_text()) for p in TRUTH.glob("*.json")]
    return [d["id"] for d in sorted(data, key=priority)]


PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Answer key review</title>
<style>
 body{font:18px/1.45 system-ui,sans-serif;margin:0;color:#1b1b1b;background:#f6f6f6}
 header{background:#1a4480;color:#fff;padding:12px 20px;display:flex;gap:20px;align-items:center}
 header b{font-size:20px} #progress{margin-left:auto}
 main{display:grid;grid-template-columns:1.2fr 1fr;gap:20px;padding:20px}
 .imgs img{max-width:100%;border:1px solid #ccc;background:#fff;margin-bottom:12px;display:block}
 .imgs figcaption{font-size:15px;color:#555}
 form{background:#fff;padding:16px 20px;border:1px solid #ddd;border-radius:6px}
 label{display:block;font-weight:600;margin-top:10px} input,select,textarea{width:100%;font:inherit;padding:6px;box-sizing:border-box}
 textarea{height:150px;font-size:15px} .app{background:#eef3fa;padding:10px;border-radius:6px;font-size:16px}
 .notes{background:#fff4e0;padding:10px;border-radius:6px;font-size:16px;margin-top:10px}
 .bar{display:flex;gap:12px;margin-top:16px} button{font:inherit;padding:12px 20px;min-height:44px;border-radius:6px;border:0;cursor:pointer}
 .save{background:#00a91c;color:#fff;font-weight:700;flex:1} .skip{background:#dfe1e2}
 .done{color:#00a91c;font-weight:700}
</style></head><body>
<header><b>Answer key review</b><span id="which"></span><span id="progress"></span></header>
<main><section class="imgs" id="imgs"></section>
<section><div class="app" id="app"></div><form id="f"></form><div class="notes" id="notes"></div>
<div class="bar"><button class="skip" id="prev">&larr; Back</button><button class="save" id="save">Save &mdash; this is correct</button><button class="skip" id="next">Skip &rarr;</button></div>
<p id="status"></p></section></main>
<script>
const FIELDS = %FIELDS%, WFIELDS = %WFIELDS%;
let ids = [], pos = 0, cur = null;
const $ = id => document.getElementById(id);
async function load() {
  ids = await (await fetch('/api/items')).json();
  show();
}
async function show() {
  const id = ids[pos];
  const d = await (await fetch('/api/item/' + id)).json();
  cur = d.truth;
  $('which').textContent = `Label ${pos + 1} of ${ids.length} - TTB ID ${id}`;
  $('progress').textContent = `${d.reviewed_count} reviewed`;
  $('imgs').innerHTML = d.record.images.map(i =>
    `<figure><img src="/img/${id}/${encodeURIComponent(i.file)}" alt="${i.image_type}"><figcaption>${i.image_type}</figcaption></figure>`).join('');
  $('app').innerHTML = `<b>Application says:</b> ${d.record.brand_name} &middot; ${d.record.class_type_code} &middot; ${d.record.product_type}, ${d.record.source}`;
  const inp = (k, v) => `<label>${k.replaceAll('_', ' ')}<input name="${k}" value="${v ?? ''}"></label>`;
  $('f').innerHTML = FIELDS.map(k => inp(k, cur[k])).join('') + '<h3>Government warning</h3>' +
    WFIELDS.map(k => k === 'text_as_printed'
      ? `<label>text as printed<textarea name="w_${k}">${cur.warning[k] ?? ''}</textarea></label>`
      : inp('w_' + k, cur.warning[k])).join('');
  $('notes').innerHTML = '<b>Notes:</b> ' + ((cur.hard_cases || []).join('; ') || 'none') +
    (cur.reviewed ? ' <span class="done">&#10003; already reviewed</span>' : '');
  $('status').textContent = '';
}
function parse(v) {
  if (v === '') return null;
  if (v === 'true') return true; if (v === 'false') return false;
  if (!isNaN(v) && v.trim() !== '') return Number(v);
  return v;
}
$('save').onclick = async () => {
  const fd = new FormData($('f'));
  FIELDS.forEach(k => cur[k] = parse(fd.get(k)));
  WFIELDS.forEach(k => cur.warning[k] = k === 'text_as_printed' ? (fd.get('w_' + k) || null) : parse(fd.get('w_' + k)));
  cur.reviewed = true;
  const r = await fetch('/api/item/' + ids[pos], {method: 'POST', body: JSON.stringify(cur)});
  $('status').textContent = r.ok ? 'Saved.' : 'Save failed.';
  if (r.ok && pos < ids.length - 1) { pos++; show(); }
};
$('next').onclick = () => { if (pos < ids.length - 1) { pos++; show(); } };
$('prev').onclick = () => { if (pos > 0) { pos--; show(); } };
load();
</script></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def send(self, body, ctype="application/json", code=200):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = unquote(self.path)
        if path == "/":
            return self.send(PAGE.replace("%FIELDS%", json.dumps(FIELDS))
                             .replace("%WFIELDS%", json.dumps(WARNING_FIELDS)), "text/html; charset=utf-8")
        if path == "/api/items":
            return self.send(json.dumps(items()))
        if path.startswith("/api/item/"):
            item_id = Path(path).name
            truth = json.loads((TRUTH / f"{item_id}.json").read_text())
            record = json.loads((COLA / item_id / "record.json").read_text())
            reviewed = sum(json.loads(p.read_text()).get("reviewed", False) for p in TRUTH.glob("*.json"))
            return self.send(json.dumps({"truth": truth, "record": record, "reviewed_count": reviewed}))
        if path.startswith("/img/"):
            _, _, item_id, name = path.split("/", 3)
            f = (COLA / item_id / name).resolve()
            if f.parent.parent == COLA.resolve() and f.exists():
                return self.send(f.read_bytes(), "image/png" if f.suffix == ".png" else "image/jpeg")
        self.send("not found", "text/plain", 404)

    def do_POST(self):
        item_id = Path(unquote(self.path)).name
        target = TRUTH / f"{item_id}.json"
        if not self.path.startswith("/api/item/") or not target.exists():
            return self.send("not found", "text/plain", 404)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        target.write_text(json.dumps(body, indent=2, ensure_ascii=False))
        self.send('{"ok": true}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Answer key review: open http://localhost:{PORT}  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
