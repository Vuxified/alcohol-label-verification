# Approaches considered

Tools and techniques that are popular for reading labels and documents, what we did with each, and why. The two rules that decide most of these: **the app must never say "Matches" when the label differs** (so nothing that can invent text may influence a verdict), and **it must answer in about 5 seconds and be able to run behind an agency firewall**.

## Adopted

| Idea | How it's used here |
|---|---|
| **Measure boldness instead of asking a model** | The "GOVERNMENT WARNING" heading's stroke thickness is measured against the warning text after it (`app/bold.py`). Advisory: Matches or Please check only. |
| **Stress-test photos** (glare, blur, tilt, bottle curve; albumentations) | 312 photo-style copies of the real labels and 808 rotated or tilted copies (`tools/augment_photos.py`), used to measure accuracy on bad photos rather than guess it. |
| **Spec first, tests first** | `docs/RULES.md` is the spec, with a regulation cited for every rule; each rule has unit tests written before the code, and the tests were mutation-checked (breaking a rule must fail a test). |
| **Regression testing on every change** | `tools/evaluate.py` runs the whole pipeline on the practice set and lists every wrong "Does not match" on approved labels and every planted mistake that slipped through. The final-test set is kept apart and run once. |
| **Find mistakes in the answer key** | Every answer sheet was cross-checked by two independent vision models; each disagreement was resolved by a person or by checking every image. Who reviewed each sheet is recorded in the sheet. |
| **Independent code review** | A separate reviewer that did not write the code audited it against the hard rules above (2026-10-08). It found 16 issues, including three ways a wrong "Matches" could happen (an added word in the warning; a one-character difference in a long name; name and address treated as not found = mismatch). All three and most others were fixed test-first; see the commits on 2026-10-08. |

## Considered and not used

| Idea | Why not |
|---|---|
| **Cloud vision-language models reading the fields** (with an OCR cross-check) | Tested on Amazon Bedrock on 2026-10-04 against labels with tampered warnings: three models never accepted a tampered warning, but one accepted 12 of them as correct. While building the answer key, the models also invented addresses and container sizes that are not on the labels. And a cloud model can't run behind an agency firewall. Since the app already knows what each field should say, it does not need a model to decide which text is the brand: it searches for the expected value. Models are used only offline, to draft the answer key for a person to check. |
| **AI upscaling of blurry or small photos** (Real-ESRGAN and similar) | These models create plausible detail that wasn't captured. An invented letter could turn a real mistake into a false "Matches". The app enlarges crops with ordinary interpolation instead, and when a picture is too blurry or small it says so (`app/quality.py`). |
| **Cutting the label out of a bottle photo** (Segment Anything 2) **and flattening curved bottles** (DocTr, UVDoc) | Agents review the label **artwork** submitted with an application, which is already flat and cropped. These steps help phone photos of bottles, and would cost several seconds per image on CPU against a 5-second budget. Curved lines that are part of a label's design are not bottle curvature, so flattening doesn't help them. A good candidate if phone photos become the main input. |
| **PP-OCR (PaddleOCR)** | Excluded by this project's model-provenance policy. OnnxTR (docTR models) plus Tesseract were chosen after measuring speed and accuracy on the practice labels. |
| **Structured-output libraries and LLM tracing** (instructor, Langfuse) | They serve apps that call language models at run time; this app doesn't. The answer-key drafting tool validates the models' structured output before saving it. |
| **Prompt evaluation frameworks** (promptfoo) | Designed for testing prompts; there are no prompts in the app. `tools/evaluate.py` plays the same role for this pipeline. |
| **Automatic label-error detection** (cleanlab) | Needs a trained classifier's probabilities over many examples; with 255 real labels, every disagreement was reviewed directly instead. |
