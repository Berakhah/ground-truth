# tests/matrix/test_build.py
import json
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from ground_truth.golden.schema import Split
from ground_truth.graders.judge.aggregate import Sample
from ground_truth.graders.judge.agreement import JudgeStatus, assess, record_decision
from ground_truth.matrix.build import (
    LeaderboardRow,
    SlotSpecMissing,
    TokenCountsUnavailable,
    _slot_accuracy,
    build_leaderboard,
    distinguishability_statements,
    headline_verdict_ids,
    headline_verdict_weights,
)
from ground_truth.matrix.cost import LIST_PRICE_CAVEAT, cost_per_1k_items
from ground_truth.matrix.latency import summarise_latency
from ground_truth.providers import SlotSpec
from ground_truth.stats.bootstrap import Interval
from ground_truth.store.db import connect, migrate


def spec(slot: str, *, judge: str | None = None) -> SlotSpec:
    return SlotSpec(
        judge=judge,
        slot=slot,
        family="fam",
        provider="prov",
        model_ref="ref",
        trains_on_data=False,
        commercial_use=True,
        exposes_fingerprint=False,
        list_price_in_per_1m=Decimal("0.10"),
        list_price_out_per_1m=Decimal("0.40"),
        pricing_url="https://example.invalid/p",
        retrieved_at=date(2026, 8, 31),
    )


def row(slot: str, low: float, point: float, high: float) -> LeaderboardRow:
    return LeaderboardRow(
        slot=slot,
        accuracy=Interval(point=point, low=low, high=high, n=180, method="cluster-BCa"),
        cost=cost_per_1k_items(spec(slot), 2000),
        latency=summarise_latency([100, 200, 300]),
        per_field={},
    )


def test_overlapping_rows_produce_a_plain_language_statement():
    statements = distinguishability_statements(
        [row("slot-a", 0.89, 0.92, 0.95), row("slot-b", 0.90, 0.93, 0.96)]
    )
    assert any("not distinguishable at this sample size" in s for s in statements)
    assert any("slot-a" in s and "slot-b" in s for s in statements)


def test_separated_rows_produce_no_statement():
    assert (
        distinguishability_statements(
            [row("slot-a", 0.60, 0.62, 0.64), row("slot-b", 0.90, 0.93, 0.96)]
        )
        == []
    )


def test_statement_carries_the_sample_size():
    statements = distinguishability_statements(
        [row("slot-a", 0.89, 0.92, 0.95), row("slot-b", 0.90, 0.93, 0.96)]
    )
    assert all("n=180" in s for s in statements)


def test_every_pair_is_examined():
    rows = [row("a", 0.89, 0.92, 0.95), row("b", 0.90, 0.93, 0.96), row("c", 0.91, 0.94, 0.97)]
    assert len(distinguishability_statements(rows)) == 3  # noqa: PLR2004


def test_single_row_produces_no_statements():
    assert distinguishability_statements([row("a", 0.89, 0.92, 0.95)]) == []


def test_rows_carry_the_cost_caveat():
    assert row("a", 0.89, 0.92, 0.95).cost.caveat == LIST_PRICE_CAVEAT


# -- build_leaderboard / the judge-rejection exclusion guarantee -----------------------
#
# COST (see ground_truth/matrix/build.py's module docstring): `outputs.token_count` is
# nullable -- rows written before that column existed, or written by a degraded-mode run
# with providers disabled, carry no token count. `build_leaderboard` raises
# `TokenCountsUnavailable` for any such slot rather than reporting a fabricated cost; once a
# slot's outputs do carry token counts, it computes a real `CostClaim` via
# `cost_per_1k_items`'s blended rate. Both paths are exercised below.
#
# The exclusion join is the guarantee this module exists to enforce: a judge's verdicts reach
# the headline only when that judge has an accepted decision for that field type. A decision
# never touches a deterministic verdict -- a rejected judge falls back to deterministic grading
# where one exists (docs/analysis-plan.md, "Judge rejection threshold"). Earlier versions keyed
# decisions by field type alone and dropped every verdict of a rejected field type,
# deterministic ones included; the tests below replace that rule.

JUDGE_A = "judge:judge-a"
JUDGES = {"slot-a": "judge-a"}  # each model slot's assigned judge, as models.yaml declares it


