"""Fast local review page for the answer key (data/ground_truth/*.json).

Picture on the left, answers on the right. Each field shows whether the three readings agree (the drafted key and
two vision-model drafts from tools/draft_answer_key.py); disputed fields show the alternatives to pick from. The
warning is shown with every word that differs from the legal text marked red. The reviewer fixes what is wrong
and presses Enter, which writes the file back with reviewed: true and adds a line to the review log.
Runs on this computer only; nothing leaves it.

Queues (pick one in the address bar):
    /?queue=heldout          all final-test labels (review every one)
    /?queue=disputed         practice labels where the readings disagree (review every one)
    /?queue=sample&n=30&seed=20261006   a random sample of practice labels where all readings agree
    /?queue=extra2           the second batch of extra practice labels (data/splits/practice_extra2.json)
    /?queue=all              everything, unreviewed first

Keys: Enter = correct, save, next.  To take a model's reading, click it under that one field (there is no
      shortcut that changes several fields at once: on 2026-10-08 one copied invented addresses into the key).
      Left / Right = back / skip.  E = edit the first field.  Esc = leave a field.

Usage: python tools/review_answer_key.py   then open http://localhost:8765/?queue=heldout
"""

import json
import random
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from app.verify.warning import REQUIRED  # noqa: E402

TRUTH = ROOT / "data" / "ground_truth"
COLA = ROOT / "data" / "cola_samples"
SPLIT = ROOT / "data" / "splits" / "split.json"
EXTRA2 = ROOT / "data" / "splits" / "practice_extra2.json"
REVIEW = ROOT / "data" / "answer_key_review"
CROSS = REVIEW / "crosscheck.json"
LOG = REVIEW / "review_log.json"
PORT = 8765

# Answer-key field -> cross-check field (tools/draft_answer_key.py)
FIELDS = [("brand_name", "brand_name"), ("class_type", "class_type"), ("abv_text", "abv_text"),
          ("abv", None), ("proof", None), ("net_contents_text", "net_contents_text"), ("net_contents_ml", None),
          ("name_address_text", "name_address_text"), ("country_of_origin_text", "country_of_origin_text")]
WARNING_FIELDS = ["present", "heading_all_caps", "heading_looks_bold", "whole_warning_bold", "orientation",
                  "matches_required_text"]
MODEL_NAMES = {"nemotron": "1 · Nemotron", "nova_pro": "2 · Nova Pro"}


def load(p, default):
    return json.loads(p.read_text()) if p.exists() else default


