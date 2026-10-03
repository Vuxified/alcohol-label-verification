"""Verification rules: pure functions, no I/O. See docs/RULES.md."""

from .model import Application, FieldResult, Report, Verdict
from .verify import verify

__all__ = ["Application", "FieldResult", "Report", "Verdict", "verify"]
