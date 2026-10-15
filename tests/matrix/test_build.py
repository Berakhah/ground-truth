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


def test_an_accepted_judges_verdicts_count_beside_deterministic_ones(con):
    _populate_two_field_types(con, decisions=(("money", "judge-a", "accepted"),))
    per_field = _per_field(con)
    assert per_field["money"].point == 0.5  # noqa: PLR2004 -- exact (true) + judge (false)
    assert "date" in per_field


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
    con.execute(
        "INSERT INTO verdicts VALUES ('v-schema', 'o1', '__schema__', 'schema', '1', 'v1', true,"
        " 'ok', now())"
    )
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
    by the (item, slot)'s replicate count it is 1/3, the same as each deterministic field, and
    stays 1/3. The judged field is the only correct one, so the item score is its share."""
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
    assert weights["v-judge"] == 10  # noqa: PLR2004 -- ten replicate outputs for (i1, slot-a)
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
    """One item, two slots, one output each. Each output has an exact `money` verdict and a
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
    assert per_field["money"].point == 0.5  # noqa: PLR2004 -- exact (true) + judge-a (false)
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


def test_a_regrade_is_per_grader_so_a_different_grader_on_the_same_field_still_counts(con):
    """The supersession key includes grader_id: a judge verdict is not replaced by an exact
    one on the same output and field."""
    _two_slots(con, accepted=("judge-a", "judge-b"))
    ids = headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)
    assert {"v-judge-slot-a", "v-judge-slot-b"} <= ids


def test_a_regrade_at_a_bumped_rubric_version_also_supersedes(con):
    _two_slots(con, accepted=())
    con.execute(
        "INSERT INTO verdicts VALUES ('v-exact-slot-a-r2', 'o-slot-a', 'total', 'exact', '1', "
        "'v2', false, 'rubric bump', now() + INTERVAL 1 SECOND)"
    )
    assert "v-exact-slot-a" not in headline_verdict_ids(con, split=Split.PUBLIC, judges=TWO_JUDGES)


# -- a judged field counts only once every current target is judged (open item: completeness) --


def _add_item_with_slot_b_unjudged(con) -> None:
    """A second item, i2, with a description field; slot-a's output has a judge verdict,
    slot-b's has none (fewer than three samples so far)."""
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