def _populate_two_field_types(
    con,
    *,
    decisions: tuple[tuple[str, str, str], ...] = (),
    token_count: int | None = None,
) -> None:
    """One item, one slot, one run, one output, three field types:

    - `money` (`total`): an exact verdict (correct) and a `judge:judge-a` verdict (incorrect),
      so its point estimate says which survived: 1.0 deterministic only, 0.5 both.
    - `date` (`invoice_date`): an exact verdict only; no decision can ever remove it.
    - `line_item_description` (`line_1_description`): a `judge:judge-a` verdict only.

    o1 parsed (a correct `__schema__` verdict), as grading writes before any field verdict.
    `decisions` is `(field_type, judge_slot, status)` rows for judge_decisions. `token_count`
    defaults to NULL -- the pre-migration / degraded-mode case."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute("INSERT INTO item_fields VALUES ('i1', 'total', 'money', '1.00', NULL, NULL)")
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'invoice_date', 'date', '2026-01-01', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'line_1_description', 'line_item_description', "
        "'Concrete works', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO runs VALUES ('r1', now(), NULL, 'slot-a', 'ref', 'prov', false, 's1',"
        " 'sha', 'h')"
    )
    con.execute(
        "INSERT INTO outputs VALUES ('o1', 'r1', 'i1', 1, '{}', 'call1', 'prov', NULL, 100,"
        " 'ph', now(), ?)",
        [token_count],
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v-schema', 'o1', '__schema__', 'schema', '1', 'v1', true,"
        " 'ok', now())"
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v1', 'o1', 'total', 'exact', '1', 'v1', true, 'ok', now())"
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v2', 'o1', 'invoice_date', 'exact', '1', 'v1', true,"
        " 'ok', now())"
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v3', 'o1', 'total', ?, '1', 'v1', false,"
        " 'judge majority NOT_EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v4', 'o1', 'line_1_description', ?, '1', 'v1', true,"
        " 'judge majority EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )
    for field_type, judge_slot, status in decisions:
        con.execute(
            "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, "
            "alpha_low, alpha_high, n_units, threshold, status, decided_at) "
            "VALUES (?, ?, 'v1', 0.5, 0.3, 0.7, 60, 0.667, ?, now())",
            [field_type, judge_slot, status],
        )


@pytest.fixture()
def con(tmp_path: Path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def _per_field(con) -> dict[str, Interval]:
    return _slot_accuracy(con, split=Split.PUBLIC, seed=1, judges=JUDGES)["slot-a"].per_field


def test_a_rejected_judges_verdicts_are_absent_but_deterministic_ones_stay(con):
    """Replaces `test_rejected_field_type_is_absent_from_headline_accuracy`, which asserted
    that a rejected decision removed every `money` verdict, the exact one included. The intent
    it guarded -- a rejected judge's verdicts never reach the headline -- is asserted here on
    the judge verdict itself; the deterministic verdict is the fallback and must stay."""
    _populate_two_field_types(con, decisions=(("money", "judge-a", "rejected"),))
    per_field = _per_field(con)
    assert "money" in per_field, "a judge decision removed a deterministic verdict"
    assert per_field["money"].point == 1.0, "a rejected judge's verdict reached the headline"
    assert "date" in per_field, "an undecided field type must not be swept up in the exclusion"


def test_a_counted_judge_replaces_the_deterministic_verdicts_on_its_field_type(con):
    """JP-1, decided 2026-10-15 "judge wins": money was graded by `exact` and is now judged.
    Once the judge's verdict counts, the field's older deterministic verdict stops counting
    (money 0.0 from the judge alone), not 0.5 from both. `date` has no judge and is untouched."""
    _populate_two_field_types(con, decisions=(("money", "judge-a", "accepted"),))
    per_field = _per_field(con)
    assert per_field["money"].point == 0.0
    assert "date" in per_field


def test_an_unassigned_judge_leaves_the_deterministic_fallback_in_place(con):
    """The judge only wins where it counts. An accepted decision for a judge the slot is not
    assigned (so its verdict is not counted) leaves money on its deterministic verdict."""
    _populate_two_field_types(con, decisions=(("money", "judge-a", "accepted"),))
    per_field = _slot_accuracy(con, split=Split.PUBLIC, seed=1, judges={"slot-a": None})[
        "slot-a"
    ].per_field
    assert per_field["money"].point == 1.0


def test_a_judge_verdict_with_no_decision_never_scores(con):
    """An unassessed judge is a judge we cannot defend (CLAUDE.md rule 3): before this rule an
    absent decision row meant "keep", so every judge scored until someone assessed it."""
    _populate_two_field_types(con)
    per_field = _per_field(con)
    assert "line_item_description" not in per_field
    assert per_field["money"].point == 1.0, "an unassessed judge's verdict reached the headline"


def test_a_judge_verdict_with_its_judges_acceptance_scores(con):
    _populate_two_field_types(con, decisions=(("line_item_description", "judge-a", "accepted"),))
    assert "line_item_description" in _per_field(con)


def test_another_judges_acceptance_does_not_admit_this_judge(con):
    _populate_two_field_types(con, decisions=(("line_item_description", "judge-b", "accepted"),))
    assert "line_item_description" not in _per_field(con)


def test_a_judge_verdict_with_its_judges_rejection_never_scores(con):
    _populate_two_field_types(con, decisions=(("line_item_description", "judge-a", "rejected"),))
    assert "line_item_description" not in _per_field(con)


def _reassigned_to_judge_b(con) -> None:
    """The slot was judged by judge-a, then models.yaml reassigned it to judge-b and grading
    judged the same target again; both judges hold an accepted decision on the field type."""
    _populate_two_field_types(
        con,
        decisions=(
            ("line_item_description", "judge-a", "accepted"),
            ("line_item_description", "judge-b", "accepted"),
        ),
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v5', 'o1', 'line_1_description', 'judge:judge-b', '1',"
        " 'v1', false, 'judge majority NOT_EQUIVALENT (3 of 3)', now())"
    )


def test_only_the_slots_assigned_judge_counts_after_a_reassignment(con):
    """Two accepted judges on one target would weigh the field twice in the item's cluster
    mean, with two judgements that can contradict (review 2026-10-14, I2)."""
    _reassigned_to_judge_b(con)
    judged = _slot_accuracy(con, split=Split.PUBLIC, seed=1, judges={"slot-a": "judge-b"})
    assert judged["slot-a"].per_field["line_item_description"].point == 0.0


def test_a_slot_with_no_assigned_judge_counts_no_judge_verdict(con):
    _reassigned_to_judge_b(con)
    per_field = _slot_accuracy(con, split=Split.PUBLIC, seed=1, judges={})["slot-a"].per_field
    assert "line_item_description" not in per_field
    assert per_field["money"].point == 1.0


def test_headline_verdict_ids_are_exactly_the_verdicts_the_headline_counts(con):
    """The publisher flags each published verdict with this set (`counts_toward_headline`), so
    a recompute from the published files reaches the headline. It must be the build's own rule,
    not a copy: here the exact verdicts count; judge-a's are out (reassigned away from), and
    judge-b's count (assigned, accepted, on the current target)."""
    _reassigned_to_judge_b(con)
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges={"slot-a": "judge-b"})
    assert ids == {"v1", "v2", "v5"}


def test_build_leaderboard_counts_the_judge_its_specs_assign(con):
    _reassigned_to_judge_b(con)
    con.execute("UPDATE outputs SET token_count = 2000")
    (row_,) = build_leaderboard(
        con, split=Split.PUBLIC, seed=1, specs={"slot-a": spec("slot-a", judge="judge-b")}
    )
    assert row_.per_field["line_item_description"].point == 0.0


# -- a judged field weighs what a deterministic field weighs (final review 2026-10-14, I2) ---


def _replicated_run(con, run_id: str, started_at: str) -> None:
    """Five replicates of slot-a on i1. Each has a wrong exact verdict on both deterministic
    fields; the description is the same in every replicate, so the judge target stays r1-1."""
    con.execute(
        "INSERT INTO runs VALUES (?, ?, NULL, 'slot-a', 'ref', 'prov', false, 's1', 'sha', 'h')",
        [run_id, started_at],
    )
    for replicate in range(1, 6):
        output_id = f"{run_id}-{replicate}"
        con.execute(
            "INSERT INTO outputs VALUES (?, ?, 'i1', ?, ?, 'call', 'prov', NULL, 100, 'ph',"
            " now(), NULL)",
            [output_id, run_id, replicate, json.dumps({"line_1_description": "Concrete works"})],
        )
        con.execute(
            "INSERT INTO verdicts VALUES (?, ?, '__schema__', 'schema', '1', 'v1', true, 'ok', "
            "now())",
            [f"v-{output_id}-schema", output_id],
        )
        for field_name in ("total", "invoice_date"):
            con.execute(
                "INSERT INTO verdicts VALUES (?, ?, ?, 'exact', '1', 'v1', false, 'wrong', now())",
                [f"v-{output_id}-{field_name}", output_id, field_name],
            )


