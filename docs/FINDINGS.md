# What Real Labels Taught Us

The first version of the rules followed the regulations to the letter. Running them against real labels that TTB has **approved** showed three places to look at closely. Two were cases where the letter of the rule was stricter than TTB's practice; one turned out to be a real deficiency that TTB approved only with a condition. A tool that rejects approved labels would lose agents' trust immediately, so each rule was changed to **Please check**: the tool flags it and a person decides.

Every case below can be verified independently: the TTB ID opens the public registry record, which shows the approved label images.

Registry record link pattern: `https://www.ttbonline.gov/colasonline/viewColaDetails.do?action=publicFormDisplay&ttbid=<TTB ID>`

---

## 1. Beer labeled only in metric units: a real deficiency, flagged by TTB too

**The regulation.** 27 CFR 7.70(c): "Metric measures may be used in addition to, but not in lieu of, the U.S. customary units of measurement." For a container under one pint, net contents "must be stated in fluid ounces" (7.70(a)(1)).

**The approved label.** Guinness Foreign Extra Stout, imported from Nigeria. TTB ID **23328001000154**, approved 01/08/2024. Both label images state the contents only as **"325ml"** / **"325 ML"**. No fluid ounces appear anywhere.

![Guinness back label: 7.5% ALC/VOL, 325ml](evidence/guinness_325ml.png)

**What TTB did.** It approved the label **with a qualification** attached to the certificate:

> "When labels are printed the net contents must include "FL" (fluid ounces) in your statement. Example 12 fl. oz. or 12 fluid ounces. See 27 CFR 7.70"

Item 15 of the application ("show any information that is blown, branded, or embossed on the container (e.g., net contents)") is **empty**, so the ounces are not molded into the bottle either.

**What this means.** It's a real deficiency. TTB's agent caught it and approved on the condition that it be fixed, rather than rejecting the label. That is exactly the kind of finding the tool should surface.

**Rule.** Metric-only net contents on a malt beverage → **Please check**, with the reason stating the 7.70(c) requirement and that TTB conditions approval on adding fluid ounces. It is not "Matches", and it is not an outright rejection, because TTB's own practice here is approval with a qualification. Net contents not found on any label image is also **Please check**, since 27 CFR 7.63(a)(5) allows them to be molded into the container (declared in item 15).

**Lesson for the dataset.** TTB's "Qualifications" field records what its agents flagged on approved labels. It is a source of real deficiencies to test against.

---

## 2. Warning statement missing a period

**The regulation.** 27 CFR 16.21 gives the exact statement, including a period after "birth defects" and at the end ("…may cause health problems.").

**The approved labels:**

| Label | TTB ID | Approved | What's printed |
|---|---|---|---|
| [ yellow tail ] Moscato | **24061001000635** | 03/05/2024 | "…OF BIRTH DEFECTS (2) CONSUMPTION…": no period after DEFECTS |
| [ yellow tail ] Cabernet Sauvignon | **24061001000628** | 03/07/2024 | Same: no period after DEFECTS |
| Robert Mondavi Winery sparkling wine | **24053001000106** | 02/26/2024 | "…MAY CAUSE HEALTH PROBLEMS": no final period |

![yellow tail Moscato: no period after BIRTH DEFECTS](evidence/yellowtail_moscato_no_period.png)

![yellow tail Cabernet Sauvignon: no period after BIRTH DEFECTS](evidence/yellowtail_cabernet_no_period.png)

![Robert Mondavi: no period after HEALTH PROBLEMS](evidence/mondavi_no_final_period.png)

**Rule change.** Every **word** must still match exactly; a changed, missing or added word is Does not match. A **punctuation-only** difference is **Please check**. This keeps the strictness where the rule's purpose is (the wording of the health message, and the all-caps heading Jenny described) without rejecting labels TTB accepts. OCR also misreads small punctuation more often than words, which is another reason not to reject on it.

---

## 3. Non-alcoholic beer has no warning

**The regulation.** The Health Warning is required on "alcoholic beverages," which 27 CFR 16.10 defines as containing "not less than one-half of one percent (.5%) of alcohol by volume."

**The approved label.** Heineken 0.0, TTB ID **24165001000500**, approved 06/20/2024, class "Cereal Beverages – Near Beer (Non Alcoholic)". The label states **"ALC. 0.0% BY VOL."** and carries no Government Warning, correctly.

![Heineken 0.0: ALC. 0.0% BY VOL.](evidence/heineken_00_abv.png)

**Rule change.** When the application declares less than 0.5% alcohol, the warning and alcohol-content checks are skipped (shown as "not applicable", with the reason).

---

## How this is enforced going forward

`tests/test_datasets.py::test_real_approved_label_never_fails` runs the rules on every real approved label in the development set and fails if any field gets "Does not match". It caught cases 1 and 3 when the rules were first run. Case 2 was spotted earlier, while building the answer key, so the punctuation rule was written lenient from the start; the test now guards it. Any future case like these will fail the test until it's resolved.
