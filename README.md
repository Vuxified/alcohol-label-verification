# Alcohol Label Verification

Prototype that checks alcohol label images against their label application (TTB COLA data) and reports, field by field, **Matches / Does not match / Please check**, with the evidence.

Work in progress. Current state:

- `docs/RULES.md`: the verification rules, with citations to 27 CFR Parts 4, 5, 7 and 16.
- `data/`: test data. Includes 92 approved labels from TTB's Public COLA Registry, 44 real bottle photos (Open Food Facts, CC BY-SA), 144 synthetic labels with known defects, an answer key, and a frozen development / held-out split.
- `tools/`: the scripts that collect and generate the data, plus the OCR speed benchmark.

Setup for the tools:

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements-tools.txt
```