def test_a_judged_field_weighs_as_much_as_a_deterministic_field_across_runs(con):
    """Worked example. Deterministic graders write a verdict per replicate; the judge writes
    one per (item, slot). Unweighted, 2 deterministic fields x 5 replicates + 1 judge verdict
    gave the judged field 1/11 of the item's score, falling to 1/21 after a second run. Weighted
    by the (item, slot)'s schema-valid graded output count (here every replicate) it is 1/3,
    the same as each deterministic field, and stays 1/3. The judged field is the only correct
    one, so the item score is its share."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute("INSERT INTO item_fields VALUES ('i1', 'total', 'money', '1.00', NULL, NULL)")
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'invoice_date', 'date', '2026-01-01', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'line_1_description', 'line_item_description', "
        "'Concrete works', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES ('line_item_description', "
        "'judge-a', 'v1', 0.9, 0.8, 0.95, 60, 0.667, 'accepted', now())"
    )
    _replicated_run(con, "r1", "2026-01-01")
    con.execute(
        "INSERT INTO verdicts VALUES ('v-judge', 'r1-1', 'line_1_description', ?, '1', 'v1', true,"
        " 'judge majority EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )

    def item_score() -> float:
        return _slot_accuracy(con, split=Split.PUBLIC, seed=1, judges=JUDGES)[
            "slot-a"
        ].accuracy.point

    assert item_score() == pytest.approx(1 / 3)
    _replicated_run(con, "r2", "2026-02-01")
    assert item_score() == pytest.approx(1 / 3)
    weights = headline_verdict_weights(con, split=Split.PUBLIC, judges=JUDGES)
    assert weights["v-judge"] == 10  # noqa: PLR2004 -- ten schema-valid outputs for (i1, slot-a)
    assert weights["v-r1-1-total"] == 1


def _weight_fixture(con) -> None:
    """The setup of the test above, one run: i1 with two deterministic fields and a judged one."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute("INSERT INTO item_fields VALUES ('i1', 'total', 'money', '1.00', NULL, NULL)")
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'invoice_date', 'date', '2026-01-01', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'line_1_description', 'line_item_description', "
        "'Concrete works', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES ('line_item_description', "
        "'judge-a', 'v1', 0.9, 0.8, 0.95, 60, 0.667, 'accepted', now())"
    )
    _replicated_run(con, "r1", "2026-01-01")
    con.execute(
        "INSERT INTO verdicts VALUES ('v-judge', 'r1-1', 'line_1_description', ?, '1', 'v1', "
        "true, 'judge majority EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )


def test_schema_invalid_outputs_do_not_add_to_the_judged_weight(con):
    """Two of the five replicates are unparseable: they carry a failed __schema__ verdict and no
    deterministic field verdicts, so each deterministic field has 3 verdicts and the judged
    field must weigh 3, not 5."""
    _weight_fixture(con)
    for output_id in ("r1-4", "r1-5"):
        con.execute(
            "UPDATE verdicts SET correct = false WHERE output_id = ? AND field_name = '__schema__'",
            [output_id],
        )
        con.execute(
            "DELETE FROM verdicts WHERE output_id = ? AND field_name IN ('total', 'invoice_date')",
            [output_id],
        )
    weights = headline_verdict_weights(con, split=Split.PUBLIC, judges=JUDGES)
    assert weights["v-judge"] == 3  # noqa: PLR2004 -- three schema-valid graded outputs


def test_ungraded_outputs_do_not_add_to_the_judged_weight(con):
    """Five outputs arrive after the grading pass and have no verdicts yet. The judged weight
    must stay at 5 until they are graded, not jump to 10."""
    _weight_fixture(con)
    con.execute(
        "INSERT INTO runs VALUES ('r2', '2026-02-01', NULL, 'slot-a', 'ref', 'prov', false, "
        "'s1', 'sha', 'h')"
    )
    for replicate in range(1, 6):
        con.execute(
            "INSERT INTO outputs VALUES (?, 'r2', 'i1', ?, '{}', 'call', 'prov', NULL, 100, 'ph', "
            "now(), NULL)",
            [f"r2-{replicate}", replicate],
        )
    weights = headline_verdict_weights(con, split=Split.PUBLIC, judges=JUDGES)
    assert weights["v-judge"] == 5  # noqa: PLR2004


def test_the_judged_weight_never_falls_below_one(con):
    _weight_fixture(con)
    con.execute("UPDATE verdicts SET correct = false WHERE field_name = '__schema__'")
    weights = headline_verdict_weights(con, split=Split.PUBLIC, judges=JUDGES)
    assert weights["v-judge"] == 1


# -- every slot is ranked on the same field set (final review 2026-10-14, I1) ----------------


def _two_slots(con, *, accepted: tuple[str, ...]) -> None:
    """One item, two slots, one output each. Each output parsed (a correct `__schema__`
    verdict) and has an exact `money` verdict and a
    judge verdict on `line_item_description` from its own slot's judge (slot-a -> judge-a,
    slot-b -> judge-b). `accepted` lists the judges holding an accepted decision on it."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute("INSERT INTO item_fields VALUES ('i1', 'total', 'money', '1.00', NULL, NULL)")
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'line_1_description', 'line_item_description', "
        "'Concrete works', NULL, NULL)"
    )
    for slot, judge in (("slot-a", "judge-a"), ("slot-b", "judge-b")):
        con.execute(
            "INSERT INTO runs VALUES (?, now(), NULL, ?, 'ref', 'prov', false, 's1', 'sha', 'h')",
            [f"r-{slot}", slot],
        )
        con.execute(
            "INSERT INTO outputs VALUES (?, ?, 'i1', 1, '{}', 'call', 'prov', NULL, 100, 'ph',"
            " now(), NULL)",
            [f"o-{slot}", f"r-{slot}"],
        )
        con.execute(
            "INSERT INTO verdicts VALUES (?, ?, '__schema__', 'schema', '1', 'v1', true, 'ok',"
            " now())",
            [f"v-schema-{slot}", f"o-{slot}"],
        )
        con.execute(
            "INSERT INTO verdicts VALUES (?, ?, 'total', 'exact', '1', 'v1', true, 'ok', now())",
            [f"v-exact-{slot}", f"o-{slot}"],
        )
        con.execute(
            "INSERT INTO verdicts VALUES (?, ?, 'line_1_description', ?, '1', 'v1', false,"
            " 'judge majority NOT_EQUIVALENT (3 of 3)', now())",
            [f"v-judge-{slot}", f"o-{slot}", f"judge:{judge}"],
        )
    for judge in accepted:
        con.execute(
            "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, "
            "alpha_low, alpha_high, n_units, threshold, status, decided_at) VALUES "
            "('line_item_description', ?, 'v1', 0.9, 0.8, 0.95, 60, 0.667, 'accepted', now())",
            [judge],
        )


TWO_JUDGES = {"slot-a": "judge-a", "slot-b": "judge-b"}


def _fields_by_slot(con, judges) -> dict[str, dict[str, float]]:
    result = _slot_accuracy(con, split=Split.PUBLIC, seed=1, judges=judges)
    return {
        slot: {ft: interval.point for ft, interval in acc.per_field.items()}
        for slot, acc in result.items()
    }


def test_a_judged_field_one_slots_judge_lacks_is_excluded_for_every_slot(con):
    """Ranking slot-a on money + descriptions against slot-b on money alone would compare
    intervals measured on different field sets without saying so: fail closed for all."""
    _two_slots(con, accepted=("judge-a",))
    assert _fields_by_slot(con, TWO_JUDGES) == {
        "slot-a": {"money": 1.0},
        "slot-b": {"money": 1.0},
    }


def test_a_judged_field_every_slots_judge_holds_counts_for_every_slot(con):
    _two_slots(con, accepted=("judge-a", "judge-b"))
    assert _fields_by_slot(con, TWO_JUDGES) == {
        "slot-a": {"money": 1.0, "line_item_description": 0.0},
        "slot-b": {"money": 1.0, "line_item_description": 0.0},
    }


def test_a_slot_with_no_assigned_judge_excludes_the_judged_field_for_every_slot(con):
    _two_slots(con, accepted=("judge-a", "judge-b"))
    assert _fields_by_slot(con, {"slot-a": "judge-a", "slot-b": None}) == {
        "slot-a": {"money": 1.0},
        "slot-b": {"money": 1.0},
    }


def test_the_shared_field_set_rule_also_decides_counts_toward_headline(con):
    _two_slots(con, accepted=("judge-a",))
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert ids == {"v-exact-slot-a", "v-exact-slot-b"}


def _old_exact_on_the_judged_field(con) -> None:
    """The rubric once graded `line_item_description` with `exact`: each slot's output keeps a
    correct exact verdict on it, beside the judge's incorrect one (JP-1)."""
    for slot in ("slot-a", "slot-b"):
        con.execute(
            "INSERT INTO verdicts VALUES (?, ?, 'line_1_description', 'exact', '1', 'v0', true,"
            " 'ok', now())",
            [f"v-old-exact-{slot}", f"o-{slot}"],
        )


def test_judge_wins_for_every_slot_when_every_slots_judge_counts(con):
    _two_slots(con, accepted=("judge-a", "judge-b"))
    _old_exact_on_the_judged_field(con)
    assert _fields_by_slot(con, TWO_JUDGES)["slot-a"]["line_item_description"] == 0.0
    assert _fields_by_slot(con, TWO_JUDGES)["slot-b"]["line_item_description"] == 0.0
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert {"v-judge-slot-a", "v-judge-slot-b"} <= ids
    assert not {"v-old-exact-slot-a", "v-old-exact-slot-b"} & ids


def test_one_slots_judge_not_counting_returns_the_old_exact_verdicts_for_every_slot(con):
    """The shared-field-set rule drops the judged type for both slots; judge-wins must then not
    drop the deterministic fallback for either."""
    _two_slots(con, accepted=("judge-a",))
    _old_exact_on_the_judged_field(con)
    fields = _fields_by_slot(con, TWO_JUDGES)
    assert fields["slot-a"]["line_item_description"] == 1.0
    assert fields["slot-b"]["line_item_description"] == 1.0
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert {"v-old-exact-slot-a", "v-old-exact-slot-b"} <= ids
    assert not {"v-judge-slot-a", "v-judge-slot-b"} & ids


def test_a_judged_type_held_back_as_incomplete_returns_the_old_exact_verdicts(con):
    """A mid-sweep build (slot-b's i2 not judged yet) holds the type back; the old exact
    verdicts on i1 are the fallback and must count, not vanish with the judge's."""
    _two_slots(con, accepted=("judge-a", "judge-b"))
    _old_exact_on_the_judged_field(con)
    _add_item_with_slot_b_unjudged(con)
    assert _fields_by_slot(con, TWO_JUDGES)["slot-a"]["line_item_description"] == 1.0
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert {"v-old-exact-slot-a", "v-old-exact-slot-b"} <= ids
    assert not {"v-judge-slot-a", "v-judge-slot-b", "v2-judge-slot-a"} & ids


def test_one_judges_acceptance_on_one_field_type_does_not_admit_it_on_another(con):
    _populate_two_field_types(con, decisions=(("line_item_description", "judge-a", "accepted"),))
    per_field = _per_field(con)
    assert per_field["money"].point == 1.0, "judge-a was admitted on a field type never assessed"


def test_latency_counts_each_output_once_not_once_per_graded_field(con):
    """Review finding (task-31): `records` has one row per verdict, so an output with two
    graded fields (money, date) surviving exclusion must still contribute exactly one
    latency observation, not two -- otherwise n and the percentiles are inflated for every
    multi-field item, which is the normal case for this domain, not an edge case."""
    _populate_two_field_types(con)
    result = _slot_accuracy(con, split=Split.PUBLIC, seed=1, judges=JUDGES)
    assert result["slot-a"].latency.n == 1


def test_retired_item_is_excluded_from_current_accuracy(con):
    """A private item that a later rotation retired (golden/rotate.py) is marked, never
    deleted, so historical verdicts against it stay valid -- but a *current* leaderboard
    build must not mix its stale outputs back into the active cohort's headline number
    (review finding: retired items were never excluded from the accuracy query)."""
    _populate_two_field_types(con)
    con.execute("UPDATE items SET split = 'private' WHERE item_id = 'i1'")
    con.execute("UPDATE items SET retired_at = now() WHERE item_id = 'i1'")
    result = _slot_accuracy(con, split=Split.PRIVATE, seed=1, judges=JUDGES)
    assert "slot-a" not in result, "a retired item's verdicts must not reach current accuracy"


def test_build_leaderboard_refuses_to_fabricate_cost(con):
    _populate_two_field_types(con, token_count=None)
    with pytest.raises(TokenCountsUnavailable):
        build_leaderboard(con, split=Split.PUBLIC, seed=1, specs={"slot-a": spec("slot-a")})


def test_build_leaderboard_reports_missing_spec_clearly(con):
    """A slot present in the store (with real token counts) but absent from `specs` --
    e.g. renamed or retired in models.yaml -- must fail with a documented error, not a bare
    KeyError (cross-file tracer finding)."""
    _populate_two_field_types(con, token_count=2000)
    with pytest.raises(SlotSpecMissing):
        build_leaderboard(con, split=Split.PUBLIC, seed=1, specs={})


def test_build_leaderboard_computes_real_cost_when_token_counts_present(con):
    _populate_two_field_types(con, token_count=2000)
    rows = build_leaderboard(con, split=Split.PUBLIC, seed=1, specs={"slot-a": spec("slot-a")})
    assert len(rows) == 1
    row_ = rows[0]
    assert row_.slot == "slot-a"
    assert row_.cost.value == cost_per_1k_items(spec("slot-a"), 2000).value
    assert "date" in row_.per_field


# -- Task 27's writer wired into Task 31's reader --------------------------------------
#
# Every judge_decisions row above is a hand-written fixture, which is exactly how the gap
# survived review: `assess` computed a status and nothing ever persisted it, so against real
# data the exclusion join could only take its `jd.status IS NULL` branch and no judge was ever
# actually excluded. These tests run the real `assess` -> `record_decision` ->
# `_slot_accuracy` chain, in both directions, so the guarantee holds end to end.


def _judge_samples(n: int = 20) -> list[Sample]:
    return [
        Sample(presentation_order=i % 2, raw="EQUIVALENT", observed_length=10 + i) for i in range(n)
    ]


def _decide(con, *, agree: bool, judge_slot: str = "judge-a"):
    """Assess a real judge-vs-human disagreement for field type `money`, and persist it."""
    judge = {str(i): "EQUIVALENT" for i in range(60)}
    if agree:
        human = {str(i): "EQUIVALENT" if i % 3 else "NOT_EQUIVALENT" for i in range(60)}
        judge = dict(human)
    else:
        human = {str(i): "EQUIVALENT" if i % 2 else "NOT_EQUIVALENT" for i in range(60)}
    report = assess("money", judge, human, _judge_samples(), seed=1, n_resamples=200)
    record_decision(con, report, rubric_version="v1", judge_slot=judge_slot)
    return report


def test_a_persisted_rejection_actually_excludes_that_judges_verdicts(con):
    """Rewritten with the per-judge key: the rejection removes judge-a's `money` verdict and
    leaves the deterministic `money` verdict, the fallback, in place."""
    _populate_two_field_types(con)
    report = _decide(con, agree=False)
    assert report.status is JudgeStatus.REJECTED

    per_field = _per_field(con)
    assert per_field["money"].point == 1.0, (
        "assess() rejected this judge and record_decision() stored it, yet its verdicts still "
        "reached the headline number"
    )
    assert "date" in per_field


def test_a_persisted_acceptance_lets_that_judges_verdicts_in(con):
    """The other direction, and the guard on the enum/CHECK case mismatch: `JudgeStatus`
    renders "ACCEPTED"/"REJECTED" but the column's CHECK and build.py's `= 'accepted'` are
    both lowercase. Writing the enum verbatim raises on insert; writing the wrong case
    silently never matches the admission, which looks identical to the rejection test above
    unless this direction is asserted too."""
    _populate_two_field_types(con)
    report = _decide(con, agree=True)
    assert report.status is JudgeStatus.ACCEPTED

    stored = con.execute(
        "SELECT status FROM judge_decisions WHERE field_type = 'money' AND judge_slot = 'judge-a'"
    ).fetchone()
    assert stored == ("accepted",), "judge_decisions.status must be stored lowercase"

    per_field = _per_field(con)
    # Judge wins (JP-1): the accepted judge-a's verdict (false) replaces the exact one (true).
    assert per_field["money"].point == 0.0
    assert "date" in per_field


def test_a_persisted_acceptance_for_another_judge_does_not_admit_this_one(con):
    _populate_two_field_types(con)
    _decide(con, agree=True, judge_slot="judge-b")
    assert _per_field(con)["money"].point == 1.0


def test_re_deciding_a_judge_replaces_rather_than_raising(con):
    """`(field_type, judge_slot)` is the primary key: a second assessment (more labels, a
    re-run) must update the standing decision, not fail on a duplicate key."""
    _populate_two_field_types(con)
    _decide(con, agree=True)
    _decide(con, agree=False)
    rows = con.execute(
        "SELECT judge_slot, status FROM judge_decisions WHERE field_type = 'money'"
    ).fetchall()
    assert rows == [("judge-a", "rejected")]


# -- one judge verdict per (item, slot, field): the current modal target's ------------------


def test_a_stale_judge_verdict_on_a_former_modal_target_does_not_count(con):
    """The judge scores one output per (item, slot): the replicate holding the modal value
    (`graders.judge.targets.select_judge_targets`). Replicates added after a grading pass can
    move the modal value to another output; grading then writes a verdict for the new target,
    and the old target's verdict stays in the append-only `verdicts` table. Counting both would
    score one (item, slot, field) twice with two different judgements."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'line_1_description', 'line_item_description', "
        "'Concrete works', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO runs VALUES ('r1', now(), NULL, 'slot-a', 'ref', 'prov', false, 's1',"
        " 'sha', 'h')"
    )
    for output_id, replicate, value in (("o1", 1, "Concrete"), ("o2", 2, "Concrete works")):
        con.execute(
            "INSERT INTO outputs VALUES (?, 'r1', 'i1', ?, ?, 'call', 'prov', NULL, 100, 'ph',"
            " now(), NULL)",
            [output_id, replicate, json.dumps({"line_1_description": value})],
        )
    # Graded when o1 was the only replicate, so o1 was the modal target then.
    con.execute(
        "INSERT INTO verdicts VALUES ('v-stale', 'o1', 'line_1_description', ?, '1', 'v1', false,"
        " 'judge majority NOT_EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )
    con.execute(
        "INSERT INTO outputs VALUES ('o3', 'r1', 'i1', 3, ?, 'call', 'prov', NULL, 100, 'ph',"
        " now(), NULL)",
        [json.dumps({"line_1_description": "Concrete works"})],
    )
    # Re-graded after o3 arrived: "Concrete works" is now modal and o2 is its first replicate.
    con.execute(
        "INSERT INTO verdicts VALUES ('v-current', 'o2', 'line_1_description', ?, '1', 'v1', true,"
        " 'judge majority EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )
    con.execute(
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES ('line_item_description', "
        "'judge-a', 'v1', 0.9, 0.8, 0.95, 60, 0.667, 'accepted', now())"
    )
    interval = _per_field(con)["line_item_description"]
    assert interval.point == 1.0, "the stale target's judge verdict was counted beside the current"


def test_a_re_run_with_the_same_modal_value_keeps_the_judged_field_in_the_headline(con):
    """Build and grading select the judge target with the same function, so they agree by
    construction; this pins that agreement across a scheduled re-run. Appending a run whose
    modal value is unchanged must not move the target off the judged output, or build would
    drop the field until the new target was judged again (review 2026-10-14, I1)."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'line_1_description', 'line_item_description', "
        "'B', NULL, NULL)"
    )
    for run_id, started_at, values in (
        ("r1", "2026-01-01", "ABBAB"),
        ("r2", "2026-02-01", "BAABB"),
    ):
        con.execute(
            "INSERT INTO runs VALUES (?, ?, NULL, 'slot-a', 'ref', 'prov', false, 's1', 'sha',"
            " 'h')",
            [run_id, started_at],
        )
        for replicate, value in enumerate(values, start=1):
            con.execute(
                "INSERT INTO outputs VALUES (?, ?, 'i1', ?, ?, 'call', 'prov', NULL, 100, 'ph',"
                " now(), NULL)",
                [
                    f"{run_id}-{replicate}",
                    run_id,
                    replicate,
                    json.dumps({"line_1_description": value}),
                ],
            )
    # Judged when r1 was the only run: "B" was modal and r1-2 its first replicate.
    con.execute(
        "INSERT INTO verdicts VALUES ('v-judged', 'r1-2', 'line_1_description', ?, '1', 'v1',"
        " true, 'judge majority EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )
    con.execute(
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES ('line_item_description', "
        "'judge-a', 'v1', 0.9, 0.8, 0.95, 60, 0.667, 'accepted', now())"
    )
    assert "line_item_description" in _per_field(con), "a re-run moved the judge target"


# -- a re-graded verdict supersedes the old one (judge-wiring open item: re-grade double count) --


def test_a_regraded_verdict_replaces_the_old_one_instead_of_counting_twice(con):
    """A grader version bump appends a second verdict for the same output and field. Only the
    latest counts: slot-a's money was correct under grader 1 and wrong under grader 2, so its
    money accuracy is 0.0, not the 0.5 that counting both would give."""
    _two_slots(con, accepted=())
    con.execute(
        "INSERT INTO verdicts VALUES ('v-exact-slot-a-g2', 'o-slot-a', 'total', 'exact', '2', "
        "'v1', false, 'regraded', now() + INTERVAL 1 SECOND)"
    )
    assert _fields_by_slot(con, TWO_JUDGES)["slot-a"] == {"money": 0.0}
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert ids == {"v-exact-slot-a-g2", "v-exact-slot-b"}


def test_the_judge_verdict_wins_over_a_deterministic_one_on_the_same_field(con):
    """JP-1: re-grade supersession stays per grader (the table keeps both rows), but the
    headline counts the judge's verdict alone on a field type it counts for."""
    _populate_two_field_types(con, decisions=(("money", "judge-a", "accepted"),))
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=JUDGES)
    assert "v3" in ids
    assert "v1" not in ids  # exact on o1's `total`, superseded by the judged field type
    assert "v2" in ids  # `date` has no judge


def test_the_deterministic_verdict_stays_in_the_ids_where_the_judge_does_not_count(con):
    _populate_two_field_types(con, decisions=(("money", "judge-a", "rejected"),))
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=JUDGES)
    assert "v1" in ids
    assert "v3" not in ids


