from pathlib import Path

import pytest

from ground_truth._bok_shim import CacheMode, CallContext, FailoverMode
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.judge_runner import (
    SameFamilyJudge,
    assert_judge_family_differs,
    build_judgement_prompt,
    randomise_presentation,
    sample_judgements,
)
from ground_truth.store.db import connect, migrate
from tests.test_runner import FakeGateway

MODELS_YAML = Path(__file__).resolve().parents[1] / "models.yaml"


def field() -> ItemField:
    return ItemField(
        field_name="line_1_description",
        field_type=FieldType.LINE_ITEM_DESCRIPTION,
        expected_value="Concrete works, phase 1",
    )


def test_presentation_order_varies_across_seeds():
    orders = {randomise_presentation("A", "B", seed=s).order for s in range(20)}
    assert orders == {0, 1}, "both presentation orders must occur"


def test_presentation_is_deterministic_for_a_seed():
    assert randomise_presentation("A", "B", seed=7) == randomise_presentation("A", "B", seed=7)


def test_order_determines_which_text_comes_first():
    p = randomise_presentation("EXPECTED", "OBSERVED", seed=0)
    assert p.first == ("EXPECTED" if p.order == 0 else "OBSERVED")


def test_prompt_requests_a_constrained_verdict():
    prompt = build_judgement_prompt(field(), randomise_presentation("A", "B", seed=1))
    assert "EQUIVALENT" in prompt and "NOT_EQUIVALENT" in prompt
    assert "exactly one" in prompt.lower()


def test_prompt_does_not_label_which_text_is_the_reference():
    prompt = build_judgement_prompt(field(), randomise_presentation("A", "B", seed=1)).lower()
    for leak in ("expected", "reference", "correct answer", "ground truth", "model output"):
        assert leak not in prompt, f"prompt leaks position semantics via {leak!r}"


def test_same_family_judge_is_rejected():
    with pytest.raises(SameFamilyJudge):
        assert_judge_family_differs("judge-same-family", "slot-a", MODELS_YAML)


def test_different_family_judge_is_accepted():
    assert assert_judge_family_differs("judge-a", "slot-a", MODELS_YAML) is None


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_sample_judgements_writes_n_rows_with_recorded_presentation_order(con):
    gw = FakeGateway()
    written = sample_judgements(
        con,
        "output-1",
        field(),
        "Concrete works, phase one",
        "judge-a",
        "slot-a",
        n=5,
        seed=0,
        resolve_fn=gw.resolve,
        call_fn=gw.call,
        context=CallContext(),
        models_yaml=MODELS_YAML,
    )
    assert written == 5  # noqa: PLR2004
    rows = con.execute(
        "SELECT output_id, field_name, judge_slot, presentation_order FROM judge_samples"
    ).fetchall()
    assert len(rows) == 5  # noqa: PLR2004
    assert all(r == ("output-1", "line_1_description", "judge-a", r[3]) for r in rows)
    assert {r[3] for r in rows} <= {0, 1}


def test_sample_judgements_disables_cache_and_failover(con):
    gw = FakeGateway()
    sample_judgements(
        con,
        "output-1",
        field(),
        "Concrete works, phase one",
        "judge-a",
        "slot-a",
        n=3,
        seed=0,
        resolve_fn=gw.resolve,
        call_fn=gw.call,
        context=CallContext(),
        models_yaml=MODELS_YAML,
    )
    assert gw.seen and all(cache is CacheMode.DISABLED for _, cache, _, _, _ in gw.seen)
    assert all(fo is FailoverMode.DISABLED for _, _, fo, _, _ in gw.seen)


def test_sample_judgements_rejects_same_family_before_any_call(con):
    gw = FakeGateway()
    with pytest.raises(SameFamilyJudge):
        sample_judgements(
            con,
            "output-1",
            field(),
            "Concrete works, phase one",
            "judge-same-family",
            "slot-a",
            n=3,
            seed=0,
            resolve_fn=gw.resolve,
            call_fn=gw.call,
            context=CallContext(),
            models_yaml=MODELS_YAML,
        )
    assert gw.seen == [], "a rejected judge must never reach the gateway"


def test_sample_judgements_refuses_fallback_handle(con):
    gw = FakeGateway(fallback_slots=frozenset({"judge-a"}))
    with pytest.raises(ValueError, match="fallback"):
        sample_judgements(
            con,
            "output-1",
            field(),
            "Concrete works, phase one",
            "judge-a",
            "slot-a",
            n=1,
            seed=0,
            resolve_fn=gw.resolve,
            call_fn=gw.call,
            context=CallContext(),
            models_yaml=MODELS_YAML,
        )
