# tests/test_simulate.py
"""The simulated provider drives the real sweep, judge and publish code. These tests pin that the
simulation is honest about being a simulation: it uses the real graders to decide what is right,
it is deterministic, and it can never write into the published artifacts/ folder."""

import json
import random

import pytest

from ground_truth.golden.generate import generate
from ground_truth.golden.rubric import loaded_rubric
from ground_truth.golden.schema import FieldType, Item, ItemField
from ground_truth.graders.deterministic.exact import grade_exact
from ground_truth.graders.deterministic.normalised import grade_normalised
from ground_truth.graders.deterministic.numeric_tolerance import grade_numeric_tolerance
from ground_truth.simulate import (
    REPO,
    SIM_MARKER,
    SimulationRefused,
    corrupt_value,
    render_value,
    run_simulation,
)

RUBRIC = loaded_rubric(REPO / "docs" / "rubric.md")
GRADERS = {
    "exact": grade_exact,
    "numeric_tolerance": grade_numeric_tolerance,
    "normalised": grade_normalised,
}


def _deterministic_fields(items: list[Item]) -> list[ItemField]:
    return [f for item in items for f in item.fields if RUBRIC[f.field_type].grader != "judge"]


def _grade(field: ItemField, observed: str) -> bool:
    rule = RUBRIC[field.field_type]
    return GRADERS[rule.grader](field, observed, rule).correct


@pytest.fixture(scope="module")
def items() -> list[Item]:
    return generate(40, "sim-test", "v1")


def test_a_correct_rendering_always_grades_correct_by_the_real_graders(items):
    """Where echoing the document's own value grades correct. The corpus plants traps (a date
    written 01/09/2026 scores incorrect by rule even when echoed); no rendering can fix those."""
    rng = random.Random(1)
    gradeable = [f for f in _deterministic_fields(items) if _grade(f, f.expected_value)]
    assert len(gradeable) > len(_deterministic_fields(items)) * 0.9
    for field in gradeable:
        for _ in range(3):
            text = render_value(field, rng)
            assert _grade(field, text), f"{field.field_type}: {text!r} vs {field.expected_value!r}"


def test_a_corrupted_value_always_grades_incorrect_by_the_real_graders(items):
    rng = random.Random(2)
    for field in _deterministic_fields(items):
        for _ in range(3):
            text = corrupt_value(field, rng, categories=["pending", "approved", "rejected"])
            assert not _grade(field, text), (
                f"{field.field_type}: {text!r} still grades correct vs {field.expected_value!r}"
            )


def test_the_corruption_is_never_the_expected_value(items):
    rng = random.Random(3)
    for field in (f for item in items for f in item.fields):
        assert corrupt_value(field, rng, categories=["pending", "approved"]) != field.expected_value


def test_every_field_type_is_covered(items):
    assert {f.field_type for item in items for f in item.fields} == set(FieldType)


@pytest.fixture(scope="module")
def sim(tmp_path_factory):
    out = tmp_path_factory.mktemp("sim")
    return out, run_simulation(out, seed=7, n_items=20, replicates=3)


@pytest.mark.slow
def test_the_run_writes_a_marker_and_every_artifact(sim):
    out, result = sim
    assert (out / SIM_MARKER).read_text(encoding="utf-8").startswith("SIMULATED")
    for name in ("leaderboard.json", "judge_agreement.json", "verdicts_public.jsonl"):
        assert (out / "artifacts" / name).exists()
    assert result.n_outputs == 20 * 3 * 3


@pytest.mark.slow
def test_every_slot_is_a_simulated_slot(sim):
    out, _ = sim
    board = json.loads((out / "artifacts" / "leaderboard.json").read_text(encoding="utf-8"))
    slots = [row["slot"] for row in board["rows"]]
    assert slots and all(slot.startswith("sim-") for slot in slots)


@pytest.mark.slow
def test_a_stronger_profile_scores_higher_on_the_real_pipeline(sim):
    out, _ = sim
    board = json.loads((out / "artifacts" / "leaderboard.json").read_text(encoding="utf-8"))
    point = {row["slot"]: row["accuracy"]["point"] for row in board["rows"]}
    assert point["sim-large"] > point["sim-small"]


@pytest.mark.slow
def test_replicates_differ_so_the_variance_is_not_fabricated(sim):
    _, result = sim
    assert result.distinct_replicate_sets > 0


@pytest.mark.slow
def test_judge_decisions_are_recorded_for_every_assigned_judge(sim):
    out, _ = sim
    agreement = json.loads((out / "artifacts" / "judge_agreement.json").read_text("utf-8"))
    assert {d["judge_slot"] for d in agreement["decisions"]} == {"sim-judge-a", "sim-judge-b"}


@pytest.mark.slow
def test_the_same_seed_reproduces_the_same_leaderboard(sim, tmp_path):
    out, _ = sim
    run_simulation(tmp_path, seed=7, n_items=20, replicates=3)
    first = (out / "artifacts" / "leaderboard.json").read_text(encoding="utf-8")
    again = (tmp_path / "artifacts" / "leaderboard.json").read_text(encoding="utf-8")
    assert first == again


@pytest.mark.slow
def test_it_refuses_to_write_into_the_published_artifacts_folder():
    with pytest.raises(SimulationRefused):
        run_simulation(REPO / "artifacts", seed=1, n_items=6, replicates=3)
    with pytest.raises(SimulationRefused):
        run_simulation(REPO / "artifacts" / "nested", seed=1, n_items=6, replicates=3)


@pytest.mark.slow
def test_it_never_reads_the_real_results_store(sim):
    """The simulated items are generated, not copied, so the real private split never enters."""
    out, _ = sim
    manifest = (out / "artifacts" / "manifest_private.json").read_text(encoding="utf-8")
    real = (REPO / "golden" / "manifest_private.json").read_text(encoding="utf-8")
    assert not set(json.loads(real).get("item_hashes", [])) & set(
        json.loads(manifest).get("item_hashes", [])
    )


@pytest.fixture(scope="module")
def contested(tmp_path_factory):
    out = tmp_path_factory.mktemp("contested")
    run_simulation(out, seed=7, n_items=20, replicates=3, scenario="contested")
    return out


@pytest.mark.slow
def test_the_contested_scenario_has_two_models_whose_intervals_overlap(contested):
    board = json.loads((contested / "artifacts" / "leaderboard.json").read_text("utf-8"))
    acc = {r["slot"]: r["accuracy"] for r in board["rows"]}
    medium, large = acc["sim-medium"], acc["sim-large"]
    assert medium["low"] <= large["high"] and large["low"] <= medium["high"]


@pytest.mark.slow
def test_the_contested_scenario_rejects_the_weak_judge_and_holds_the_type_back(contested):
    agreement = json.loads((contested / "artifacts" / "judge_agreement.json").read_text("utf-8"))
    status = {d["judge_slot"]: d["status"] for d in agreement["decisions"]}
    assert status["sim-judge-b"] == "rejected"
    board = json.loads((contested / "artifacts" / "leaderboard.json").read_text("utf-8"))
    assert [h["field_type"] for h in board["held_back_field_types"]] == ["line_item_description"]


def test_an_unknown_scenario_is_refused(tmp_path):
    with pytest.raises(ValueError, match="scenario"):
        run_simulation(tmp_path, seed=1, n_items=6, replicates=3, scenario="nope")
