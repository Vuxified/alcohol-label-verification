# Approach: why it is built this way

What the prototype is for, the decisions that shaped it and why, what was assumed where the brief leaves gaps, what
is still unknown, and how it is tested. Rules and citations are in [RULES.md](RULES.md); other tools that were
considered are in [ALTERNATIVES.md](ALTERNATIVES.md).

## The job

From the interviews: an agent compares a label with its application, item by item (Sarah, Jenny). Most of that is
matching, which is where a tool helps. It must answer in about **5 seconds** (the scanning-vendor pilot took 30–40 s and
was abandoned), be usable by someone who isn't comfortable with technology, handle **batches of 200–300**, and work
behind a firewall that blocks many outside services (Marcus). Judgment stays with the agent (Dave: "STONE'S THROW" is
obviously "Stone's Throw").

So the app answers each item with **Matches**, **Does not match** or **Please check**, shows the evidence, and
**never approves a label**.

## Decisions

| Decision | Why | Not chosen, and why |
|---|---|---|
| **Verify, don't extract.** The app searches the label for what the application says. | The application already says what the label should show; searching for a known value is far more reliable than guessing which text is the brand. | Extracting every field and comparing afterwards: errors pile up (which line is the brand?), and a label can end up checked against itself. |
| **The label is read on the app's own server** (OnnxTR models, with Tesseract as a second reader). | Works behind a firewall; the container was tested with networking switched off. No label leaves the server. | Cloud AI services: blocked by the firewall Marcus describes; 46 of the 71 public submissions we reviewed depend on one. |
| **Written rules decide, each citing 27 CFR.** AI is used to read the picture, never to decide. | The same label always gets the same answer, and each answer can be explained. In our tests a vision model accepted 12 deliberately altered warnings as correct, and models invented addresses and bottle sizes. | A retrieval-augmented or LLM "judge": inconsistent, can't run behind the firewall, and can "helpfully" correct the very text that must be checked word for word. |
| **Three answers, chosen to be honest.** Not finding something is never Does not match. | A value may be in decorative lettering, on a curved can or on a side that wasn't photographed. Real approved labels must not be failed (**never stricter than TTB**). | Two answers (pass/fail): forces guesses either way. |
| **A clearly read difference is Does not match**: a different number ("10 Year" vs "12 YEAR"), a different product-type word ("RYE" vs "BOURBON"), a different alcohol content or size. | The label must be identical to the approved application (27 CFR 5.22(a)); overstating age is prohibited (5.74(a)(2)). | Everything close as Please check: hides real violations among reading slips. Digits that readers confuse (0/8, 1/7, 5/6) and near spellings ("BOURBAN") stay Please check. |
| **Obviously the same is Matches**: case, spacing, punctuation, apostrophes, dashes, accents, ™/®, "&"/"and", "St."/"Saint", "whisky"/"whiskey" (class/type only, § 5.143), units ("750 ml" = "75 cl" = "25.4 fl oz"). | Dave's point. Every variant is a test case. | Fuzzy similarity scores: a 95% score let "10 Year" pass as "12 Year", found by an independent review and fixed. |
| **The health warning is judged across several independent readings**; Does not match needs two different readers showing the same change. | Word for word is required (Jenny; 27 CFR 16.21), but one reader's slip must not fail a real label. The capitals check uses the raw text; boldness is measured from stroke thickness. | Trusting one reading: either fails real labels or lets changes through. |
| **Speed: two clocks.** Items are read within about 3 s; the warning gets until 5 s for its extra passes. | Meets the 5-second limit while giving small, sideways or curved warnings the extra reads they need. | Reading everything at the highest quality: 6–7 s on 4 cores. |
| **Hosting: AWS Lambda with a container**, scaled to zero when idle; uploads go to private storage deleted after one day; results are not stored. | Costs nothing idle; the same container runs on Azure (Container Apps) or on a server inside the agency. Marcus: store nothing sensitive. | Always-on servers: cost; storing results: not needed for a prototype, and brings retention rules. |
| **Results page**: one sentence says what needs attention; each such item shows "Application says" next to "Label shows" with the different words underlined, a close-up, and the reason; matching items fold away. | Readable in 5 seconds; the agent sees the evidence without hunting. Large type, works at 200% zoom and on a phone. | A table of every item: the one problem gets lost among the matches. |
| **Batch runs from the browser**, a few applications at a time, each checked by its own copy of the checker. Pictures are paired with applications by the file names in the spreadsheet, or by being named after the application ("TTB-0001_front.jpg"). | No queue or database to run; 22 applications take about 10 s on AWS. | A server-side job queue: more to build and secure than a prototype needs. |
| **Feedback stays with the agent.** (Planned) an "I disagree" note on any result goes into the printout and the results spreadsheet only. | Nothing stored on the server. In production a reviewer would turn confirmed feedback into rule fixes and new tests, never into automatic learning: one tired click must not teach the system to pass a real difference. | Clicks that retrain the system directly. |

