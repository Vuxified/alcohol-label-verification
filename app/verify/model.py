"""Data types shared by the verification rules."""

from dataclasses import dataclass, field
from enum import Enum


class Verdict(str, Enum):
    PASS = "pass"            # shown as "Matches"
    CHECK = "check"          # shown as "Please check"
    FAIL = "fail"            # shown as "Does not match"
    NOT_APPLICABLE = "n/a"   # rule doesn't apply (e.g. proof on wine)


SEVERITY = {Verdict.NOT_APPLICABLE: 0, Verdict.PASS: 1, Verdict.CHECK: 2, Verdict.FAIL: 3}

BEVERAGE_TYPES = ("spirits", "wine", "malt")


@dataclass
class Application:
    """What the applicant declared. Optional fields are skipped when blank."""
    beverage_type: str
    brand_name: str
    class_type: str | None = None
    abv: float | None = None
    net_contents: str | None = None
    name_address: str | None = None
    source: str = "domestic"            # "domestic" or "imported"
    country_of_origin: str | None = None
    fanciful_name: str | None = None

    def __post_init__(self):
        if self.beverage_type not in BEVERAGE_TYPES:
            raise ValueError(f"beverage_type must be one of {BEVERAGE_TYPES}")


@dataclass
class FieldResult:
    field: str
    verdict: Verdict
    reason: str                          # plain English, shown to the agent
    code: str | None = None              # stable identifier for tests and CSV export
    found: str | None = None             # the label text the verdict is based on


@dataclass
class Report:
    fields: list[FieldResult] = field(default_factory=list)

    @property
    def overall(self) -> Verdict:
        """The worst verdict among the fields."""
        return max((f.verdict for f in self.fields), key=SEVERITY.__getitem__, default=Verdict.PASS)

    def get(self, name: str) -> FieldResult:
        return next(f for f in self.fields if f.field == name)