def queue(name, n=30, seed=20261006):
    heldout = {x[5:] for x in load(SPLIT, {}).get("heldout", []) if x.startswith("cola_")}
    ids = sorted(p.stem for p in TRUTH.glob("*.json"))
    cross = load(CROSS, {})
    reviewed = {i for i in ids if load(TRUTH / f"{i}.json", {}).get("reviewed")}
    dev = [i for i in ids if i not in heldout]
    if name == "heldout":
        out = [i for i in ids if i in heldout]
    elif name == "disputed":
        out = [i for i in dev if cross.get(i, {}).get("disputed")]
    elif name == "extra2":
        out = [x[5:] for x in load(EXTRA2, {}).get("dev", []) if x[5:] in ids]
    elif name == "sample":
        agreed = [i for i in dev if i in cross and not cross[i]["disputed"]]
        out = sorted(random.Random(seed).sample(agreed, min(n, len(agreed))))
    else:
        out = ids
    return sorted(out, key=lambda i: (i in reviewed, i))


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8"><title>Answer key review</title>
<style>
 body{font:16px/1.4 system-ui,sans-serif;margin:0;color:#1b1b1b;background:#f6f6f6}
 header{background:#1a4480;color:#fff;padding:10px 18px;display:flex;gap:18px;align-items:center;flex-wrap:wrap}
 header b{font-size:18px} header .r{margin-left:auto}
 main{display:grid;grid-template-columns:1.25fr 1fr;gap:16px;padding:14px}
 main>section{max-height:calc(100vh - 80px);overflow:auto}
 .imgs figure{margin:0 0 10px;background:#fff;border:1px solid #ccc;overflow:auto;max-height:78vh}
 .imgs img{width:100%;display:block;cursor:zoom-in;transform-origin:top left}
 .imgs img.z2{width:200%;cursor:zoom-out} figcaption{font-size:13px;color:#555;padding:4px 6px}
 .panel{background:#fff;border:1px solid #ddd;border-radius:6px;padding:10px 14px;margin-bottom:10px}
 .row{display:grid;grid-template-columns:150px 1fr;gap:8px;align-items:start;padding:5px 0;border-bottom:1px solid #eee}
 .row label{font-weight:600;font-size:14px} input,textarea,select{width:100%;font:inherit;padding:4px 6px;box-sizing:border-box}
 textarea{height:96px;font:13px ui-monospace,monospace}
 .ok{color:#0a5c22;font-size:12px;font-weight:700} .disp{color:#8a4b00;font-size:12px;font-weight:700}
 .alt{display:block;margin-top:3px;font-size:13px;background:#fff7e6;border:1px solid #f0c36d;border-radius:4px;padding:3px 6px;cursor:pointer;text-align:left;width:100%}
 .alt:hover{background:#ffe9b8} .rowd{background:#fffaf0}
 .warn{font:13px/1.5 ui-monospace,monospace} mark.bad{background:#ffd4d4;color:#900;font-weight:700} mark.miss{background:#fff1c2}
 .ttb{font-size:14px} .ttb td{padding:2px 6px} .bar{display:flex;gap:10px;margin-top:8px}
 button.main{background:#00a91c;color:#fff;font-weight:700;border:0;border-radius:6px;padding:12px;flex:1;font-size:17px;cursor:pointer}
 button.sec{background:#dfe1e2;border:0;border-radius:6px;padding:12px 16px;cursor:pointer}
 kbd{border:1px solid #999;border-radius:3px;padding:0 4px;background:#fff;color:#000;font-size:12px}
 .done{background:#d9f2df;color:#0a5c22;padding:2px 8px;border-radius:4px;font-weight:700}
</style></head><body>
<header><b>Answer key review</b><span id="which"></span><span id="q"></span>
<span class="r" id="stats"></span></header>
<main><section class="imgs" id="imgs"></section>
<section>
 <div class="panel ttb" id="ttb"></div>
 <div class="panel" id="fields"></div>
 <div class="panel"><b>Government warning</b> <span id="wbadge"></span>
   <div class="warn" id="wdiff"></div><textarea id="wtext"></textarea><div id="walts"></div><div id="wfields"></div></div>
 <div class="bar"><button class="sec" id="prev">&larr; Back</button>
   <button class="main" id="save">Correct &mdash; save &amp; next <kbd>Enter</kbd></button>
   <button class="sec" id="next">Skip &rarr;</button></div>
 <p id="status" style="font-size:14px"></p>
 <p style="font-size:13px;color:#555">Keys: <kbd>Enter</kbd> save &amp; next ·
 <kbd>&larr;</kbd>/<kbd>&rarr;</kbd> back/skip · <kbd>E</kbd> edit · <kbd>Esc</kbd> leave field · click a picture to zoom</p>
</section></main>
<script>
const LEGAL = %LEGAL%, FIELDS = %FIELDS%, WFIELDS = %WFIELDS%, MODELS = %MODELS%;
const params = new URLSearchParams(location.search);
let ids = [], pos = 0, cur = null, cross = null, t0 = 0, times = [], orig = '';
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function words(s) { return (s || '').match(/\(?\w+\)?[.,:;]?/g) || []; }
function diff(text) {  // mark words that differ from the legal text (case ignored)
  const a = words(LEGAL).map(w => w.toLowerCase().replace(/[.,:;]$/, '')), bw = words(text),
        b = bw.map(w => w.toLowerCase().replace(/[.,:;]$/, ''));
  const n = a.length, m = b.length, L = Array.from({length: n + 1}, () => new Int32Array(m + 1));
  for (let i = n - 1; i >= 0; i--) for (let j = m - 1; j >= 0; j--)
    L[i][j] = a[i] === b[j] ? L[i + 1][j + 1] + 1 : Math.max(L[i + 1][j], L[i][j + 1]);
  let i = 0, j = 0, out = [];
  while (i < n || j < m) {
    if (i < n && j < m && a[i] === b[j]) { out.push(esc(bw[j])); i++; j++; }
    else if (j < m && (i >= n || L[i][j + 1] >= L[i + 1][j])) { out.push(`<mark class="bad" title="not in the legal text">${esc(bw[j])}</mark>`); j++; }
    else { out.push(`<mark class="miss" title="missing">[${esc(a[i])}?]</mark>`); i++; }
  }
  return out.join(' ');
}
async function load() {
  const q = params.get('queue') || 'heldout';
  ids = await (await fetch('/api/items?' + params.toString())).json();
  const NAMES = {heldout: 'Final exam labels', disputed: 'Practice labels: computers disagreed',
                 sample: 'Practice labels: computers agreed (quick look)',
                 extra2: 'Extra practice labels, batch 2', all: 'All labels'};
  $('q').textContent = `${NAMES[q] || q} (${ids.length}) · all from the TTB website`;
  if (!ids.length) { $('which').textContent = 'Nothing in this queue.'; return; }
  show();
}
function badge(c) {
  if (!c) return '';
  return c.status === 'agreed' ? '<span class="ok">✓ all readings agree</span>' : '<span class="disp">⚠ disputed</span>';
}
function alts(c, onpick) {
  if (!c || c.status === 'agreed') return '';
  return Object.entries(c.readings).filter(([k]) => k !== 'answer_key').map(([k, v]) =>
    `<button class="alt" data-v="${esc(JSON.stringify(v))}" data-k="${k}">${esc(MODELS[k] || k)}: ${esc(v ?? '(not on label)')}</button>`).join('');
}
async function show() {
  const id = ids[pos];
  const d = await (await fetch('/api/item/' + id)).json();
  cur = d.truth; cross = d.cross; orig = JSON.stringify(cur); t0 = performance.now();
  $('which').textContent = `Label ${pos + 1} of ${ids.length} · TTB ID ${id}`;
  $('stats').innerHTML = `${d.reviewed_count} reviewed · avg ${times.length ? (times.reduce((a, b) => a + b) / times.length).toFixed(0) : '–'} s/label` +
    (cur.reviewed ? ' <span class="done">✓ reviewed</span>' : '');
  $('imgs').innerHTML = d.record.images.map(i =>
    `<figure><img src="/img/${id}/${encodeURIComponent(i.file)}" alt="${esc(i.image_type)}" onclick="this.classList.toggle('z2')">
     <figcaption>${esc(i.image_type)}${i.width_in ? `, ${i.width_in}×${i.height_in} in` : ''}${i.file === cur.warning.image_file ? ' · <b>warning on this image</b>' : ''}</figcaption></figure>`).join('');
  const r = d.record;
  $('ttb').innerHTML = `<b>TTB record</b> (official) · <a href="https://www.ttbonline.gov/colasonline/viewColaDetails.do?action=publicFormDisplay&ttbid=${id}" target="_blank">open on TTB</a>
    <table><tr><td>Brand</td><td><b>${esc(r.brand_name)}</b> ${r.fanciful_name ? '· ' + esc(r.fanciful_name) : ''}</td></tr>
    <tr><td>Category code</td><td>${esc(r.class_type_code)} <i>(a filing bucket, not the label wording)</i></td></tr>
    <tr><td>Type / source</td><td>${esc(r.product_type)} · ${esc(r.source)} · origin code ${esc(r.origin_code)}</td></tr></table>
    ${(cur.hard_cases || []).length ? '<div style="font-size:13px;color:#6b4e00">Notes: ' + esc(cur.hard_cases.join('; ')) + '</div>' : ''}`;
  $('fields').innerHTML = FIELDS.map(([k, ck]) => {
    const c = ck && cross ? cross.fields[ck] : null;
    return `<div class="row ${c && c.status !== 'agreed' ? 'rowd' : ''}"><label for="f_${k}">${k.replaceAll('_', ' ')}<br>${badge(c)}</label>
      <div><input id="f_${k}" data-k="${k}" value="${esc(cur[k])}">${alts(c)}</div></div>`;
  }).join('');
  const wc = cross ? cross.fields.warning_text : null;
  $('wbadge').innerHTML = badge(wc);
  $('wtext').value = cur.warning.text_as_printed || '';
  $('wdiff').innerHTML = diff($('wtext').value);
  $('walts').innerHTML = alts(wc);
  $('wfields').innerHTML = WFIELDS.map(k => `<div class="row"><label for="w_${k}">${k.replaceAll('_', ' ')}</label>
      <input id="w_${k}" value="${esc(cur.warning[k])}"></div>`).join('');
  document.querySelectorAll('#fields .alt').forEach(b => b.onclick = () => {
    b.closest('div').querySelector('input').value = JSON.parse(b.dataset.v) ?? ''; });
  document.querySelectorAll('#walts .alt').forEach(b => b.onclick = () => {
    $('wtext').value = JSON.parse(b.dataset.v) ?? ''; $('wdiff').innerHTML = diff($('wtext').value); });
  $('status').textContent = '';
}
$('wtext').oninput = () => $('wdiff').innerHTML = diff($('wtext').value);
function parse(v, numeric) {  // only number fields become numbers: a brand like "51" stays text
  if (v === '') return null; if (v === 'true') return true; if (v === 'false') return false;
  if (numeric && !isNaN(v) && v.trim() !== '') return Number(v); return v;
}
const NUMERIC = ['abv', 'proof', 'net_contents_ml'];
async function save() {
  FIELDS.forEach(([k]) => cur[k] = parse($('f_' + k).value, NUMERIC.includes(k)));
  cur.warning.text_as_printed = $('wtext').value.trim() || null;
  WFIELDS.forEach(k => cur.warning[k] = parse($('w_' + k).value));
  const before = JSON.parse(orig);
  const changed = FIELDS.map(([k]) => k).filter(k => JSON.stringify(before[k]) !== JSON.stringify(cur[k]))
    .concat(['text_as_printed', ...WFIELDS].filter(k => JSON.stringify(before.warning[k]) !== JSON.stringify(cur.warning[k])).map(k => 'warning.' + k));
  cur.reviewed = true;
  const secs = Math.round((performance.now() - t0) / 1000);
  const r = await fetch('/api/item/' + ids[pos], {method: 'POST', body: JSON.stringify(
    {truth: cur, log: {queue: params.get('queue') || 'heldout', seconds: secs, changed}})});
  if (!r.ok) { $('status').textContent = 'Save failed.'; return; }
  times.push(secs);
  $('status').textContent = changed.length ? `Saved with fixes: ${changed.join(', ')}` : 'Saved, no changes.';
  if (pos < ids.length - 1) { pos++; show(); } else { $('which').textContent = 'Queue finished. Thank you!'; }
}
$('save').onclick = save;
$('next').onclick = () => { if (pos < ids.length - 1) { pos++; show(); } };
$('prev').onclick = () => { if (pos > 0) { pos--; show(); } };
document.addEventListener('keydown', e => {
  const typing = ['INPUT', 'TEXTAREA'].includes(document.activeElement.tagName);
  if (e.key === 'Escape') { document.activeElement.blur(); return; }
  if (e.key === 'Enter' && (!typing || document.activeElement.tagName === 'INPUT')) { e.preventDefault(); save(); return; }
  if (typing) return;
  if (e.key === 'ArrowRight') $('next').click();
  else if (e.key === 'ArrowLeft') $('prev').click();
  else if (e.key === 'e' || e.key === 'E') { e.preventDefault(); $('f_brand_name').focus(); }
});
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
        url = urlparse(self.path)
        path, qs = unquote(url.path), parse_qs(url.query)
        if path == "/":
            page = (PAGE.replace("%LEGAL%", json.dumps(REQUIRED)).replace("%FIELDS%", json.dumps(FIELDS))
                    .replace("%WFIELDS%", json.dumps(WARNING_FIELDS)).replace("%MODELS%", json.dumps(MODEL_NAMES)))
            return self.send(page, "text/html; charset=utf-8")
        if path == "/api/items":
            q = qs.get("queue", ["heldout"])[0]
            return self.send(json.dumps(queue(q, int(qs.get("n", [30])[0]), int(qs.get("seed", [20261006])[0]))))
        if path.startswith("/api/item/"):
            item_id = Path(path).name
            truth = json.loads((TRUTH / f"{item_id}.json").read_text())
            record = json.loads((COLA / item_id / "record.json").read_text())
            reviewed = sum(1 for p in TRUTH.glob("*.json") if json.loads(p.read_text()).get("reviewed", False))
            cross = load(CROSS, {}).get(item_id)
            return self.send(json.dumps({"truth": truth, "record": record, "cross": cross, "reviewed_count": reviewed}))
        if path.startswith("/img/"):
            _, _, item_id, name = path.split("/", 3)
            f = (COLA / item_id / name).resolve()
            if f.parent.parent == COLA.resolve() and f.exists():
                return self.send(f.read_bytes(), "image/png" if f.suffix == ".png" else "image/jpeg")
        self.send("not found", "text/plain", 404)

    def do_POST(self):
        item_id = Path(unquote(urlparse(self.path).path)).name
        target = TRUTH / f"{item_id}.json"
        if not self.path.startswith("/api/item/") or not target.exists():
            return self.send("not found", "text/plain", 404)
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        target.write_text(json.dumps(body["truth"], indent=2, ensure_ascii=False))
        log = load(LOG, [])
        log.append({"id": item_id, "time": time.strftime("%Y-%m-%dT%H:%M:%S"), **body.get("log", {})})
        LOG.write_text(json.dumps(log, indent=1))
        self.send('{"ok": true}')

    def log_message(self, *args):
        pass


if __name__ == "__main__":
    print(f"Answer key review: open http://localhost:{PORT}/?queue=heldout  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