def test_a_field_moved_to_another_deterministic_grader_counts_once(con):
    """Final review 2026-10-15, I1: a rubric that moves money from `exact` to
    `numeric_tolerance`, then a re-grade, leaves both graders' verdicts on o-slot-a's total.
    Keyed by grader, both counted (money 0.5) and the field weighed 2 against the judge's 1.
    Across deterministic graders the latest verdict wins."""
    _two_slots(con, accepted=())
    con.execute(
        "INSERT INTO verdicts VALUES ('v-tol-slot-a', 'o-slot-a', 'total', 'numeric_tolerance', "
        "'1', 'v2', false, 'outside tolerance', now() + INTERVAL 1 SECOND)"
    )
    assert _fields_by_slot(con, TWO_JUDGES)["slot-a"] == {"money": 0.0}
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert "v-tol-slot-a" in ids
    assert "v-exact-slot-a" not in ids


def test_a_regrade_at_a_bumped_rubric_version_also_supersedes(con):
    _two_slots(con, accepted=())
    con.execute(
        "INSERT INTO verdicts VALUES ('v-exact-slot-a-r2', 'o-slot-a', 'total', 'exact', '1', "
        "'v2', false, 'rubric bump', now() + INTERVAL 1 SECOND)"
    )
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert "v-exact-slot-a-r2" in ids
    assert "v-exact-slot-a" not in ids


