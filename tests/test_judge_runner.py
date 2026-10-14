import json
from pathlib import Path

import pytest

from ground_truth._bok_shim import (
    CacheMode,
    CallContext,
    FailoverMode,
    Sensitivity,
    SensitivityViolation,
)
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.judge_runner import (
    SameFamilyJudge,
    assert_judge_family_differs,
    build_judgement_prompt,
    randomise_presentation,
    sample_judgements,
    select_judge_targets,
)
from ground_truth.providers import judge_assignments
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


def test_sample_judgements_refuses_confidential_material_to_a_training_judge(con, tmp_path):
    """The judge sees the same client text the model under test saw. models.yaml's judge slots
    get the same gate as its model slots, checked before the judge is even resolved."""
    manifest = tmp_path / "models.yaml"
    manifest.write_text(
        MODELS_YAML.read_text(encoding="utf-8").replace(
            "trains_on_data: false", "trains_on_data: true"
        ),
        encoding="utf-8",
    )
    gw = FakeGateway()
    with pytest.raises(SensitivityViolation, match="trains_on_data=True"):
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
            models_yaml=manifest,
            sensitivity=Sensitivity.CLIENT_CONFIDENTIAL,
        )
    assert gw.seen == [], "a refused judge must never reach the gateway"


def test_sample_judgements_defaults_to_the_synthetic_corpus_label(con):
    gw = FakeGateway()
    sample_judgements(
        con,
        "output-1",
        field(),
        "Concrete works, phase one",
        "judge-a",
        "slot-a",
        n=2,
        seed=0,
        resolve_fn=gw.resolve,
        call_fn=gw.call,
        context=CallContext(),
        models_yaml=MODELS_YAML,
    )
    assert gw.seen and all(sens is Sensitivity.SYNTHETIC for _, _, _, sens, _ in gw.seen)


def _output(con, *, item_id, slot, replicate, raw):
    """One replicate under its own run (run_id per slot) -- only the columns the selector reads
    matter; the rest are schema-required fillers."""
    run_id = f"run-{slot}"
    con.execute(
        "INSERT OR IGNORE INTO runs (run_id, started_at, model_slot, resolved_model_ref, "
        "provider, commercial_context, sweep_id, code_version, models_yaml_hash) "
        "VALUES (?, now(), ?, 'ref', 'prov', false, 's1', 'sha', 'h')",
        [run_id, slot],
    )
    output_id = f"o-{item_id}-{slot}-{replicate}"
    con.execute(
        "INSERT INTO outputs (output_id, run_id, item_id, replicate_idx, raw_output, "
        "ledger_call_id, provider_served, latency_ms, prompt_hash, observed_at) "
        "VALUES (?, ?, ?, ?, ?, 'call', 'prov', 10, 'ph', now())",
        [output_id, run_id, item_id, replicate, raw],
    )
    return output_id


def _desc(value):
    return json.dumps({"line_1_description": value})


def test_judge_targets_are_one_output_per_item_slot(con):
    """Audit H8 / spec section 15: the judge scores the modal output per (item, slot), so
    300 x 6 x 3 = 5,400 judge calls, not one per replicate (27,000)."""
    for item in ("i1", "i2"):
        for slot in ("slot-a", "slot-b"):
            for r in range(1, 6):
                _output(con, item_id=item, slot=slot, replicate=r, raw=_desc(f"text {r % 2}"))
    targets = select_judge_targets(con, "line_1_description")
    assert len({t.output_id for t in targets}) == 2 * 2  # n_items x n_slots
    assert {(t.item_id, t.model_slot) for t in targets} == {
        (i, s) for i in ("i1", "i2") for s in ("slot-a", "slot-b")
    }


def test_the_judge_target_carries_the_modal_value(con):
    values = ["minority", "Concrete works", "Concrete works", "other", "Concrete works"]
    for r, value in enumerate(values, start=1):
        _output(con, item_id="i1", slot="slot-a", replicate=r, raw=_desc(value))
    (target,) = select_judge_targets(con, "line_1_description")
    assert target.observed == "Concrete works"
    assert target.output_id == "o-i1-slot-a-2"  # the first replicate holding the modal value


def test_a_tie_goes_to_the_lowest_replicate_so_selection_is_reproducible(con):
    for r, value in enumerate(["B", "A", "A", "B"], start=1):
        _output(con, item_id="i1", slot="slot-a", replicate=r, raw=_desc(value))
    (target,) = select_judge_targets(con, "line_1_description")
    assert (target.observed, target.output_id) == ("B", "o-i1-slot-a-1")


def test_an_unparseable_or_missing_field_votes_as_absent(con):
    """A modal absence is not judged: there is no text to compare, so the caller records the
    field as not extracted rather than spending three judge calls on nothing."""
    _output(con, item_id="i1", slot="slot-a", replicate=1, raw="not json")
    _output(con, item_id="i1", slot="slot-a", replicate=2, raw=json.dumps({"other": "x"}))
    _output(con, item_id="i1", slot="slot-a", replicate=3, raw=_desc("Concrete works"))
    (target,) = select_judge_targets(con, "line_1_description")
    assert target.observed is None
    assert target.output_id == "o-i1-slot-a-1"


def _yaml(tmp_path, slot_judge):
    p = tmp_path / "models.yaml"
    p.write_text(
        MODELS_YAML.read_text(encoding="utf-8").replace("judge: judge-a", f"judge: {slot_judge}"),
        encoding="utf-8",
    )
    return p


def test_every_slot_names_its_judge():
    assert judge_assignments(MODELS_YAML) == {"slot-a": "judge-a"}


def test_an_unknown_judge_is_refused_at_load(tmp_path):
    with pytest.raises(ValueError, match="judge-nope"):
        judge_assignments(_yaml(tmp_path, "judge-nope"))


def test_a_same_family_assignment_is_refused_at_load(tmp_path):
    with pytest.raises(SameFamilyJudge):
        judge_assignments(_yaml(tmp_path, "judge-same-family"))


def test_a_slot_without_a_judge_is_refused(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(
        MODELS_YAML.read_text(encoding="utf-8").replace("    judge: judge-a\n", ""), "utf-8"
    )
    with pytest.raises(ValueError, match="slot-a"):
        judge_assignments(p)
