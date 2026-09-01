from datetime import UTC, datetime
from decimal import Decimal

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import evaluate
from ground_truth.triage.ingest import Intent
from ground_truth.triage.report import PLACEHOLDER_ACCURACY_METHOD, ReportRow, render_report
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


def test_placeholder_accuracy_renders_a_visible_warning_banner():
    intent = Intent(
        intent="invoice_total",
        volume_per_month=1000,
        current_cost_per_item=Decimal("2.00"),
        cost_of_error=Decimal("4.00"),
        client_quote="about four dollars of rework each time",
        unbounded_error=False,
    )
    placeholder = Interval(
        point=0.90, low=0.85, high=0.94, n=50, method=PLACEHOLDER_ACCURACY_METHOD
    )
    placeholder_row = ReportRow(
        intent=intent,
        ev=evaluate(intent, placeholder, AUTO),
        flip=find_flip_point(intent, placeholder, AUTO, ceiling=Decimal("1000")),
        accuracy=placeholder,
    )
    body = render_report(
        [placeholder_row],
        generated_at=datetime(2026, 9, 15, tzinfo=UTC),
        methodology_url="https://example.invalid/methodology",
    )
    assert "not a measurement" in body.lower()


def test_real_accuracy_data_does_not_render_the_placeholder_banner():
    body = html()
    assert "not a measurement" not in body.lower()