def test_equal_computed_at_is_broken_by_the_greater_verdict_id(con):
    """Two verdicts written in one clock tick: the order must not be the engine's."""
    _two_slots(con, accepted=())
    con.execute("UPDATE verdicts SET computed_at = TIMESTAMPTZ '2026-10-15 08:00:00+00'")
    con.execute(
        "INSERT INTO verdicts VALUES ('v-exact-slot-a-z', 'o-slot-a', 'total', 'exact', '2', "
        "'v1', false, 'same tick', TIMESTAMPTZ '2026-10-15 08:00:00+00')"
    )
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert "v-exact-slot-a-z" in ids  # 'v-exact-slot-a-z' > 'v-exact-slot-a'
    assert "v-exact-slot-a" not in ids


# -- a schema re-grade decides whether the output counts (final review 2026-10-15, I2) --------


def _regrade_schema(con, output_id: str, *, correct: bool, version: str, second: int) -> None:
    """Grading at grader version `version`, `second` seconds after the fixture's pass: a new
    `__schema__` verdict, and -- only when it parsed -- new verdicts on both deterministic
    fields (grade.py writes no field verdict for an unparseable output)."""
    at = f"now() + INTERVAL {second} SECOND"
    con.execute(
        f"INSERT INTO verdicts VALUES (?, ?, '__schema__', 'schema', ?, 'v1', ?, 'regrade', {at})",
        [f"v-{output_id}-schema-{version}", output_id, version, correct],
    )
    if correct:
        for field_name in ("total", "invoice_date"):
            con.execute(
                f"INSERT INTO verdicts VALUES (?, ?, ?, 'exact', ?, 'v1', false, 'wrong', {at})",
                [f"v-{output_id}-{field_name}-{version}", output_id, field_name, version],
            )


