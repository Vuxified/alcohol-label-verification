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
| **A different number needs two readers.** A different alcohol content or net contents is Does not match only when Tesseract, re-reading that spot, sees the same different number. | One misread digit must not fail a real label: a beer printed "6.5%" was read "5.5%" in its display font. | Trusting one reading: a wrong Does not match on an approved label. |
| **Two word readers on every word**: the stock reader and one fine-tuned on label words; the more confident reading wins. | The fine-tuned reader alone fixed the display fonts but broke some ordinary words (BACARDI, GOVERNMENT); together they keep the fixes and almost none of the breaks ([Reader training](#reader-training)). | The fine-tuned reader alone, or a larger stock reader (parseq: about as accurate, 38 times slower per word). |
| **A stray word in one warning reading is noise** when two other readings show that spot clean. | One noisy reading ("thf", "kof") used to put the whole warning on Please check. A really inserted word is in most readings, so it is still caught. | Ignoring added words: "beverages does not impair" must never pass. |
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
- **Type size**: the rule sets a minimum *type size*, a picture shows *letter height* (capitals are about 70% of the
  type size). The app measures the capitals when the agent gives the label height, says Matches only if the capitals
  alone reach the minimum, Please check only if they are clearly too small either way, and otherwise "not confirmed"
  with the measured size. Most approved labels print right at the minimum, so it often can't settle it.
- **TTB practice where it stretches a rule**: some approved labels lack the warning's final period, or show metric-only
  beer sizes with a qualification. The app says Please check there ([FINDINGS.md](FINDINGS.md)).
- **Reading limits**: script logos and very small or curved text are often unread, so those items say Please check.
  How often that happens on a grader's own labels is unknown until they try.
- **A misread that looks like a real difference**: digit misreads that keep the number plausible are guarded
  (only the end of a number read, "8%" for 4.8; look-alike digits, "1,8%" for 4.8), and a different alcohol content or
  net contents now needs Tesseract to see the same different number. Before that rule, 1 of 262 real labels (a keg
  read "115.5 U.S. Gallons" for 15.5) came back Does not match; in the 2026-10-09 run with it, 0 of 262.
- **Open judgment calls**: whether a clearly different stated country ("PRODUCT OF CANADA" for Mexico) should be Does not
  match (today Please check), and whether a street address on the application must also be on the label (city and state
  are what § 5.66 requires; today Please check).

## How it is tested

| Test | What it proves | Size |
|---|---|---|
| Rule tests (`tests/test_rules.py`) | Each rule in RULES.md, written before the code and mutation-checked | 74 |
| Edge cases (`tests/test_edge_cases.py`) | What an agent might type and what the reader might produce: spaces, missing letters, stray s, commas, apostrophes, dashes, accents, units, decimal commas, look-alike digits, contradicting readings | 657 |
| Typed values (`tests/test_typed_values.py`) | "45% Alc", "45% AL", "45,0" all mean 45; proof and ranges are refused, not guessed | 35 |
| Batch reading (`tests/test_batch_read.py`, in a browser) | Excel/Numbers exports, encodings, header spellings, ZIP layouts, file-name pairing, the label-height column | 53 |
| Safety rules (`test_second_reading.py`, `test_warning_noise.py`, `test_word_pair.py`) | A different number needs a second reader; warning noise vs real inserted words; two word readers | 15 |
| Type size (`tests/test_type_size.py`) | Letter height measured on labels drawn at a known size; the three outcomes; the form | 28 |
| Pictures only (`tests/test_picture_only.py`, `test_picture_only_web.py`) | Blank items looked for on the label; never Does not match; "Fill in from the label" on the real reader | 22 |
| Label rules (`tests/test_label_rules.py`) | Class minimums, bottled in bond, table wine, low/no-alcohol wording, each with its section; liqueurs and mixed drinks skipped | 15 |
| Safety gate and no network (`tests/test_gate.py`, `tests/test_offline.py`) | The gate refuses a run of other code, a partial run, any wrong answer, an unflagged mistake, slow labels; the reader starts and checks a label with every network call failing | 11 |
| Whole pipeline (`tools/evaluate.py`) | Every wrong "Does not match" on real approved labels and every planted mistake that slipped through; items confirmed; timing | 538 practice items (227 real labels, 180 tampered, 96 generated, 35 labels in photo scenes) |
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

## Reader training

The stock word reader (OnnxTR `crnn_mobilenet_v3_small`) misreads some label fonts: "BEVERABES" for BEVERAGES,
"GOYERNMENT", "ALCAVOL" for ALC/VOL in tall condensed type. It was fine-tuned (`tools/make_reader_data.py`,
`tools/train_reader.py`, on an AWS GPU) on:

- **Real word pictures** cut from the 64 original practice labels and their tampered copies, each named with the true
  word from the answer key. A word the stock reader got wrong becomes a lesson only when Tesseract, reading the same
  picture on its own, agrees with the answer key, and never for a punctuation-only difference, so the reader learns
  real letters, not guesses ("ALC./VOL" must never be taught as "ALC/VOL").
- **Damaged copies** of those (blur, low resolution, JPEG, noise, black-and-white, inverted, slight turn).
- **Drawn words** in 34 fonts: label words, numbers and units, and *misspelled words and random letters*, so it keeps
  reading letters as printed instead of correcting toward familiar words (important for spotting altered warnings).

Measured on 3,956 words from 1 in 6 practice labels kept out of training (punctuation and capitals ignored, as the
rules do): stock 3,915 right; fine-tuned alone 3,911 (fixes 22, breaks 26: it learned the condensed fonts and slipped
on some ordinary words); **both readers, more confident wins: 3,930 (fixes 17, breaks 2)**. Misspelled drawn words in
fonts never trained on are read as printed at least as well as by the stock reader (2,885 vs 2,878 of 3,000). In the
whole app on labels never used in training: wrong answers stayed 0; items confirmed rose a little (cola2 66.5% →
67.5%), most of the remaining Please checks have other causes (logos, warning text mixed with neighbouring text, items
not found). Also tried and not kept: more training data plus "don't forget" training (too timid: fixes 9, breaks 11),
two other partner readers (fewer fixes), and larger stock readers (parseq is as accurate but 38 times slower per word).
