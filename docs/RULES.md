# Verification Rules

> Three rules were relaxed after testing against real TTB-approved labels. The evidence is in [FINDINGS.md](FINDINGS.md).

This document is the rulebook the app follows: what it checks, how strictly, and the federal regulation behind each rule. Every rule in `app/verify/` maps to a section here, and every section has tests.

Regulations are cited from Title 27 of the Code of Federal Regulations (eCFR, current as of 2026-09-01): Part 4 (wine), Part 5 (distilled spirits), Part 7 (malt beverages), Part 16 (Health Warning Statement).

---

## 1. Guiding principles

1. **Verify, don't extract.** The application already says what the label should contain. The app reads the label text and checks for those values. It does not guess what a label "means."
2. **Plain code decides.** Every verdict comes from deterministic, tested rules. OCR only supplies the words, their positions, and how confident the reader was.
3. **Three verdicts, and "Please check" is honest.**
   - **Matches:** the expected value was found and agrees.
   - **Does not match:** the label clearly shows a different value (a different number, or a different word read clearly).
   - **Please check:** the app can't be sure (low-confidence read, glare, missing image, or a judgment call). A person decides.
   - **Couldn't find it is never "Does not match".** A value the reader did not find may be in decorative type, on a curved can, or on a side not photographed. That is **Please check**, with what was found. (Owner decision 2026-10-05, after the first full test wrongly failed 34 approved labels this way.)
4. **Never stricter than TTB.** If TTB approves labels that technically stretch a rule, the app does not fail them. Those checks are advisory (§5).
5. **Show the evidence.** Each verdict comes with the crop of the label where the value was found (or should have been) and a plain-English reason, e.g. *"Label says 45% Alc./Vol. Application says 40%."*
6. **The agent decides.** This is an advisory tool. The compliance agent makes the determination.

The overall verdict for an application is the worst verdict among its fields.

---

## 2. Text matching (brand name, fanciful name, class/type, name and address)

Before comparing, both sides are normalized:
- Unicode NFKC; curly quotes and dashes become plain ones; accents removed.
- Case ignored; extra spaces and line breaks collapsed; punctuation ignored except apostrophes inside words.
- Spaces between words don't count: the reader sometimes drops one ("FourRoses" for "Four Roses").
- Written two ways, same meaning: "&" = "and", "St." = "Saint", "Ste." = "Sainte"; ™, ® and ℠ are ignored; a backtick,
  prime or stray space at an apostrophe ("STONE' S") is an apostrophe. A value may wrap across up to four label lines.
- Name and address only: a state's name = its abbreviation ("Kentucky" = "KY"), "Co." = "Company", "St." = "Street";
  a ZIP code on the application is not looked for (§ 5.66 requires city and state); a space the reader dropped
  ("OLDTOM") is forgiven.
- A different number is Does not match only when no digit could be a reading slip: digits readers confuse (0/8, 1/7,
  3/8, 5/6, 6/8, 1/4, 8/9, 5/8) stay Please check, so "10" vs "12" fails but "10" vs "18" asks a person. Every variant
  is a case in `tests/test_edge_cases.py`.

After normalization the label must show **the same text** to match. Close is not the same: in a long name one character can be "10 Year" vs "12 Year", so anything merely similar is **Please check**, showing what was read (changed 2026-10-08 after an independent code review found that a 95% similarity score let one wrong character through). The exception is a **clearly read different number**: when every word is the same and the only difference is one whole number read as another ("10" vs "12"), the result is **Does not match** (owner decision 2026-10-09). The label must be identical to the approved application (§ 5.22(a)), and when the number is an age, stating more than the real age is prohibited (§ 5.74(a)(2)). Anything less clear ("1O" with a letter O, or a different word as well) stays Please check. In the **class/type** only, one product-type word read in place of another ("RYE" for "BOURBON", "RUM" for "GIN", from a fixed list of class/type words) is also **Does not match**: it is a different product, not a reading slip. A near spelling ("BOURBAN") or a word outside the list stays Please check, and brand names never fail on a different word, because decorative lettering can be read as any word.

