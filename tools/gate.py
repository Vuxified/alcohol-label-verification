"""The safety gate: may this version go live? (tools/deploy.sh runs it first and stops on any problem.)

A version may go live only after a full practice run (tools/evaluate.py) of exactly the code being shipped, with:
  - no wrong "Does not match" on a TTB-approved label, and no wrong "Matches" on a planted mistake;
  - every label with a planted mistake flagged (not "Matches" overall);
  - 95% of labels in every practice set checked within 5 seconds.
"The code being shipped" is what goes into the container: app/, Dockerfile, requirements.txt. A change to the README
after the run does not need a new run; any change to those does.

Usage: python tools/gate.py [out/eval/<name>.json]      (default: the newest run)
"""

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SHIPPED = ("app", "Dockerfile", "requirements.txt")
REQUIRED = ("cola", "cola2", "cola3", "scene_real", "syn", "tampered", "tampered_x")
SECONDS = 5.0


def shipped_code(rev="HEAD") -> str:
    """One fingerprint of everything that goes into the container at a commit."""
    out = subprocess.run(["git", "rev-parse", *(f"{rev}:{p}" for p in SHIPPED)], cwd=ROOT, capture_output=True,
                         text=True, check=True).stdout
    return "-".join(line[:12] for line in out.split())


def shipped_code_changed() -> bool:
    """Uncommitted edits to the shipped files (the run would not be of any commit)."""
    out = subprocess.run(["git", "status", "--porcelain", "--", *SHIPPED], cwd=ROOT, capture_output=True, text=True,
                         check=True).stdout
    return bool(out.strip())


def p95(xs):
    xs = sorted(xs)
    return xs[max(0, int(round(0.95 * len(xs))) - 1)]


def problems(report: dict, code: str) -> list[str]:
    out = []
    if report.get("code") != code:
        out.append("The practice run was of a different version of the app. Run tools/evaluate.py again.")
    if report.get("code_changed"):
        out.append("The practice run had uncommitted changes to the app. Commit, then run it again.")
    if report.get("limit"):
        out.append(f"The practice run stopped early (--limit {report['limit']}). Run every label.")
    kinds = {r["kind"] for r in report["rows"]}
    for k in REQUIRED:
        if k not in kinds:
            out.append(f"The practice run left out the {k} labels.")
    if report["false_fail"]:
        out.append(f"{len(report['false_fail'])} wrong \"Does not match\" on approved labels: "
                   + "; ".join(f"{x[0]} {x[1]}" for x in report["false_fail"][:5]))
    if report["false_pass"]:
        out.append(f"{len(report['false_pass'])} wrong \"Matches\" on planted mistakes: "
                   + "; ".join(f"{x[0]} {x[1]}" for x in report["false_pass"][:5]))
    missed = [r for r in report["rows"] if r["expected"].get("overall", "pass") in ("fail", "check")
              and r["overall"] == "pass"]  # approved labels are "approved"
    if missed:
        out.append(f"{len(missed)} labels with a planted mistake were not flagged: "
                   + ", ".join(r.get("id", "?") for r in missed[:5]))
    for k in sorted(kinds):
        t = p95([r["seconds"] for r in report["rows"] if r["kind"] == k])
        if t > SECONDS:
            out.append(f"{k}: 95% of labels took up to {t:.1f} seconds (the limit is {SECONDS:g}).")
    return out


def summary(report: dict) -> list[str]:
    """Items confirmed per set (passes over items that apply), for the deploy log."""
    lines = []
    for k in sorted({r["kind"] for r in report["rows"]}):
        rows = [r for r in report["rows"] if r["kind"] == k]
        fields = [f["verdict"] for r in rows for f in r.get("fields", []) if f["verdict"] != "n/a"]
        if fields:
            lines.append(f"  {k:10s} {len(rows):3d} labels, items confirmed {100 * fields.count('pass') / len(fields):.1f}%")
    return lines


def main():
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else max((ROOT / "out" / "eval").glob("*.json"),
                                                              key=lambda p: p.stat().st_mtime)
    report = json.loads(path.read_text())
    found = problems(report, shipped_code())
    print(f"Safety gate, practice run {path.name} ({report.get('when', '?')}):")
    print("\n".join(summary(report)))
    if found:
        print("NOT SAFE TO SHIP:\n  - " + "\n  - ".join(found))
        sys.exit(1)
    print("Safe to ship: no wrong answers, every planted mistake flagged, within the time limit.")


if __name__ == "__main__":
    main()
