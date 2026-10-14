# Label Check: alcohol label verification prototype

A TTB agent uploads a label's images and types in what the application says. Within about 5 seconds the app answers, item by item, **Matches**, **Does not match** or **Please check**, and shows where on the label each answer came from and which rule applies (each row names its 27 CFR section, linked to eCFR). A batch page checks hundreds of applications at once. **The agent decides; the app never approves a label.**

**Try it:** https://3jirlgdkpcw55t54gz32ggdnbq0yfrjp.lambda-url.us-east-1.on.aws/
- No files needed: press **Try a label that matches** or **Try a label with a problem**.
- Batch: open **Check many labels**, download the sample batch (22 applications, 2 broken on purpose) and add it.
- No application? Add pictures and leave the boxes blank. The app looks for every required statement and says **On the label** or **Please check**.
- As soon as pictures are added, what the label says is shown under each box ("On the label: 45%"); the boxes stay for the application's values, so a label is never compared with its own reading.
- The first visit after a quiet period takes about 6 seconds while the checker starts.

---

## A five-minute tour

1. **Try a label with a problem.** The heading is "Government Warning" in title case: **Does not match**, with a close-up of the spot and the rule (27 CFR 16.22). Press **I disagree** to see how an agent records a different view; it prints with the page.
2. **Your own label:** add the front and back pictures, and the app reads them at once: alcohol, net contents, class and bottler appear under their boxes, and the product type is chosen (it is optional: left blank, it is told from the label). Type the application's values (try alcohol 40 where the label says 45) and the brand, press **Check label**: alcohol content **Does not match**, everything else **Matches**.
3. **Pictures only:** the same pictures with every box blank. The app looks for each statement the rules require and says **On the label** or **Please check**; it never says Does not match without an application to compare.
4. **Batch:** on **Check many labels**, add the sample batch (22 applications, 2 broken on purpose). Rows that need attention come first; select any row to see its pictures and every item checked; download the results spreadsheet. Pictures that aren't named after an application are read and paired by what they say; anything unclear is listed for you.
5. **Why trust it:** [`docs/RULES.md`](docs/RULES.md) lists every rule with its citation, and what a picture cannot settle. No version goes live unless a full practice run of that exact code has **0 wrong answers** (see Deployment).

---

## How it works, in one minute

