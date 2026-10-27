# tests/test_regression_issues_script.py
"""scripts/regression_issues.py decides which GitHub issues regression-watch.yml opens.

Regression: the workflow used to open an issue for every `detected` alert in the committed
artifacts/regression.json every Monday, with no placeholder check and no dedupe, so demo data
produced a fresh pair of "regression" issues on the public repo each week (issues 17-24).
"""

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "regression_issues", REPO / "scripts" / "regression_issues.py"
)
assert _spec and _spec.loader
regression_issues = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(regression_issues)

ALERT = {
    "slot": "slot-a",
    "field_type": "money",
    "look": 3,
    "detected": True,
    "statement": "slot-a/money dropped.",
}
FINGERPRINT = {"slot": "slot-b", "status": "NOT_EXPOSED", "statement": "slot-b exposes none."}


def _doc(**over: object) -> dict[str, object]:
    return {"look": 3, "alerts": [ALERT], "fingerprints": [FINGERPRINT], **over}


def test_placeholder_data_opens_nothing():
    assert regression_issues.issues_to_open(_doc(placeholder=True), set()) == []


def test_real_detected_alert_and_fingerprint_open_issues_with_the_notice():
    issues = regression_issues.issues_to_open(_doc(), set())
    titles = [title for title, _ in issues]
    assert titles == [
        "Regression detected: slot-a / money (look 3)",
        "Fingerprint NOT_EXPOSED: slot-b",
    ]
    assert "10-business-day notice" in issues[0][1]
    assert "slot-a/money dropped." in issues[0][1]


def test_an_existing_issue_with_the_same_title_is_not_opened_again():
    existing = {"Regression detected: slot-a / money (look 3)", "Fingerprint NOT_EXPOSED: slot-b"}
    assert regression_issues.issues_to_open(_doc(), existing) == []


def test_a_new_look_opens_a_new_issue_and_undetected_and_stable_are_ignored():
    doc = _doc(
        alerts=[{**ALERT, "look": 4}, {**ALERT, "slot": "slot-c", "detected": False}],
        fingerprints=[{**FINGERPRINT, "status": "STABLE"}],
    )
    existing = {"Regression detected: slot-a / money (look 3)"}
    titles = [t for t, _ in regression_issues.issues_to_open(doc, existing)]
    assert titles == ["Regression detected: slot-a / money (look 4)"]


def test_main_without_a_file_is_a_no_op(tmp_path, capsys):
    assert regression_issues.main(["--file", str(tmp_path / "missing.json")]) == 0
    assert "nothing to check" in capsys.readouterr().out


def test_main_creates_only_the_issues_not_already_present(tmp_path):
    path = tmp_path / "regression.json"
    path.write_text(json.dumps(_doc()), encoding="utf-8")
    created: list[str] = []
    code = regression_issues.main(
        ["--file", str(path)],
        list_titles=lambda: {"Fingerprint NOT_EXPOSED: slot-b"},
        create_issue=lambda title, body: created.append(title),
    )
    assert code == 0
    assert created == ["Regression detected: slot-a / money (look 3)"]


def test_the_workflow_delegates_to_the_script_and_no_longer_loops_over_jq():
    workflow = (REPO / ".github" / "workflows" / "regression-watch.yml").read_text(encoding="utf-8")
    assert "scripts/regression_issues.py" in workflow
    assert "gh issue create" not in workflow
