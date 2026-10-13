# Requirements and Where They're Met

Every requirement below comes from the assignment brief: the stakeholder interviews, the technical notes and the deliverables. Each row says how the prototype meets it and how to verify that. Status as of 2026-10-12.

**Status key:** ✅ done and verified · 🔨 in progress · ⏳ planned · ➖ out of scope by design (with reason)

## From the stakeholders

| # | Requirement | Who said it | How it's met | Status | How to verify |
|---|---|---|---|---|---|
| R1 | Results in **about 5 seconds** or nobody will use it | Sarah Chen | Local OCR models chosen by benchmark; all images of an application read in parallel; models loaded once at startup | ✅ final test: typical 0.7–2.6 s, slowest 4.5 s per label | Time shown on every result; README "Final test" |
| R2 | Usable by someone with little tech comfort ("my mother could figure it out"); clean, obvious, no hunting for buttons | Sarah Chen | One screen, one primary button, large text and targets, plain-language results (Matches / Does not match / Please check) built on the U.S. Web Design System; the label is read as soon as pictures are added | ✅ | Live URL; works at 200% zoom and on a phone |
| R3 | **Batch upload** for 200–300 applications at once | Sarah Chen (Janet, Seattle) | ZIP of images + CSV of application data (up to 500), live progress, needs-attention rows first, results spreadsheet; pictures paired by file name or by reading them | ✅ | Sample batch on the batch page (22 applications) |
| R4 | Standalone proof of concept; **no COLA integration** | Marcus Williams | Runs on its own; JSON endpoints `/api/check` and `/api/read` so another system could call it later | ✅ | `app/web/main.py` |
| R5 | Nothing sensitive stored; "don't do anything crazy" with security | Marcus Williams | Uploads go to private storage and are deleted after one day; no database; results are not stored; logs never contain label images or text | ✅ | README "Deployment" |
| R6 | Network **blocks outbound traffic** to many cloud domains | Marcus Williams | Zero outbound calls: the label is read on the server and all page assets are self-hosted | ✅ | `tests/test_offline.py`; every deploy checks the container with networking switched off |
| R7 | Brand names that differ only in case/punctuation ("STONE'S THROW" vs "Stone's Throw") should match: **judgment, not pattern matching** | Dave Morrison | Normalized comparison; near matches go to "Please check" for a person to decide | ✅ | `pytest -k brand_matching`; [RULES.md §2](RULES.md) |
| R8 | Don't make agents' work harder | Dave Morrison | Never stricter than TTB: approved real labels must not be failed; every result shows its evidence and reason | ✅ 0 Does not match on 255 real approved labels (practice and final test) | `pytest tests/test_datasets.py`; [FINDINGS.md](FINDINGS.md) |
| R9 | Government warning must be **exact, word for word**, with "GOVERNMENT WARNING:" in **all caps** (title case is rejected) | Jenny Park | Word-by-word comparison with 27 CFR 16.21; caps checked on the raw text before any normalization | ✅ | `pytest -k warning`; [RULES.md §5](RULES.md) |
| R10 | "GOVERNMENT WARNING:" must be **bold** | Jenny Park | Stroke-thickness comparison of heading vs body; Matches or Please check only, because OCR can't confirm bold reliably and TTB has approved fully bold warnings | ✅ | [RULES.md §5.3](RULES.md) |
| R11 | Catch warnings in **smaller font** / tiny text | Jenny Park | Letter height measured in mm when the agent gives the label's height (form field or batch column `label_height`); advisory, since TTB states it doesn't review type size | ✅ | [RULES.md §5.3](RULES.md) |
| R12 | Handle **imperfect photos**: weird angles, bad lighting, glare ("maybe out of scope") | Jenny Park | Rotation, light-on-dark and sideways text handled; when an item is unsure, the app says which picture is probably why (small, blurry, no writing). Photos stay safe (0 wrong answers) but leave most items to the agent | ✅ safe · limited | README "Final test" (photo rows) |

## From the technical notes

| # | Requirement | How it's met | Status |
|---|---|---|---|
| T1 | Requirements vary by beverage type (beer, wine, spirits) | Rules are beverage-type aware: wine at 14% or less may omit alcohol content with "table wine"; beer net contents in U.S. units; proof is spirits only | ✅ |
| T2 | Check brand name, class/type, alcohol content, net contents, name/address, country of origin for imports, Government Health Warning | All seven checked from the pictures, plus proof, the importer statement and label rules; see [RULES.md](RULES.md) | ✅ |
| T3 | Handle labels like the sample (OLD TOM DISTILLERY, Kentucky Straight Bourbon Whiskey, 45% Alc./Vol. (90 Proof), 750 mL) | The sample is a test case and passes every field, including proof = 2 × alcohol content | ✅ |
| T4 | Create or source test labels | 255 approved labels from TTB's public COLA registry, 224 copies of them with one planted change, 144 generated labels with known defects, photo-style pictures, 44 real bottle photos; all in `data/` | ✅ |

## Deliverables

| # | Deliverable | Status |
|---|---|---|
| D1 | Source code repository | ✅ |
| D2 | README with setup and run instructions | ✅ |
| D3 | Documentation of approach, tools used, assumptions made | ✅ [APPROACH.md](APPROACH.md), [RULES.md](RULES.md), [FINDINGS.md](FINDINGS.md), this file |
| D4 | Deployed application URL, working prototype | ✅ https://3jirlgdkpcw55t54gz32ggdnbq0yfrjp.lambda-url.us-east-1.on.aws/ |
| D5 | Trade-offs and limitations documented | ✅ README "Limitations and trade-offs", [RULES.md §7](RULES.md) |

## Assumptions

See [APPROACH.md](APPROACH.md#assumptions-where-the-brief-leaves-gaps).
