from pathlib import Path

import pytest

from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.judge_runner import (
    SameFamilyJudge,
    assert_judge_family_differs,
    build_judgement_prompt,
    randomise_presentation,
)

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
