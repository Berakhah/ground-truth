# tests/test_definition_of_done.py
"""Machine-checked verification of `04` section 12's eleven definition-of-done items.

Fixes applied against the plan's Task 50 brief (see docs/definition-of-done.md for the
full record):

- `import os` was missing from the brief's code sample even though `test_dod_10` uses
  `os.environ`.
- `test_dod_7`'s load-bearing assertion is on the pre-registered `looks` calendar that
  `ground_truth.regression.schedule` builds (13 looks, each with a look index, a run
  timestamp, and a monotone cumulative alpha-spend), per the plan's own 2026-08-29
  amendment to Task 38: "`assert 'schedule:' in workflow` proves the wrong thing --
  assert on the `looks` calendar record instead." The workflow-YAML check is kept as a
  secondary, weaker assertion (a cron trigger is still a real requirement).
- `test_dod_4` reads the actual published `judge_agreement.json` shape
  (`{"decisions": [...]}` with flat `alpha_low`/`alpha_high` fields), not the brief's
  `{"entries": [...]}` with a nested `alpha_ci` -- that shape belongs to a different,
  in-memory representation (`ground_truth.publish.leaderboard._agreement_to_dict`), not
  the file `ground_truth.publish.artifacts.emit_all` actually writes.
- `_require_release` also skips on placeholder/demo data, reusing the convention already
  established by `tests/test_reproducibility.py`'s `_only_placeholder_published`: an
  `artifacts/` directory that exists but holds only checked-in placeholder scaffolding is
  not a cut release, and running these tests against demo numbers would produce
  meaningless pass/fail results rather than an honest skip.
"""

import json
import os
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "artifacts"
DOCS = REPO / "docs"


def _git(*args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=REPO, capture_output=True, text=True, check=True
    ).stdout


def _only_placeholder_published() -> bool:
    leaderboard_path = ARTIFACTS / "leaderboard.json"
    if not leaderboard_path.exists():
        return False
    return json.loads(leaderboard_path.read_text(encoding="utf-8")).get("placeholder") is True


@pytest.fixture(autouse=True)
def _require_release():
    if not ARTIFACTS.exists():
        pytest.skip("cut a release first")
    if _only_placeholder_published():
        pytest.skip("only placeholder/demo data is published; run the sweep and publish for real")


def test_dod_1_golden_set_and_rubric_authored_before_labelling():
    rubric = _git("log", "--format=%ct", "-1", "--", "docs/rubric.md").strip()
    labels = _git("log", "--format=%ct", "--reverse", "--", "golden/manifest_public.json").split()[
        0
    ]
    assert rubric and labels
    assert int(rubric) < int(labels), "the rubric must be committed before the first labels"
    public = json.loads((REPO / "golden" / "manifest_public.json").read_text(encoding="utf-8"))
    private = json.loads((REPO / "golden" / "manifest_private.json").read_text(encoding="utf-8"))
    assert 200 <= public["count"] + private["count"] <= 500  # noqa: PLR2004


def test_dod_2_splits_enforced_and_hashes_published():
    assert (REPO / "golden" / "manifest_private.json").exists()
    assert "contamination" in (DOCS / "methodology.md").read_text(encoding="utf-8").lower()
    tracked = [
        p
        for p in _git("ls-files", "golden/corpus/private/").splitlines()
        if p.strip() and not p.endswith(".gitkeep")
    ]
    assert tracked == []


def test_dod_3_deterministic_graders_for_every_possible_field_type():
    from ground_truth.golden.rubric import loaded_rubric  # noqa: PLC0415
    from ground_truth.golden.schema import FieldType  # noqa: PLC0415

    rubric = loaded_rubric(DOCS / "rubric.md")
    judged = {ft for ft, rule in rubric.items() if rule.grader == "judge"}
    assert judged <= {FieldType.LINE_ITEM_DESCRIPTION}, (
        f"only free text may require a judge; these do too: {judged}"
    )


def test_dod_4_judge_agreement_published_including_weakness():
    body = json.loads((ARTIFACTS / "judge_agreement.json").read_text(encoding="utf-8"))
    assert body["decisions"], "the judge agreement table must not be empty"
    for entry in body["decisions"]:
        assert entry["status"] in {"accepted", "rejected"}
        assert "alpha_low" in entry and "alpha_high" in entry and "n_units" in entry


def test_dod_5_matrix_has_list_price_cost_and_caveated_latency():
    for row in json.loads((ARTIFACTS / "leaderboard.json").read_text(encoding="utf-8"))["rows"]:
        assert "list price" in row["cost"]["caveat"].lower()
        assert "free tier" in row["latency"]["caveat"].lower()
        assert "rank" not in row["latency"]


