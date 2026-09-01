from decimal import Decimal
from pathlib import Path

import pytest

from ground_truth.triage.ingest import load_intents

HEADER = "intent,volume_per_month,current_cost_per_item,cost_of_error,client_quote\n"


def write(tmp_path, body: str):
    p = tmp_path / "intake.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    return p


def test_parses_a_well_formed_row(tmp_path):
    path = write(tmp_path, 'invoice_total,4000,2.50,40.00,"About forty dollars of rework"\n')
    intent = load_intents(path)[0]
    assert intent.volume_per_month == 4000  # noqa: PLR2004
    assert intent.current_cost_per_item == Decimal("2.50")
    assert intent.cost_of_error == Decimal("40.00")


def test_costs_are_decimal_not_float(tmp_path):
    path = write(tmp_path, 'a,10,0.10,0.30,"x"\n')
    assert isinstance(load_intents(path)[0].cost_of_error, Decimal)


def test_unbounded_marker_is_recognised(tmp_path):
    path = write(tmp_path, 'bank_detail_change,20,1.00,unbounded,"Could lose a whole payment"\n')
    intent = load_intents(path)[0]
    assert intent.unbounded_error and intent.cost_of_error is None


def test_missing_client_quote_is_rejected(tmp_path):
    path = write(tmp_path, "a,10,0.10,0.30,\n")
    with pytest.raises(ValueError, match="client_quote"):
        load_intents(path)


def test_missing_cost_of_error_is_rejected(tmp_path):
    path = write(tmp_path, 'a,10,0.10,,"x"\n')
    with pytest.raises(ValueError, match="cost_of_error"):
        load_intents(path)


def test_wrong_header_is_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("intent,volume\na,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        load_intents(p)


def test_error_names_the_offending_line(tmp_path):
    path = write(tmp_path, 'a,10,0.10,0.30,"ok"\nb,10,0.10,0.30,\n')
    with pytest.raises(ValueError, match="line 3"):
        load_intents(path)


def test_template_file_loads(tmp_path):
    template = Path(__file__).resolve().parents[2] / "docs" / "triage-intake-template.csv"
    assert load_intents(template), "the shipped template must be a valid, loadable example"