def _deterministic_ids(con) -> dict[str, set[str]]:
    """The counted deterministic verdict ids, by field name."""
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=JUDGES)
    by_field: dict[str, set[str]] = {"total": set(), "invoice_date": set()}
    for verdict_id, field_name in con.execute(
        "SELECT verdict_id, field_name FROM verdicts "
        "WHERE field_name IN ('total', 'invoice_date') AND grader_id NOT LIKE 'judge:%'"
    ).fetchall():
        if verdict_id in ids:
            by_field[field_name].add(verdict_id)
    return by_field


def test_an_output_re_graded_as_unparseable_counts_for_neither(con):
    """grade.py writes a new `__schema__` verdict and, when it fails, no field verdict, so
    r1-5's old exact verdicts were still the latest of their field and kept counting, and the
    judged weight (any correct schema verdict, ever) still counted r1-5. The published rule
    (methodology, the judged field's weight) is that a schema-invalid output counts for
    neither: its deterministic verdicts drop out and the judged weight drops by one."""
    _weight_fixture(con)
    _regrade_schema(con, "r1-5", correct=False, version="2", second=1)
    by_field = _deterministic_ids(con)
    assert "v-r1-5-total" not in by_field["total"]
    assert "v-r1-5-invoice_date" not in by_field["invoice_date"]
    weight = headline_verdict_weights(con, split=Split.PUBLIC, judges=JUDGES)["v-judge"]
    assert weight == 4  # noqa: PLR2004
    assert {len(ids) for ids in by_field.values()} == {weight}


