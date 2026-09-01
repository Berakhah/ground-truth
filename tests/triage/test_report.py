from datetime import UTC, datetime
from decimal import Decimal

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import evaluate
from ground_truth.triage.ingest import Intent
from ground_truth.triage.report import ReportRow, render_report
from ground_truth.triage.sensitivity import find_flip_point

ACC = Interval(point=0.92, low=0.905, high=0.935, n=40, method="cluster-BCa")
AUTO = Decimal("0.10")


def row() -> ReportRow:
    intent = Intent(
        intent="invoice_total",
        volume_per_month=1000,
        current_cost_per_item=Decimal("2.00"),
        cost_of_error=Decimal("4.00"),
        client_quote="about four dollars of rework each time",
        unbounded_error=False,
    )
    return ReportRow(
        intent=intent,
        ev=evaluate(intent, ACC, AUTO),
        flip=find_flip_point(intent, ACC, AUTO, ceiling=Decimal("1000")),
        accuracy=ACC,
    )


def html() -> str:
    return render_report(
        [row()],
        generated_at=datetime(2026, 9, 15, tzinfo=UTC),
        methodology_url="https://example.invalid/methodology",
    )


def test_every_number_carries_its_sample_size():
    assert "n=40" in html()


def test_interval_is_rendered_as_an_interval():
    body = html()
    assert "0.905" in body and "0.935" in body


def test_client_quote_appears_verbatim():
    assert "about four dollars of rework each time" in html()


def test_flip_point_sentence_is_present():
    assert "if a wrong extraction costs more than" in html()


def test_mde_caveat_is_present():
    assert "not that none exists" in html()


def test_methodology_link_is_present():
    assert "https://example.invalid/methodology" in html()


def test_print_stylesheet_is_inlined():
    body = html()
    assert "@media print" in body and "<link" not in body


def test_report_states_the_generation_date():
    assert "2026-09-15" in html()


def test_empty_rows_render_an_empty_state_not_a_crash():
    body = render_report(
        [],
        generated_at=datetime(2026, 9, 15, tzinfo=UTC),
        methodology_url="https://example.invalid/methodology",
    )
    assert "no intents" in body.lower()