## Assumptions (where the brief leaves gaps)

1. **The application details are typed in** (one label) **or come from a spreadsheet** (batch). In production they
   would come from COLA; the brief rules out connecting to it for the prototype.
2. An application may have **several images** (front, back, neck), as in the COLA registry; the warning may be on any.
3. **Alcohol content and net contents are compared when given.** The real COLA form has no fields for them, but the
   brief's example treats them as application data.
4. **All three product types** (spirits, wine, malt beverages) are in scope.
5. The images are mostly **label artwork**, as submitted with applications; phone photos of bottles are handled but are
   harder (glare, curves).
6. Graders can reach a public cloud address to open the demo. It is a prototype: no sign-in, no stored records.
7. Labels are mainly in English; common French, Spanish and Italian phrases for the country of origin are recognized.

## Unknowns

- **How agents would want to record their decision** (approve, request a correction) inside a real workflow. The tool
  stops at evidence and leaves the decision to the agent.
- **Type size**: the minimum size of the warning can't be checked without the label's real dimensions; the form doesn't
  ask for them yet.
- **TTB practice where it stretches a rule**: some approved labels lack the warning's final period, or show metric-only
  beer sizes with a qualification. The app says Please check there ([FINDINGS.md](FINDINGS.md)).
- **Reading limits**: script logos and very small or curved text are often unread, so those items say Please check.
  How often that happens on a grader's own labels is unknown until they try.
- **A misread that looks like a real difference**: digit misreads that keep the number plausible are guarded
  (only the end of a number read, "8%" for 4.8; look-alike digits, "1,8%" for 4.8). One case is not: a stray extra
  digit ("115.5 U.S. Gallons" read for 15.5 on a keg label) still gives Does not match. Guarding it would also hide
  real differences (45% vs 45.3%, 750 mL vs 1750 mL), so it is left as a known limit: 1 of 262 real labels in the
  2026-10-09 run.
- **Open judgment calls**: whether a clearly different stated country ("PRODUCT OF CANADA" for Mexico) should be Does not
  match (today Please check), and whether a street address on the application must also be on the label (city and state
  are what § 5.66 requires; today Please check).

## How it is tested

| Test | What it proves | Size |
|---|---|---|
| Rule tests (`tests/test_rules.py`) | Each rule in RULES.md, written before the code and mutation-checked | 74 |
| Edge cases (`tests/test_edge_cases.py`) | What an agent might type and what the reader might produce: spaces, missing letters, stray s, commas, apostrophes, dashes, accents, units, decimal commas, look-alike digits, contradicting readings | 630 |
| Typed values (`tests/test_typed_values.py`) | "45% Alc", "45% AL", "45,0" all mean 45; proof and ranges are refused, not guessed | 33 |
| Batch reading (`tests/test_batch_read.py`, in a browser) | Excel/Numbers exports, encodings, header spellings, ZIP layouts, file-name pairing | 47 |
| Whole pipeline (`tools/evaluate.py`) | Every wrong "Does not match" on real approved labels and every planted mistake that slipped through; timing | 160 practice labels |
| Final test (`--final`) | The same, once, on labels kept apart from all tuning | 28 real + 48 generated, run on Oct 13 |

## Test data

| Data | Status |
|---|---|
| 92 real approved labels from the TTB Public COLA Registry (64 practice, 28 final test), answer key reviewed | Built and used |
| 144 generated labels with planted mistakes (wrong alcohol, changed warning words, title-case heading, …), from 36 label designs | Built and used (96 practice, 48 final test; split by design, so no final-test design is seen in practice) |
| 312 photo-style copies of real labels (blur, glare, tilt, low light) and 808 rotated copies | Built; used to measure the reader, not yet in the regular scorecard |
| 44 real bottle photos (Open Food Facts; 32 practice, 12 final test) | Collected; not yet in the regular scorecard |
| 78 more real approved labels from the registry (collected 2026-10-04) | Built and used; answer key checked against the images with AI assistance |
| 85 more real approved labels (40 beer, 27 spirits, 18 wine; one per brand and company), fetched 2026-10-09 | Built and used; answer keys await the owner's review |
| 180 real approved labels with one planted change (alcohol, size, proof, a warning word changed or deleted, title-case heading, brand), in two sets (`tools/make_tampered.py`) | Built and used: no changed item came back Matches |
| 76 photo-style pictures of 35 real labels (angles up to 45°, close-ups, cans), and 54 of generated labels; the label pixels are ours, only the scene is drawn by an image model (`tools/make_scenes.py`) | Built; the real-label set is used. Letting an image model draw the label itself rewrites its text, so those images can't be scored. |