def test_the_judged_weight_floor_holds_when_every_output_is_re_graded_unparseable(con):
    _weight_fixture(con)
    for replicate in range(1, 6):
        _regrade_schema(con, f"r1-{replicate}", correct=False, version="2", second=1)
    assert _deterministic_ids(con) == {"total": set(), "invoice_date": set()}
    # The judge verdict on the unparseable modal target still counts (it scores as absent).
    assert headline_verdict_weights(con, split=Split.PUBLIC, judges=JUDGES)["v-judge"] == 1


def test_an_output_re_graded_unparseable_then_parseable_counts_again(con):
    _weight_fixture(con)
    _regrade_schema(con, "r1-5", correct=False, version="2", second=1)
    _regrade_schema(con, "r1-5", correct=True, version="3", second=2)
    by_field = _deterministic_ids(con)
    assert "v-r1-5-total-3" in by_field["total"]
    assert "v-r1-5-total" not in by_field["total"]  # superseded by the version-3 re-grade
    weight = headline_verdict_weights(con, split=Split.PUBLIC, judges=JUDGES)["v-judge"]
    assert weight == 5  # noqa: PLR2004
    assert {len(ids) for ids in by_field.values()} == {weight}


def test_the_judged_weight_matches_the_deterministic_count_across_re_grades(con):
    """The invariant behind the weight: for every (item, slot), the judged field weighs exactly
    as many verdicts as each deterministic field has, through a grader move on one field, a
    rubric bump on another, and schema flips (r1-3 out, r1-4 out and back)."""
    _weight_fixture(con)
    con.execute(
        "INSERT INTO verdicts VALUES ('v-r1-1-total-tol', 'r1-1', 'total', 'numeric_tolerance', "
        "'1', 'v2', true, 'within', now() + INTERVAL 1 SECOND)"
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v-r1-2-date-r2', 'r1-2', 'invoice_date', 'exact', '1', "
        "'v2', true, 'rubric bump', now() + INTERVAL 1 SECOND)"
    )
    _regrade_schema(con, "r1-3", correct=False, version="2", second=2)
    _regrade_schema(con, "r1-4", correct=False, version="2", second=2)
    _regrade_schema(con, "r1-4", correct=True, version="3", second=3)
    by_field = _deterministic_ids(con)
    weight = headline_verdict_weights(con, split=Split.PUBLIC, judges=JUDGES)["v-judge"]
    assert {field: len(ids) for field, ids in by_field.items()} == {"total": 4, "invoice_date": 4}
    assert weight == 4  # noqa: PLR2004
    assert "v-r1-1-total-tol" in by_field["total"]
    assert "v-r1-2-date-r2" in by_field["invoice_date"]


# -- what holds a judged type back: a target with no verdict from the current judge -----------


def test_a_reassigned_judge_with_no_verdict_yet_holds_the_judged_type_back(con):
    """slot-b was reassigned to judge-c (accepted) after judge-b judged its target. judge-b's
    verdict no longer counts and judge-c has none yet: the target is unjudged, so the type is
    out for every slot."""
    _two_slots(con, accepted=("judge-a", "judge-b", "judge-c"))
    fields = _fields_by_slot(con, {"slot-a": "judge-a", "slot-b": "judge-c"})
    assert "line_item_description" not in fields["slot-a"]
    assert "line_item_description" not in fields["slot-b"]


