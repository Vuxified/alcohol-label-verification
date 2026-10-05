"""Alcohol content and proof (RULES.md §3; 27 CFR 4.36, 5.65, 7.65)."""

import re
from dataclasses import dataclass

from .model import Application, FieldResult, Verdict

_NUM = r"(\d{1,2}(?:\.\d{1,2})?)"
# "45% Alc./Vol.", "Alc. 45% by vol", "45 percent alcohol by volume", "40 ALC/VOL",
# "Alcohol by volume: 45%", "ALC. 13% BY VOL."
_ABV_PATTERNS = [
    re.compile(rf"{_NUM}\s*(?:%|percent)\s*(?:alc(?:ohol)?\.?(?:\s*(?:/|by)\s*vol(?:ume)?\.?)?|abv|vol(?:ume)?\.?)", re.I),
    re.compile(rf"(?:alc|alcohol)\.?\s*(?:by\s*vol(?:ume)?\.?\s*:?\s*)?{_NUM}\s*(?:%|percent)", re.I),
    re.compile(rf"{_NUM}\s*(?:%|percent)?\s*alc\.?\s*/\s*vol", re.I),
    re.compile(rf"\babv\s*:?\s*{_NUM}\s*%", re.I),
]
_PROOF = re.compile(r"(\d{2,3}(?:\.\d{1,2})?)\s*°?\s*proof", re.I)
MAX_PROOF = 200  # 100% alcohol
_TABLE_WINE = re.compile(r"\b(table|light)\s+wine\b", re.I)
_ABV_ABBREVIATION = re.compile(r"\babv\b", re.I)


@dataclass
class AbvReading:
    value: float
    text: str


def find_abv(text: str) -> list[AbvReading]:
    found = {}
    for pattern in _ABV_PATTERNS:
        for m in pattern.finditer(text):
            value = float(m.group(1))
            if 0 < value <= 95:
                found.setdefault((value, m.start()), AbvReading(value, m.group(0).strip()))
    return list(found.values())


def find_proof(text: str) -> list[float]:
    return [float(m.group(1)) for m in _PROOF.finditer(text)]


def check_abv(app: Application, lines: list[str]) -> FieldResult:
    text = " ".join(lines)
    readings = find_abv(text)
    if app.abv is None:
        if app.beverage_type == "spirits":
            return FieldResult("abv", Verdict.CHECK, "Alcohol content is required on spirits, but the application leaves it blank.",
                               code="ABV_NOT_DECLARED")
        return FieldResult("abv", Verdict.NOT_APPLICABLE, "No alcohol content declared; not checked.")

    matching = [r for r in readings if abs(r.value - app.abv) < 0.05]
    if matching:
        hit = matching[0]
        if app.beverage_type == "wine" and _ABV_ABBREVIATION.search(hit.text):
            return FieldResult("abv", Verdict.CHECK, f'"{hit.text}" uses "ABV", which TTB does not allow on wine labels.',
                               code="ABV_ABBREVIATION", found=hit.text)
        return FieldResult("abv", Verdict.PASS, f'Label says "{hit.text}".', found=hit.text)
    if readings:
        shown = readings[0]
        return FieldResult("abv", Verdict.FAIL,
                           f'Label says "{shown.text}". Application says {app.abv:g}%.',
                           code="ABV_MISMATCH", found=shown.text)
    if app.beverage_type == "wine" and app.abv <= 14 and _TABLE_WINE.search(text):
        return FieldResult("abv", Verdict.PASS,
                           'No alcohol content on the label; allowed at 14% or less because it says "table wine" (27 CFR 4.36).')
    return FieldResult("abv", Verdict.CHECK, f"No alcohol content found on the label. Application says {app.abv:g}%.",
                       code="ABV_MISSING")


def check_proof(app: Application, lines: list[str]) -> FieldResult:
    """Spirits only: if proof is shown it must be twice the alcohol by volume (27 CFR 5.1, 5.65)."""
    if app.beverage_type != "spirits":
        return FieldResult("proof", Verdict.NOT_APPLICABLE, "Proof applies to spirits only.")
    text = " ".join(lines)
    proofs = find_proof(text)
    if not proofs:
        return FieldResult("proof", Verdict.NOT_APPLICABLE, "No proof shown (optional).")
    abvs = [r.value for r in find_abv(text)] or ([app.abv] if app.abv is not None else [])
    if not abvs:
        return FieldResult("proof", Verdict.CHECK, f"Proof {proofs[0]:g} shown, but no alcohol content to compare it to.",
                           code="PROOF_UNCHECKED")
    if all(p > MAX_PROOF for p in proofs):  # a misread, e.g. "82.6" read as "826"
        return FieldResult("proof", Verdict.CHECK, f"Proof read as {proofs[0]:g}, which is not possible. Please look.",
                           code="PROOF_MISMATCH")
    if any(abs(p - 2 * a) < 0.15 for p in proofs for a in abvs):
        return FieldResult("proof", Verdict.PASS, f"{proofs[0]:g} Proof is twice the alcohol content.")
    return FieldResult("proof", Verdict.FAIL,
                       f"Label says {proofs[0]:g} Proof, but {abvs[0]:g}% alcohol is {2 * abvs[0]:g} Proof.",
                       code="PROOF_MISMATCH")