def test_dod_6_calibration_exported_for_ledger_sense():
    body = json.loads((ARTIFACTS / "calibration.json").read_text(encoding="utf-8"))
    assert body["curves"]
    for curve in body["curves"]:
        assert curve["threshold_recommendations"]
        assert curve["source_split"] == "public-fit/private-validate"


def test_dod_7_regression_watch_scheduled_and_alerts_state_their_test(tmp_path):
    # Secondary, weaker check: the workflow does need a real cron trigger.
    workflow = (REPO / ".github" / "workflows" / "regression-watch.yml").read_text(encoding="utf-8")
    assert "schedule:" in workflow and "cron:" in workflow

    # Load-bearing check (plan amendment, Task 38, audit H12): a workflow file containing
    # the substrings "schedule:"/"cron:" proves nothing about whether a real pre-registered
    # analysis calendar exists -- assert on the `looks` calendar record that
    # ground_truth.regression.schedule actually builds and enforces instead.
    from ground_truth.regression.schedule import next_look, record_look  # noqa: PLC0415
    from ground_truth.stats.sequential import LOOKS_PER_QUARTER, spent_alpha  # noqa: PLC0415
    from ground_truth.store.db import connect, migrate  # noqa: PLC0415

    con = connect(tmp_path / "dod7-looks.duckdb")
    migrate(con)
    now = datetime(2026, 10, 5, tzinfo=UTC)
    records = []
    for i in range(LOOKS_PER_QUARTER):
        record = next_look(con, now + timedelta(days=7 * i))
        record_look(con, record)
        records.append(record)
    con.close()

    assert len(records) == LOOKS_PER_QUARTER == 13  # noqa: PLR2004
    assert [r.look for r in records] == list(range(1, LOOKS_PER_QUARTER + 1)), (
        "the calendar must carry a look index for every scheduled look"
    )
    assert all(r.total_looks == LOOKS_PER_QUARTER for r in records)
    assert all(isinstance(r.run_at, datetime) for r in records), (
        "every look must carry the date it ran"
    )

    cumulative_spend = [spent_alpha(r.look, r.total_looks) for r in records]
    assert cumulative_spend == sorted(cumulative_spend), (
        "alpha spend must be monotone non-decreasing across the pre-registered looks"
    )
    assert cumulative_spend[-1] == pytest.approx(0.05), (
        "the full alpha budget is spent by the final pre-registered look"
    )

    for alert in json.loads((ARTIFACTS / "regression.json").read_text(encoding="utf-8"))["alerts"]:
        assert "O'Brien-Fleming" in alert["statement"]


def test_dod_8_triage_produced_end_to_end_with_sensitivity():
    """Reads deliverables/, NOT artifacts/ -- audit B2. The triage report is
    CLIENT_CONFIDENTIAL and artifacts/ is deployed to a public web page."""
    path = REPO / "deliverables" / "triage.html"
    if not path.exists():
        pytest.skip("no triage engagement delivered yet")
    body = path.read_text(encoding="utf-8")
    assert "costs more than" in body and "n=" in body
    assert "synthetic" in body.lower(), (
        "audit M8: the report must state that its accuracy was measured on a synthetic "
        "corpus, not on this client's documents"
    )


def test_dod_9_public_leaderboard_ships_its_whole_evidence_chain():
    for name in (
        "leaderboard.json",
        "verdicts_public.jsonl",
        "verdicts_private_by_hash.jsonl",
        "manifest_private.json",
    ):
        assert (ARTIFACTS / name).exists(), f"missing published artifact: {name}"
    for name in ("methodology.md", "rubric.md", "corrections.md", "analysis-plan.md"):
        assert (DOCS / name).exists(), f"missing published document: {name}"
    assert (REPO / "CHANGELOG.md").exists()
    assert (REPO / ".github" / "ISSUE_TEMPLATE" / "right-of-reply.yml").exists()


def test_dod_10_reproducibility_test_runs_and_does_not_skip():
    # -o addopts= is load-bearing (audit H14): without it the nested run inherits the parent's
    # options, measures coverage from three tests, scores far under any floor, and exits
    # non-zero after passing. A nested run must never carry the parent's gate.
    result = subprocess.run(
        [
            "uv",
            "run",
            "pytest",
            "tests/test_reproducibility.py",
            "-v",
            "--no-header",
            "-p",
            "no:cacheprovider",
            "-o",
            "addopts=",
        ],
        cwd=REPO,
        capture_output=True,
        text=True,
        env={**os.environ, "GT_REQUIRE_DB": "1"},
        check=False,
    )
    assert result.returncode == 0, result.stdout
    assert "skipped" not in result.stdout.lower(), (
        "the reproducibility test must actually run, not skip"
    )


def test_dod_11_methodology_defines_every_published_term():
    from ground_truth.publish import leaderboard  # noqa: PLC0415

    leaderboard.assert_methodology_defines_every_term(DOCS / "methodology.md")