| After normalization | Verdict |
|---|---|
| Same text | Matches |
| Same words, one whole number different | Does not match |
| Similar (85% or more) | Please check |
| Not found | Please check |

Plus a **word rule**: if the value only appears inside a longer line, the result is **Please check**, showing that line. The longer line may be a different product ("Old Tom Reserve") or simply the bottler line ("BOTTLED BY SUTTER HOME FAMILY VINEYARDS"), which approved labels often carry next to a decorative brand.

| Application | Label | Result | Why |
|---|---|---|---|
| Stone's Throw | STONE'S THROW | Matches | Case only |
| Old Tom Distillery | OLD TOM DISTILLERY | Matches | Case only |
| Old Tom | Old Tom Reserve | Please check | Label adds a word; it could be a different product, so a person looks |
| Sutter Home | BOTTLED BY SUTTER HOME FAMILY VINEYARDS | Please check | Found only inside the bottler line; the brand itself may be decorative |
| Copper Hollow | (not found) | Please check | Never Does not match: the reader may have missed decorative type |
| Stone's Throw | Stone Throw | Please check | Possessive dropped; may be an OCR miss or a real change |
| Eagle Rare 10 Year Old | EAGLE RARE 12 YEAR OLD | Does not match | A clearly read different number (§ 5.22(a), § 5.74(a)(2)) |
| Eagle Rare 10 Year Old | EAGLE RARE 1O YEAR OLD | Please check | Letter O instead of a zero: may be a reading slip |
| Kentucky Straight Rye Whiskey | KENTUCKY STRAIGHT BOURBON WHISKEY | Does not match | Class/type: a different product type word |
| Kentucky Straight Bourbon Whiskey | KENTUCKY STRAIGHT BOURBAN WHISKEY | Please check | Near spelling: may be a reading slip |
| Four Roses | FourRoses | Matches | Only a space differs |
| Kentucky Straight Bourbon Whiskey | KENTUCKY STRAIGHT BOURBON WHISKY | Matches | Class/type only: "the word whisky may be spelled as either 'whisky' or 'whiskey'" (§ 5.143). Brand names get no such allowance. |

**Allowed spelling variants (class/type only):** whisky = whiskey (§ 5.143). This list grows only when a regulation allows a variant; each entry cites its section.

**Class/type code vs. class/type on the label:** the TTB registry's "Class/Type Code" (e.g. OTHER STRAIGHT WHISKY) is a filing category, not the wording the label must carry (e.g. KENTUCKY STRAIGHT MALT WHISKEY). They are never compared word for word; the label wording is checked against the application's class/type statement.

**Name and address:** every word of the application's statement must appear on the label to match; any missing word (a different street or city, or text the reader missed) gives **Please check**, listing the missing words.

