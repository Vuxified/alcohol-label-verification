# Requirements and Where They're Met

Every requirement below comes from the assignment brief: the stakeholder interviews, the technical notes and the deliverables. Each row says how the prototype meets it and how to verify that. Status is kept current as work lands.

**Status key:** ✅ done and verified · 🔨 in progress · ⏳ planned · ➖ out of scope by design (with reason)

## From the stakeholders

| # | Requirement | Who said it | How it's met | Status | How to verify |
|---|---|---|---|---|---|
| R1 | Results in **about 5 seconds** or nobody will use it | Sarah Chen | Local OCR models chosen by benchmark; all images of an application read in parallel; models loaded once at startup | 🔨 2.1 s median / 3.8 s p95 per application measured locally; must re-measure on the deployed server | `python tools/benchmark_ocr.py`; latency shown on every result |
| R2 | Usable by someone with little tech comfort ("my mother could figure it out"); clean, obvious, no hunting for buttons | Sarah Chen | One screen, one primary button, large text and targets, plain-language results (Matches / Does not match / Please check) built on the U.S. Web Design System | ⏳ | Screenshot in README; accessibility check |
| R3 | **Batch upload** for 200–300 applications at once | Sarah Chen (Janet, Seattle) | ZIP of images + CSV of application data, live progress, results CSV | ⏳ | 300-application run in the README |
| R4 | Standalone proof of concept; **no COLA integration** | Marcus Williams | Runs on its own; JSON API documented so a .NET system could call it later | ⏳ | API docs at `/docs` |
| R5 | Nothing sensitive stored; "don't do anything crazy" with security | Marcus Williams | Images processed in memory only; no database; logs never contain label images or text | ⏳ | Code review; production notes in README |
| R6 | Network **blocks outbound traffic** to many cloud domains | Marcus Williams | Default mode makes zero outbound calls: OCR runs on the server, all page assets self-hosted. Optional cloud second opinion is off by default | 🔨 OCR runs locally (benchmark); app not yet built | Run with networking disabled |
| R7 | Brand names that differ only in case/punctuation ("STONE'S THROW" vs "Stone's Throw") should match: **judgment, not pattern matching** | Dave Morrison | Normalized comparison; near matches go to "Please check" for a person to decide | ✅ | `pytest -k brand_matching`; [RULES.md §2](RULES.md) |
| R8 | Don't make agents' work harder | Dave Morrison | Never stricter than TTB: approved real labels must not be failed; every result shows its evidence and reason | ✅ for rules (0 fails on real approved labels); ⏳ for UI | `pytest tests/test_datasets.py`; [FINDINGS.md](FINDINGS.md) |
| R9 | Government warning must be **exact, word for word**, with "GOVERNMENT WARNING:" in **all caps** (title case is rejected) | Jenny Park | Word-by-word comparison with 27 CFR 16.21; caps checked on the raw text before any normalization | ✅ | `pytest -k warning`; [RULES.md §5](RULES.md) |
| R10 | "GOVERNMENT WARNING:" must be **bold** | Jenny Park | Stroke-thickness comparison of heading vs body; Pass or Please check only, because OCR can't confirm bold reliably and TTB has approved fully bold warnings | ⏳ | [RULES.md §5.3](RULES.md) |
| R11 | Catch warnings in **smaller font** / tiny text | Jenny Park | Letter height measured in mm using the label's real dimensions from the COLA form; advisory, since TTB states it doesn't review type size | ⏳ | [RULES.md §5.3](RULES.md) |
| R12 | Handle **imperfect photos**: weird angles, bad lighting, glare ("maybe out of scope") | Jenny Park | Image quality check returns specific reasons ("glare over the warning") instead of guessing; rotation and light-on-dark text handled | ⏳ | Tested on 312 photo-style copies + 44 real photos |

## From the technical notes

| # | Requirement | How it's met | Status |
|---|---|---|---|
| T1 | Requirements vary by beverage type (beer, wine, spirits) | Rules are beverage-type aware: wine at 14% or less may omit alcohol content with "table wine"; beer net contents in U.S. units; proof is spirits only | ✅ |
| T2 | Check brand name, class/type, alcohol content, net contents, name/address, country of origin for imports, Government Health Warning | All seven checked; see [RULES.md](RULES.md) | ✅ rules · ⏳ from images |
| T3 | Handle labels like the sample (OLD TOM DISTILLERY, Kentucky Straight Bourbon Whiskey, 45% Alc./Vol. (90 Proof), 750 mL) | The sample is a test case and passes every field, including proof = 2 × alcohol content | ✅ |
| T4 | Create or source test labels | 92 approved labels from TTB's public COLA registry, 44 real bottle photos, 144 synthetic labels with known defects, 312 photo-style copies | ✅ |

## Deliverables

| # | Deliverable | Status |
|---|---|---|
| D1 | Source code repository | ✅ |
| D2 | README with setup and run instructions | 🔨 |
| D3 | Documentation of approach, tools used, assumptions made | 🔨 [RULES.md](RULES.md), [FINDINGS.md](FINDINGS.md), this file |
| D4 | Deployed application URL, working prototype | ⏳ |
| D5 | Trade-offs and limitations documented | 🔨 [RULES.md §7](RULES.md) |

## Assumptions (where the brief leaves gaps)

1. **Application data** is entered in a form (one label) or a CSV (batch).
2. An application may have **several images** (front, back, neck), as in the COLA registry. The warning is usually on the back.
3. **Alcohol content and net contents** are compared when the application provides them. The real COLA form (TTB F 5100.31) has no fields for them, but the brief's example treats them as application data.
4. **All three beverage types** are in scope.
5. Reviewers can reach a mainstream cloud domain to open the demo.
