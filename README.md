# Label Check: alcohol label verification prototype

A TTB agent uploads a label's images and types in what the application says. Within about 5 seconds the app answers, item by item, **Matches**, **Does not match** or **Please check**, and shows where on the label each answer came from. A batch page checks hundreds of applications at once. **The agent decides; the app never approves a label.**

**Try it:** https://3jirlgdkpcw55t54gz32ggdnbq0yfrjp.lambda-url.us-east-1.on.aws/
- No files needed: press **Try a label that matches** or **Try a label with a problem**.
- Batch: open **Check many labels**, download the sample batch (22 applications, 2 broken on purpose) and add it.
- The first visit after a quiet period takes about 6 seconds while the checker starts.

---

## How it works, in one minute

1. **Verify, don't extract.** The application already says what the label should contain, so the app searches the label for those values instead of guessing what the label means.
2. **Reading the label:** local text recognition (OnnxTR, with Tesseract as a second reader). Nothing is sent to an outside AI service, so it can run behind an agency firewall: the container was tested with networking switched off.
3. **Deciding:** small, tested rules in plain code (`app/verify/`), each citing its regulation in [`docs/RULES.md`](docs/RULES.md). No AI model decides a verdict.
4. **Three answers, chosen to be honest:**
   - **Matches:** obviously the same ("STONE'S THROW" vs "Stone's Throw").
   - **Does not match:** a different value read clearly (label 45%, application 40%; "may" changed to "can" in the warning, confirmed by two independent readings).
   - **Please check:** anything the app can't be sure of, with what it found. *Not finding something is never "Does not match"*: it may be in script lettering, on a curved can, or on a side that wasn't photographed.
5. **Never stricter than TTB.** Real approved labels must not come back "Does not match". Where TTB approves labels that stretch a rule (a missing period in the warning, metric-only beer with a qualification), the app says Please check. Evidence: [`docs/FINDINGS.md`](docs/FINDINGS.md).

## What it checks

| Item | Rule (27 CFR) |
|---|---|
| Brand name, class/type, name and address, country of origin (imports) | Parts 4, 5, 7: matched as text, case and punctuation ignored; whisky = whiskey in class/type only (§ 5.143) |
| Alcohol content | §§ 4.36, 5.65, 7.65: compared as numbers, many formats ("45% Alc./Vol.", "ALC. 45% BY VOL."); optional for most beer |
| Proof (spirits) | Must be twice the alcohol content when shown (optional) |
| Net contents | Any unit (mL, L, fl oz, pints); standard container sizes; beer must show U.S. units (§ 7.70) |
| Health warning | Part 16: word for word, "GOVERNMENT WARNING" in capitals; sideways, tiny and wrapped text handled |

Not checked by design (listed in `docs/RULES.md` §7): sulfite and color-additive statements, bold and type size (advisory checks still being built).

## Results so far (practice labels)

Measured with `tools/evaluate.py` on the practice set (the final-test set is kept apart and run once):

| | Result |
|---|---|
| 64 real TTB-approved labels | **0** wrongly marked "Does not match" |
| 64 generated labels with planted mistakes | **0** mistakes marked "Matches", except the two advisory checks not built yet (bold heading, type size) |
| Health warning on approved labels | 39 confirmed word for word; the rest Please check (mostly print too small to read) |
| Speed on AWS, warm | 1–3 s per label typical; up to about 5 s when the warning is too small to read |

**Final test (held-out labels, run once on Oct 13):** _to be filled in with the numbers exactly as measured._

**How the answer key was made:** label values were drafted with AI tools and cross-checked by two independent vision models. The author reviewed every final-test label by hand against its images; the practice labels were checked against every image with AI assistance. Each answer sheet in `data/ground_truth/` records who reviewed it. In that review, the vision models' disagreements were almost always the models' own errors (invented addresses and container sizes), which is why the app never lets a model decide.

## Running it yourself

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt onnx
.venv/bin/python tools/make_dynamic_det.py         # one-time: fetch the reading models, make the detector size-flexible
.venv/bin/pytest                                   # 210 rule tests
.venv/bin/uvicorn app.web.main:app --port 8000     # open http://localhost:8000
```

Or with Docker (the models are built into the image; no network needed once built):

```bash
docker build -t label-check .
docker run --rm -p 8080:8080 label-check           # open http://localhost:8080
```

## Deployment

- **AWS Lambda** (container image, arm64, 10 GB / 6 vCPU) behind a function URL; it costs nothing while idle and about $0.0005 per label checked.
- **Uploads** go from the browser straight to a private S3 bucket (Lambda requests are capped at 6 MB) and are **deleted automatically after one day**. Results are not stored: they are returned with the page.
- A batch runs from the browser, which sends several applications at a time; each is checked by its own copy of the checker.
- The same container runs anywhere Docker does. Azure equivalents: Container Apps or Functions (container), Blob Storage with a lifecycle rule.

## Limitations and trade-offs

- **Script logos and curved text** often can't be read; the brand or class/type then says Please check rather than guessing.
- **Bold heading and minimum type size** are not checked yet (advisory only: TTB treats them that way in practice).
- **Batch** needs the browser tab to stay open; results live in the page until downloaded as a spreadsheet.
- **No COLA integration** (out of scope per the brief); the agent types the application values, or supplies them in the batch spreadsheet.
- Prototype only: no login, and not an official U.S. Government system.

## Repository map

| Path | What |
|---|---|
| `app/verify/` | The rules, as small pure functions |
| `app/ocr/` | Label reading: main pass, sideways and upside-down passes, zoom re-read of the warning |
| `app/pipeline.py` | Reading + rules for one application, with the safety rules on top |
| `app/web/` | FastAPI pages (USWDS design system, self-hosted), single label and batch |
| `docs/` | Rules with citations, findings from real labels, requirements traceability |
| `data/` | Real approved labels (TTB Public COLA Registry), generated labels with known mistakes, answer key, frozen practice/final split |
| `tools/` | Data collection, label generator, answer-key review screen, evaluation, sample batch |

Built with the help of AI coding tools; every rule, number and claim here was checked against the code, the regulations or a measurement.
