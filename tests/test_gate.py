"""The safety gate (tools/gate.py): a version may only go live after a full practice run of that very code with no
wrong answer either way, every planted mistake flagged, and the slow labels inside the time limit."""

from tools.gate import REQUIRED, problems

CODE = "abc123"


def row(kind, overall="pass", seconds=1.0, planted=False):
    approved = kind in ("cola", "cola2", "cola3", "scene_real")
    return {"kind": kind, "overall": overall, "seconds": seconds,
            "expected": {"overall": "fail" if planted else "approved" if approved else "pass"}}


def report(**over):
    rows = [row(k) for k in REQUIRED]
    rows += [row("syn", "fail", planted=True), row("tampered", "check", planted=True)]
    r = {"code": CODE, "code_changed": False, "limit": 0, "rows": rows, "false_fail": [], "false_pass": []}
    r.update(over)
    return r


def test_a_clean_full_run_of_this_code_passes():
    assert problems(report(), CODE) == []


def test_a_run_of_different_code_is_refused():
    assert any("different version" in p for p in problems(report(), "other"))
    assert any("different version" in p for p in problems(report(code=None), CODE))  # runs from before the gate


def test_a_run_with_uncommitted_changes_is_refused():
    assert any("uncommitted" in p for p in problems(report(code_changed=True), CODE))


def test_a_partial_run_is_refused():
    assert any("limit" in p for p in problems(report(limit=20), CODE))
    r = report()
    r["rows"] = [x for x in r["rows"] if x["kind"] != "cola2"]
    assert any("cola2" in p for p in problems(r, CODE))


def test_one_wrong_does_not_match_blocks():
    assert any("wrong" in p for p in problems(report(false_fail=[["1", "abv", "ABV_MISMATCH", "..."]]), CODE))


def test_one_wrong_matches_blocks():
    assert any("wrong" in p for p in problems(report(false_pass=[["t1", "abv", "ABV_MISMATCH"]]), CODE))


def test_a_planted_mistake_that_came_back_matches_overall_blocks():
    r = report()
    r["rows"].append(row("tampered_x", "pass", planted=True))
    assert any("not flagged" in p for p in problems(r, CODE))


def test_slow_labels_block():
    r = report()
    r["rows"] += [row("cola", seconds=6.0) for _ in range(5)]
    assert any("seconds" in p for p in problems(r, CODE))


def test_one_slow_label_among_many_is_allowed():
    r = report()
    r["rows"] += [row("cola") for _ in range(40)] + [row("cola", seconds=6.0)]
    assert problems(r, CODE) == []
