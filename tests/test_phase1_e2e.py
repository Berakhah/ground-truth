from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ground_truth.stats.bootstrap import cluster_bootstrap_ci
from ground_truth.stats.mde import describe_mde
from ground_truth.triage.expected_value import evaluate
from ground_truth.triage.ingest import load_intents
from ground_truth.triage.report import ReportRow, render_report
from ground_truth.triage.sensitivity import find_flip_point

INTAKE = Path(__file__).resolve().parents[1] / "docs" / "triage-intake-template.csv"


def test_intake_to_report_produces_a_sellable_artifact(tmp_path):
    intents = load_intents(INTAKE)
    assert intents, "the intake template must contain at least one example row"
    accuracy = cluster_bootstrap_ci(
        [(f"i{i}", i % 10 != 0) for i in range(40)], seed=1, n_resamples=500
    )
    rows = [
        ReportRow(
            intent=intent,
            ev=evaluate(intent, accuracy, Decimal("0.10")),
            flip=find_flip_point(intent, accuracy, Decimal("0.10"), ceiling=Decimal("10000")),
            accuracy=accuracy,
        )
        for intent in intents
    ]
    html = render_report(
        rows,
        generated_at=datetime(2026, 9, 15, tzinfo=UTC),
        methodology_url="https://example.invalid/methodology",
    )
    assert f"n={accuracy.n}" in html
    assert describe_mde(accuracy.n, 0.10, n_comparisons=1) is not None
    assert "never automate" in html.lower(), "the unbounded-error row must be visible as such"
    (tmp_path / "triage.html").write_text(html, encoding="utf-8")
