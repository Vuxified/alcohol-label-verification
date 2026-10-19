# Results in detail

The headline numbers are in the [README](../README.md#results). This page has every measurement, the changes made after the final test, and how the answer key was made.

## Practice sets

I measured these with `tools/evaluate.py` on the practice sets (I kept the final-test set apart and ran it once). Three numbers matter: **wrong answers** (must be 0), **mistakes caught**, and **items confirmed automatically** (the rest are Please check, for the agent).

| Practice set | Wrong answers | Mistakes caught | Items confirmed |
|---|---|---|---|
| 227 real TTB-approved labels (64 + 78 + 85, from the registry) | **0** "Does not match" | – | 77% / 76% / 71% |
| 178 real approved labels with one planted change (alcohol, size, proof, a warning word, title-case heading, brand) | **0** changed items "Matches" | **178 of 178** flagged; 158 named exactly | 69% / 68% |
| 96 generated labels, 64 with planted mistakes | **0** "Matches" on a mistake | **64 of 64** flagged; 61 named exactly | 93% |
| 76 photo-style pictures of 35 real labels (angles, close-ups, cans) | **0** "Does not match" | – | 30% (photos are hard; most items say Please check) |

- Health warning confirmed word for word on approved labels: 51 of 64, 63 of 78, 57 of 85. One approved label really prints the warning differently from 27 CFR 16.21 ([`FINDINGS.md`](FINDINGS.md)); it is reported apart.
- Speed (laptop, 4 cores): typical 1.6–2.1 s, slowest 4.3 s per label (5.1 s for a photo).
- Pictures only, on 142 approved labels: 0 Does not match; class found on 135, net contents 126, bottler 107, alcohol content 106 (+9 beer, where it is optional). Reading on upload showed alcohol right 103 times (wrong 3) and net contents right 115 (wrong 15); the brand, read by Amazon Nova Pro on all 227 approved labels, was exact on 142, right or close on 188 ("CORONADO" for CORONADO BREWING CO.), and another name on 39, mostly the product's own name ("WEEKEND VIBES"); the local text reader found it on 95 at best. About 2 seconds, while the text is read.
- The new label rules (class minimums, bottled in bond, table wine, low/no-alcohol wording) said Please check on 0 of the 227 approved labels.
- Measured 2026-10-14, run g14 ([`docs/evidence/practice_run.log`](evidence/practice_run.log)); the same run is the one the safety gate approved for the live version. The answer keys of the 85 newest labels were drafted with AI assistance and I reviewed them.

**Final test (held-out labels, run once, 2026-10-12, on the live version ef13fdb):** numbers exactly as measured ([`docs/evidence/final_test.log`](evidence/final_test.log)).

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

**After the final test** (it was not run again), my code review and hands-on testing led to these changes, each approved by a full practice run (live version ce956b7; see the last item for its run):
- A different number or product word in a name or class needs the second reader before it is Does not match; Pinot Gris/Grigio, Syrah/Shiraz and Muscat/Moscato are not different products; the importer statement must be one phrase ("Imported by …"). Each can only turn an answer into Please check.
- The type of product may be left blank and is then told from the label (the result says so); with pictures only, the brand is read by AI and shown for the agent to confirm (never used to call a typed brand Matches).
- Clearer wording on the form, and each batch row opens a side panel with its pictures and every item.
- Text printed beside the warning in its own column is painted over before the warning is re-read, so it is no longer taken for words added to the warning (a word really added sits a word space from the warning's words and is never painted over).
- "Hard tea" and "hard lemonade" are told as malt beverages. If no product type can be told from the label, the page says so as soon as the pictures are added and keeps them, instead of losing them on Check label.
- More is read from the label when nothing is typed (measured on the 227 approved labels, all pictures): the product type is told on 225 (0 wrong; also from "Brewed by", "Proof", "Winery", and alcohol over 24%), alcohol content 178 of 221 (up from 164; misread wording like "13.5% Ale./Vol." and two readings settled by the proof), country 59 of 78 imports (up from 48: "Wine of Australia", "Hecho en México"). Class or type shows the designation line, not a sentence or the company. With one picture only, the result says the back and neck are needed too.
- A typed brand is Matches when the label prints it with company words or an amount beside it ("BULLEIT DISTILLING CO.", "CROWN ROYAL 40% ALC/VOL"), or when the second reader sees a misread brand exactly at that spot; never when the label also shows a close but different version of it. Brand Matches on the approved labels: 128 of 227, up from 119.
- The brand read by AI (nothing typed) can be wrong, so it is "On the label" only when the local text reader also finds those words on the label; otherwise it is Please check and the agent decides. On the 227 approved labels: 119 "On the label" (101 right or close; 18 another name that is printed on the label, such as the product's own name, hence "check it is the brand"), 108 Please check (81 of them right: logos the text reader can't read). A word printed beside the warning's lines, with both zoom-in readings clean at that spot, is no longer taken for an added word (1 approved label fixed). Practice run g16 (2026-10-18, [`docs/evidence/practice_run_g16.log`](evidence/practice_run_g16.log)): 0 wrong Does not match, 0 wrong Matches, every planted mistake flagged. Its timing check was not met because the laptop running it was in Low Power Mode (every set ran about twice as slow as on 2026-10-15, including the generated labels the change does not touch); speed was measured on the live site instead: 2.5 to 5.1 seconds of checking for 12 approved labels with nothing typed (the 5.1 s labels hit the warning's 5-second reading deadline).

**How I made the answer key:** I drafted label values with AI tools and cross-checked by two independent vision models. I reviewed every final-test label and the 85 newest practice labels by hand against their images; I checked the other practice labels against every image with AI assistance. Each answer sheet in `data/ground_truth/` records who reviewed it. In that review, the vision models' disagreements were almost always the models' own errors (invented addresses and container sizes), which is why I never let a model decide in the app.