def test_a_moved_modal_target_with_no_verdict_yet_holds_the_judged_type_back(con):
    """slot-a's only judge verdict is on o1, the modal target before o2 and o3 arrived; the
    target is now o2, which has no verdict yet."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i1', 'public', 'v1', 'synthetic', 'h', now())"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i1', 'line_1_description', 'line_item_description', "
        "'Concrete works', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO runs VALUES ('r1', now(), NULL, 'slot-a', 'ref', 'prov', false, 's1',"
        " 'sha', 'h')"
    )
    for output_id, replicate, value in (
        ("o1", 1, "Concrete"),
        ("o2", 2, "Concrete works"),
        ("o3", 3, "Concrete works"),
    ):
        con.execute(
            "INSERT INTO outputs VALUES (?, 'r1', 'i1', ?, ?, 'call', 'prov', NULL, 100, 'ph',"
            " now(), NULL)",
            [output_id, replicate, json.dumps({"line_1_description": value})],
        )
    con.execute(
        "INSERT INTO verdicts VALUES ('v-stale', 'o1', 'line_1_description', ?, '1', 'v1', false,"
        " 'judge majority NOT_EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )
    con.execute(
        "INSERT INTO judge_decisions (field_type, judge_slot, rubric_version, alpha, alpha_low, "
        "alpha_high, n_units, threshold, status, decided_at) VALUES ('line_item_description', "
        "'judge-a', 'v1', 0.9, 0.8, 0.95, 60, 0.667, 'accepted', now())"
    )
    # i2 is fully judged, so the type would count through i2 if nothing held it back; the stale
    # verdict on o1 never counts. Only the hold-back keeps the type out. (Asserting an empty
    # result instead passes with the hold-back broken, because o1's verdict is stale anyway.)
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i2', 'public', 'v1', 'synthetic', 'h2', now())"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i2', 'line_1_description', 'line_item_description', "
        "'Rebar', NULL, NULL)"
    )
    con.execute(
        "INSERT INTO outputs VALUES ('o-i2', 'r1', 'i2', 1, ?, 'call', 'prov', NULL, 100, 'ph', "
        "now(), NULL)",
        [json.dumps({"line_1_description": "Rebar"})],
    )
    con.execute(
        "INSERT INTO verdicts VALUES ('v-i2', 'o-i2', 'line_1_description', ?, '1', 'v1', true,"
        " 'judge majority EQUIVALENT (3 of 3)', now())",
        [JUDGE_A],
    )
    result = _slot_accuracy(con, split=Split.PUBLIC, seed=1, judges=JUDGES)
    per_field = result["slot-a"].per_field if "slot-a" in result else {}
    assert "line_item_description" not in per_field


# -- a judged field counts only once every current target is judged (open item: completeness) --


def _add_item_with_slot_b_unjudged(con) -> None:
    """A second item, i2, with a description field; slot-a's output has a judge verdict,
    slot-b's has none yet."""
    con.execute(
        "INSERT INTO items (item_id, split, rubric_version, source, content_hash, created_at) "
        "VALUES ('i2', 'public', 'v1', 'synthetic', 'h2', now())"
    )
    con.execute(
        "INSERT INTO item_fields VALUES ('i2', 'line_1_description', 'line_item_description', "
        "'Rebar', NULL, NULL)"
    )
    for slot in ("slot-a", "slot-b"):
        con.execute(
            "INSERT INTO outputs VALUES (?, ?, 'i2', 1, ?, 'call', 'prov', NULL, 100, 'ph', "
            "now(), NULL)",
            [f"o2-{slot}", f"r-{slot}", json.dumps({"line_1_description": "Rebar"})],
        )
    con.execute(
        "INSERT INTO verdicts VALUES ('v2-judge-slot-a', 'o2-slot-a', 'line_1_description', "
        "'judge:judge-a', '1', 'v1', true, 'judge majority EQUIVALENT (3 of 3)', now())"
    )


def test_a_judged_field_with_an_unjudged_target_is_dropped_for_every_slot(con):
    """slot-b's i2 output is not judged yet. Counting slot-a's judged i2 would rank slot-a on
    descriptions for two items and slot-b for one: drop the field type everywhere."""
    _two_slots(con, accepted=("judge-a", "judge-b"))
    _add_item_with_slot_b_unjudged(con)
    fields = _fields_by_slot(con, TWO_JUDGES)
    assert "line_item_description" not in fields["slot-a"]
    assert "line_item_description" not in fields["slot-b"]
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert not {"v-judge-slot-a", "v-judge-slot-b", "v2-judge-slot-a"} & ids


def test_the_judged_field_returns_once_the_last_target_is_judged(con):
    _two_slots(con, accepted=("judge-a", "judge-b"))
    _add_item_with_slot_b_unjudged(con)
    con.execute(
        "INSERT INTO verdicts VALUES ('v2-judge-slot-b', 'o2-slot-b', 'line_1_description', "
        "'judge:judge-b', '1', 'v1', true, 'judge majority EQUIVALENT (3 of 3)', now())"
    )
    assert "line_item_description" in _fields_by_slot(con, TWO_JUDGES)["slot-a"]


def test_an_inconclusive_verdict_counts_as_judged_not_as_missing(con):
    """Inconclusive is a measurement (correct = false, reported in the inconclusive table), so
    it must not trip the completeness gate."""
    _two_slots(con, accepted=("judge-a", "judge-b"))
    _add_item_with_slot_b_unjudged(con)
    con.execute(
        "INSERT INTO verdicts VALUES ('v2-judge-slot-b', 'o2-slot-b', 'line_1_description', "
        "'judge:judge-b', '1', 'v1', false, 'judge inconclusive: no majority in 3 samples', "
        "now())"
    )
    assert "line_item_description" in _fields_by_slot(con, TWO_JUDGES)["slot-b"]


def test_completeness_ignores_retired_items(con):
    _two_slots(con, accepted=("judge-a", "judge-b"))
    _add_item_with_slot_b_unjudged(con)
    con.execute("UPDATE items SET retired_at = now() WHERE item_id = 'i2'")
    assert "line_item_description" in _fields_by_slot(con, TWO_JUDGES)["slot-a"]


def test_completeness_ignores_the_other_split(con):
    """An unjudged target on a private item must not hold back the public headline."""
    _two_slots(con, accepted=("judge-a", "judge-b"))
    _add_item_with_slot_b_unjudged(con)
    con.execute("UPDATE items SET split = 'private' WHERE item_id = 'i2'")
    assert "line_item_description" in _fields_by_slot(con, TWO_JUDGES)["slot-a"]