**Country of origin (imports):** checks for the country named on the application, e.g. "Product of Ireland." Not found gives Please check (TTB has approved imports whose country appears only in the importer's address or on the container).

**Fanciful name:** checked like the brand name when the application gives one.

---

## 3. Alcohol content

### 3.1 Accepted formats (§ 5.65(b), § 7.65(b), § 4.36)
- "45% Alc./Vol.", "Alc. 45% by vol.", "45 percent alcohol by volume", "Alcohol by volume: 45%"
- "alc" and "vol" may be abbreviated, with or without periods; "%" may replace "percent"; "/" may replace "by".
- **Wine:** "ABV" is not an allowed abbreviation (TTB wine guidance). Seeing it gives **Please check**.
- A comma is a decimal point ("12,5% VOL" on imported labels). A number glued to other characters ("455%", "l2%", "4 5%")
  is not a clear reading, so it is not used. "LESS THAN 0.5%" is a limit, not a value: it fits any declared value below it.
- If the label also shows a *different* clearly read alcohol content, the result is **Please check** (the label
  contradicts itself, or one reading is wrong), never Matches.
- **Two readings for Does not match (alcohol content and net contents).** A different number is Does not match only
  when a second, independent reader (Tesseract) reading the same spot sees the same different number. Otherwise it is
  **Please check**, and the reason shows both readings. Found on a real approved beer (TTB ID 26205001000228): the
  label prints "6.5%", the word reader read "5.5%" in its display font.
- Typed on the application, "45", "45%", "45% Alc", "45% AL", "45,0" and "45% Alc./Vol. (90 Proof)" all mean 45.
  Proof alone ("90 proof"), ranges and other numbers are refused by the form rather than guessed.

### 3.2 Comparison
Label and application values are compared **as numbers** (45, 45.0 and 45.00 are equal). They should match exactly; the regulatory tolerances (±0.3 for spirits and malt, ±1.0/±1.5 for wine) apply to the *liquid vs. the label*, not to the label vs. the application. So any difference between label and application is **Does not match**.

### 3.3 When alcohol content is required

| Type | Rule | Citation |
|---|---|---|
| Distilled spirits | **Always required** | § 5.63(a)(3), § 5.65(a) |
| Wine | Required **above 14%**. At 14% or less it may be left off **if** "table wine" or "light wine" appears | § 4.32(b)(3), § 4.36(a) |
| Malt beverage | Required **only if** alcohol comes from added flavors or other nonbeverage ingredients (e.g. hard seltzers, flavored malt drinks). Otherwise optional | § 7.63(a)(3), § 7.65(a) |

If the application gives an alcohol content and none is found on the label, the result is **Please check** (§1: not found is never Does not match). For a type where alcohol content is optional and the application leaves it blank, the check is skipped.

**Wine tax-class line (§ 4.36(c)):** if one of the label and application values is 14% or less and the other is above 14%, the result is **Does not match**, because those are different tax classes.

### 3.4 Proof (spirits only)
Proof is optional (§ 5.65(b)(1)(i)). If shown, it must equal **2 × alcohol by volume** (§ 5.1): 45% with 90 Proof matches; 45% with 80 Proof does not. A proof over 200 is impossible and means a misread (e.g. "82.6" read as "826"), so it gives **Please check**. Parts 4 and 7 have no proof rules, so proof is ignored for wine and malt beverages.

---

## 4. Net contents

Parsed and converted to milliliters: mL ×1, cL ×10, L ×1000, fl oz ×29.5735, pint (PT) ×473.176, quart (QT) ×946.353. Compound forms are added ("1 PINT 8 FL. OZ." and "1 PT. 8 FL. OZ." = 710 mL). On the application, a bare number takes the usual unit (750 or 1.75 for spirits and wine means mL or L; 12 for beer means fl oz), and "oz", "mls", "ltr", ".75 L" are understood; anything that isn't one amount is refused by the form. On the label, a number right after a lone digit ("7 50 ML", a split "750") is not a clear reading. If the label also shows another clearly different container size, the result is **Please check**; serving statements ("1.5 fl oz") and misreads of the same size ("15L" for "1.5L") don't count. Label and application match if they differ by 0.4% or 1.5 mL, whichever is larger: enough for unit conversion (12 fl oz = 354.9 mL), but 350 mL and 355 mL are different sizes. "1,750 mL" is read as 1750.

| Type | Units | Container sizes | Citation |
|---|---|---|---|
| Distilled spirits | Metric required; U.S. units may be added | Must be an authorized standard of fill: 3.75 L, 3 L, 2 L, 1.8 L, 1.75 L, 1.5 L, 1 L, 945, 900, 750, 720, 710, 700, 570, 500, 475, 375, 355, 350, 331, 250, 200, 187, 100, 50 mL | § 5.70, § 5.203(a) |
| Wine | Metric required; U.S. units may be added | Authorized standards of fill: 3 L, 2.25 L, 1.8 L, 1.5 L, 1 L, 750, 720, 700, 620, 600, 568, 550, 500, 473, 375, 360, 355, 330, 300, 250, 200, 187, 180, 100, 50 mL and any even number of liters from 4 L up (§ 4.72(b)) | § 4.37, § 4.72 |
| Malt beverage | **U.S. units required** (e.g. "12 FL. OZ."); metric may only be added | No standards of fill | § 7.70 |

A size that isn't an authorized standard of fill for spirits or wine gives **Please check**. A malt beverage label with metric units only also gives **Please check**, with the reason stated: it is a real deficiency under 27 CFR 7.70(c), and TTB's practice is to approve with a qualification requiring fluid ounces rather than reject (Guinness Foreign Extra Stout, "325ml", TTB ID 23328001000154; see [FINDINGS.md](FINDINGS.md)).

Net contents not found on any label image gives **Please check**, not a fail, for the same reason (27 CFR 5.63(b)(2), 7.63(a)(5)).

A different amount that rests only on a bare letter "L" (e.g. "1 L") gives **Please check**: on curved cans the reader produces strings like "I 1 1 E 1 L" from noise. A clearly read different amount ("700 mL" for "750 mL") is **Does not match**.

---

## 5. Government Health Warning Statement

Required on every alcohol beverage of 0.5% alcohol by volume or more, for all three types (Part 16). Below 0.5% a product is not an "alcoholic beverage" (27 CFR 16.10), so for a product declared below 0.5% the warning and alcohol content checks are skipped, unless the label itself shows 0.5% or more (a typo such as 0.4 for 40 must not switch the checks off). It may be on the front, back, or side label (§ 16.21), so the app searches **all images** in the application.

### 5.1 Exact text (§ 16.21)

> GOVERNMENT WARNING: (1) According to the Surgeon General, women should not drink alcoholic beverages during pregnancy because of the risk of birth defects. (2) Consumption of alcoholic beverages impairs your ability to drive a car or operate machinery, and may cause health problems.

- **Only line breaks, repeated spaces and words hyphenated across lines are forgiven** (labels wrap text). Every word and number must be present and in order, with no words added ("beverages does not impair" never passes). A changed, missing or added word gives **Does not match** when two independent readings show the same change, and **Please check** when only one does (it may be a reader slip). An added word that only one reading shows, while two other readings show that very spot with nothing between the required words, is reader noise ("thf", "kof") and is ignored; a really inserted word is in most readings (checked by planting inserted words into the saved readings of the practice labels: every one still caught).
- **Punctuation-only differences give Please check**, not Does not match. TTB has approved labels missing a single period in the statement (e.g. [ yellow tail ] Moscato, Robert Mondavi sparkling wine in our test set).
- Differences are shown as a word-by-word comparison with changed words highlighted.
- If the only differences are single characters the OCR read with low confidence, the result is **Please check**, not Does not match. The app shouldn't fail a label because of its own misread.
- Not found → **Please check**, asking for a picture of the side that carries it (§1: not found is never Does not match).

### 5.2 Capital letters (§ 16.22(a)(2))
"GOVERNMENT WARNING" must be in capital letters. This is checked on the **raw** OCR text, before any normalization, so "Government Warning" in title case is caught. The app requires at least 90% of the heading's letters to read as capitals, so one ambiguous glyph doesn't cause a false fail, and shows the crop.

### 5.3 Advisory checks (Pass or Please check only, never Does not match)

**Bold heading (§ 16.22(a)(2)):** "GOVERNMENT WARNING" must be bold, and the rest may not be. The app compares the stroke thickness of the heading to the rest of the statement. Clearly heavier (at least 1.2 times as thick, set on the practice labels: regular headings measured 0.98–1.18, bold ones 1.46–2.31) → Pass. Otherwise → Please check. Too small, sideways or curved to measure → not checked. If the readings disagree on whether the heading is in capitals, the capitals check is Please check. It never fails the bold check, because:
- OCR engines can't report bold reliably.
- TTB has approved labels where the *entire* warning is set in heavy type (for example, a Jack Daniel's back label in our test set, TTB ID 24002001000457).

**Type size (§ 16.22(b)):**

| Container | Minimum letter height | Max characters per inch (§ 16.22(a)(4)) |
|---|---|---|
| 237 mL (8 fl oz) or less | 1 mm | 40 |
| Over 237 mL, up to 3 L | 2 mm | 25 |
| Over 3 L | 3 mm | 12 |

When the label's real size is known (COLA applications list "Actual Dimensions" for every image), the app converts pixels to millimeters and estimates the capital-letter height of the warning. Too small → Please check. Unknown size (e.g. a phone photo) → "type size not checked."

This stays advisory because TTB itself states on every approved COLA:

> "TTB has not reviewed this label for type size, characters per inch or contrasting background. The responsible industry member must continue to ensure that the mandatory information on the actual labels is displayed in the correct type size, number of characters per inch, and on a contrasting background…"

---

## 6. Image quality

Before trusting a reading, the app checks each image and returns **every** problem together, so the agent can request one better image instead of several:
- **Blurry:** low sharpness score.
- **Glare:** too much of the label is washed out, or glare covers the warning.
- **Too small to read:** letters under about 8 pixels tall.
- **Low confidence:** the reader is unsure of too many words in a required field.

Any of these produce **Please check — please request a clearer image**, with the reason. This replaces today's "can't read it, reject it" step with a specific, instant explanation.

Handled automatically: phone rotation (EXIF), white or gold text on dark backgrounds (the app reads both normal and inverted versions), and sideways text (e.g. a vertical warning on a can).

---

## 7. What the app does not check (by design)

These need human judgment or are outside a prototype's scope; the app doesn't pretend otherwise:
- Contrasting background, and "separate and apart" placement of the warning.
- Spirits "same field of vision" (brand, class/type and alcohol content visible together, § 5.63(a)).
- Standards of identity (whether a product actually qualifies as "bourbon," etc.).
- Wine appellation, varietal and vintage percentages; age statements; state of distillation; coloring, sulfite, Yellow No. 5, cochineal and aspartame disclosures. *(Candidates for a later version: they're text-presence checks that fit the same engine.)*
- State-level labeling rules.

---

## 8. How we develop and test against these rules

- **Each rule is a small pure function** in `app/verify/`, with unit tests for the normal case and the known traps:
  - "Government Warning" (title case) → Does not match.
  - "Old Tom" vs "Old Tom Reserve" → Please check; "STONE'S THROW" vs "Stone's Throw" → Matches.
  - 45% + 90 Proof → Matches; 45% + 80 Proof → Does not match.
  - Wine at 13% with "table wine" and no alcohol content → Matches.
  - Malt with metric-only net contents → Please check.
  - Deliberately breaking any rule must make a test fail.
- **Real labels:** about 90 approved labels from TTB's Public COLA Registry (30 each of spirits, wine, and malt beverages, domestic and imported), plus about 44 real bottle photos from Open Food Facts (CC BY-SA).
- **Labels that should fail:** synthetic labels with known answers, covering 10 failure types (wrong alcohol content, wrong net contents, brand mismatch, class/type mismatch, missing warning, title-case warning, non-bold heading, altered warning wording, warning hard to read, type too small).
- **Photo conditions:** copies of real labels with added glare, blur, tilt and bottle curvature.
- **Honest scoring:** the data is split into a development set (used while building) and a held-out set, frozen with a checksum before tuning and run once at the end. The README reports what that run measured: a confusion matrix, the **false-Pass rate** (the number that matters most), per-field precision and recall, and latency on the deployed server.
- **Target on real approved labels: zero "Does not match" results.** They were approved by TTB, so a fail there is our bug.

---

## Sources

- eCFR Title 27: Part 4 https://www.ecfr.gov/current/title-27/part-4 · Part 5 https://www.ecfr.gov/current/title-27/part-5 · Part 7 https://www.ecfr.gov/current/title-27/part-7 · Part 16 https://www.ecfr.gov/current/title-27/part-16
- Key sections: § 5.65 https://www.ecfr.gov/current/title-27/section-5.65 · § 7.63 https://www.ecfr.gov/current/title-27/section-7.63 · § 7.65 https://www.ecfr.gov/current/title-27/section-7.65 · § 16.21 https://www.ecfr.gov/current/title-27/section-16.21 · § 16.22 https://www.ecfr.gov/current/title-27/section-16.22
- TTB wine alcohol content guidance: https://www.ttb.gov/node/883
- TTB Public COLA Registry: https://www.ttb.gov/regulated-commodities/labeling/cola-public-registry
- Open Food Facts (photo licensing): https://world.openfoodfacts.org/terms-of-use