1. **Verify, don't extract.** The application already says what the label should contain, so the app searches the label for those values instead of guessing what the label means.
2. **Reading the label:** local text recognition (OnnxTR, with Tesseract as an independent second reader). Every word is read by two word readers, the stock one and one fine-tuned on label words, and the more confident reading is kept ([how it was trained and measured](docs/APPROACH.md#reader-training)). Nothing is sent to an outside AI service, so it can run behind an agency firewall: the container was tested with networking switched off.
3. **Deciding:** small, tested rules in plain code (`app/verify/`), each citing its regulation in [`docs/RULES.md`](docs/RULES.md). No AI model decides a verdict.
4. **Three answers, chosen to be honest:**
   - **Matches:** obviously the same ("STONE'S THROW" vs "Stone's Throw").
   - **Does not match:** a different value read clearly and confirmed by a second, independent reading (label 45%, application 40%; "may" changed to "can" in the warning).
   - **Please check:** anything the app can't be sure of, with what it found. *Not finding something is never "Does not match"*: it may be in script lettering, on a curved can, or on a side that wasn't photographed.
5. **Never stricter than TTB.** Real approved labels must not come back "Does not match". Where TTB approves labels that stretch a rule (a missing period in the warning, metric-only beer with a qualification), the app says Please check. Evidence: [`docs/FINDINGS.md`](docs/FINDINGS.md).
6. **Other approaches** (cloud AI models, AI upscaling, bottle-photo flattening, other OCR engines) were considered; what was tried and why each was or wasn't adopted is in [`docs/ALTERNATIVES.md`](docs/ALTERNATIVES.md).
7. **Why it is built this way**, the assumptions where the brief leaves gaps (for example, the application details are typed in or come from a spreadsheet, standing in for COLA), the open unknowns and the test data: [`docs/APPROACH.md`](docs/APPROACH.md).

## What it checks

| Item | Rule (27 CFR) |
|---|---|
| Brand name, class/type, name and address, country of origin (imports) | Parts 4, 5, 7: matched as text, case and punctuation ignored; whisky = whiskey in class/type only (§ 5.143) |
| Alcohol content | §§ 4.36, 5.65, 7.65: compared as numbers, many formats ("45% Alc./Vol.", "ALC. 45% BY VOL."); optional for most beer |
| Proof (spirits) | Must be twice the alcohol content when shown (optional) |
| Net contents | Any unit (mL, L, fl oz, pints); standard container sizes; beer must show U.S. units (§ 7.70) |
| Health warning | Part 16: word for word, "GOVERNMENT WARNING" in capitals; sideways, tiny and wrapped text handled |
| Warning type size | § 16.22: measured when the label height is given (form field or batch column `label_height`); advisory |
| Label rules | Minimum alcohol for the class (vodka, whisky, gin, brandy, rum, tequila 40%; flavored 30%; §§ 5.142–5.151), bottled in bond = 100 proof (§ 5.88), "table wine" only at 14% or less (§ 4.21), "low alcohol", "non-alcoholic", "alcohol free" wording on beer (§ 7.65); Please check with the rule quoted |
| Pictures only | With no brand given: each required statement looked for on the label (§§ 4.32, 5.63, 7.63); "On the label" or Please check, never Does not match |

Also: the fanciful name (like the brand), the "GOVERNMENT WARNING" heading in bold (measured, advisory). Not checked by design: whether sulfite, color-additive or age statements are needed (they depend on facts a picture cannot show), characters per inch. The full rule inventory, checked or not and why, is in [`docs/RULES.md`](docs/RULES.md) §6b.

## Results so far (practice labels)

Measured with `tools/evaluate.py` on the practice sets (the final-test set is kept apart and run once). Three numbers matter: **wrong answers** (must be 0), **mistakes caught**, and **items confirmed automatically** (the rest are Please check, for the agent).

| Practice set | Wrong answers | Mistakes caught | Items confirmed |
|---|---|---|---|
| 227 real TTB-approved labels (64 + 78 + 85, from the registry) | **0** "Does not match" | – | 77% / 76% / 71% |
| 178 real approved labels with one planted change (alcohol, size, proof, a warning word, title-case heading, brand) | **0** changed items "Matches" | **178 of 178** flagged; 158 named exactly | 69% / 68% |
| 96 generated labels, 64 with planted mistakes | **0** "Matches" on a mistake | **64 of 64** flagged; 61 named exactly | 93% |
| 76 photo-style pictures of 35 real labels (angles, close-ups, cans) | **0** "Does not match" | – | 30% (photos are hard; most items say Please check) |

- Health warning confirmed word for word on approved labels: 51 of 64, 63 of 78, 57 of 85. One approved label really prints the warning differently from 27 CFR 16.21 (`docs/FINDINGS.md`); it is reported apart.
- Speed (laptop, 4 cores): typical 1.6–2.1 s, slowest 4.3 s per label (5.1 s for a photo).
- Pictures only, on 142 approved labels: 0 Does not match; class found on 135, net contents 126, bottler 107, alcohol content 106 (+9 beer, where it is optional). Reading on upload showed alcohol right 103 times (wrong 3) and net contents right 115 (wrong 15); it does not guess the brand (usually a logo).
- The new label rules (class minimums, bottled in bond, table wine, low/no-alcohol wording) said Please check on 0 of the 227 approved labels.
- Measured 2026-10-14, run g14 ([`docs/evidence/practice_run.log`](docs/evidence/practice_run.log)); the same run is the one the safety gate approved for the live version. The answer keys of the 85 newest labels were drafted with AI assistance and reviewed by the author.

**Final test (held-out labels, run once, 2026-10-12, on the live version ef13fdb):** numbers exactly as measured ([`docs/evidence/final_test.log`](docs/evidence/final_test.log)).

| Final-test set | Wrong answers | Mistakes caught | Items confirmed |
|---|---|---|---|
| 28 real TTB-approved labels | **0** "Does not match" | – | 77% |
| 46 of them with one planted change | **0** changed items "Matches" | **46 of 46** flagged; 39 named exactly | 75% |
| 48 generated labels, 32 with planted mistakes | **0** "Matches" on a mistake | **32 of 32** flagged; 29 named exactly | 94% |
| 22 photo-style pictures of real labels | **0** "Does not match" | – | 16% |
| 18 photo-style pictures with a planted change | **0** changed items "Matches" | **18 of 18** flagged; 6 named exactly | 19% |

- Without the six real labels that have a near-identical twin in practice: still 0 wrong answers either way.
- Health warning confirmed word for word on 19 of 28 approved labels; the rest Please check.
- Speed: typical 0.7–2.6 s, slowest 4.5 s per label (a photo).
- The harder photos (never straight-on, glare, coloured light) are where the app is weakest: it stays safe (no wrong answers) but leaves most items to the agent.

162 items the app had never seen: 28 real approved labels and 48 generated labels (32 with planted mistakes), frozen 2026-10-02. From the same 28 labels, frozen 2026-10-10: 46 with one planted change, 22 photo-style pictures (harder than practice: never straight-on, more glare, coloured light) and 18 photos with a planted change. Six real labels with a near-identical twin in practice were left out of the 2026-10-10 sets. `tools/evaluate.py --final` checks every file's checksum and runs only once. All of it is in `data/`.

**After the final test** (it was not run again), a code review and hands-on testing led to these changes, each approved by a full practice run (live version f5e5928):
- A different number or product word in a name or class needs the second reader before it is Does not match; Pinot Gris/Grigio, Syrah/Shiraz and Muscat/Moscato are not different products; the importer statement must be one phrase ("Imported by …"). Each can only turn an answer into Please check.
- The type of product may be left blank and is then told from the label (the result says so); with pictures only, the brand is Please check for the agent to confirm.
- Clearer wording on the form, and each batch row opens a side panel with its pictures and every item.
- Text printed beside the warning in its own column is painted over before the warning is re-read, so it is no longer taken for words added to the warning (a word really added sits a word space from the warning's words and is never painted over).
- "Hard tea" and "hard lemonade" are told as malt beverages. If no product type can be told from the label, the page says so as soon as the pictures are added and keeps them, instead of losing them on Check label.
- More is read from the label when nothing is typed (measured on the 227 approved labels, all pictures): the product type is told on 225 (0 wrong; also from "Brewed by", "Proof", "Winery", and alcohol over 24%), alcohol content 178 of 221 (up from 164; misread wording like "13.5% Ale./Vol." and two readings settled by the proof), country 59 of 78 imports (up from 48: "Wine of Australia", "Hecho en México"). Class or type shows the designation line, not a sentence or the company. With one picture only, the result says the back and neck are needed too.
- A typed brand is Matches when the label prints it with company words or an amount beside it ("BULLEIT DISTILLING CO.", "CROWN ROYAL 40% ALC/VOL"), or when the second reader sees a misread brand exactly at that spot; never when the label also shows a close but different version of it. Brand Matches on the approved labels: 128 of 227, up from 119.

**How the answer key was made:** label values were drafted with AI tools and cross-checked by two independent vision models. The author reviewed every final-test label and the 85 newest practice labels by hand against their images; the other practice labels were checked against every image with AI assistance. Each answer sheet in `data/ground_truth/` records who reviewed it. In that review, the vision models' disagreements were almost always the models' own errors (invented addresses and container sizes), which is why the app never lets a model decide.

## Running it yourself

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt onnx
.venv/bin/python tools/make_dynamic_det.py         # one-time: fetch the reading models, make the detector size-flexible
.venv/bin/pytest                                   # 1,141 tests
.venv/bin/uvicorn app.web.main:app --port 8000     # open http://localhost:8000
```

Or with Docker (the models are built into the image; no network needed once built):

```bash
docker build -t label-check .
docker run --rm -p 8080:8080 label-check           # open http://localhost:8080
```

## Deployment

**Safety gate.** A version goes live only through `tools/deploy.sh`, which stops at the first failure:
1. all tests, including one that switches the network off and checks a label (`tests/test_offline.py`);
2. `tools/gate.py`: a full practice run of exactly the code being shipped, with **0 wrong "Does not match" on approved labels, 0 wrong "Matches" on planted mistakes, every planted mistake flagged**, and 95% of labels within 5 seconds;
3. the container is built from the committed code, started **with networking switched off**, and must answer both sample labels correctly;
4. only then is the live site switched, and checked again.

- **AWS Lambda** (container image, arm64, 10 GB / 6 vCPU) behind a function URL; it costs nothing while idle and about $0.0005 per label checked.
- **Uploads** go from the browser straight to a private S3 bucket (Lambda requests are capped at 6 MB) and are **deleted automatically after one day**. Results are not stored: they are returned with the page.
- A batch runs from the browser, which sends several applications at a time; each is checked by its own copy of the checker.
- The same container runs anywhere Docker does. Azure equivalents: Container Apps or Functions (container), Blob Storage with a lifecycle rule.

## Limitations and trade-offs

- **Script logos and curved text** often can't be read; the brand or class/type then says Please check rather than guessing.
- **Batch** needs the browser tab to stay open; results live in the page until downloaded as a spreadsheet.
- **No COLA integration** (out of scope per the brief); the agent types the application values, or supplies them in the batch spreadsheet.
- **Bold heading** is measured (stroke thickness) when the warning is large and straight enough; **type size** is measured when the label height is given, and only answers when the picture settles it (most approved labels print right at the minimum, so it often says "not confirmed"). Both are advisory: TTB states it does not review type size.
- **"I disagree"** on every result (single page and batch): a reason and a note, shown with the results, printed, and in the batch spreadsheet (`agent_note`). Nothing is stored on the server. In production these notes would go to a reviewer, who turns each real miss into a rule fix with a test, or a reading lesson for the next reader training, released only through the safety gate.
- **Public prototype:** no login. Cost is capped by limiting the checker to 12 copies running at once, plus a budget alert; anyone can upload pictures, which are deleted after one day.

## Repository map

| Path | What |
|---|---|
| `app/verify/` | The rules, as small pure functions |
| `app/ocr/` | Label reading: main pass, sideways and upside-down passes, zoom re-read of the warning |
| `app/pipeline.py` | Reading + rules for one application, with the safety rules on top |
| `app/web/` | FastAPI pages (USWDS design system, self-hosted), single label and batch |
| `docs/` | Rules with citations, findings from real labels, requirements traceability |
| `data/` | Real approved labels (TTB Public COLA Registry), generated labels with known mistakes, answer key, frozen practice/final split |
| `tools/` | Data collection, label generator, answer-key review screen, evaluation, sample batch, word-reader training |

Built with the help of AI coding tools; every rule, number and claim here was checked against the code, the regulations or a measurement.
