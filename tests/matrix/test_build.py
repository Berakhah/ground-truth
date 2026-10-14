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
)
from ground_truth.matrix.cost import LIST_PRICE_CAVEAT, cost_per_1k_items
from ground_truth.matrix.latency import summarise_latency
from ground_truth.providers import SlotSpec
from ground_truth.stats.bootstrap import Interval
from ground_truth.store.db import connect, migrate


def spec(slot: str) -> SlotSpec:
    return SlotSpec(
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
    return _slot_accuracy(con, split=Split.PUBLIC, seed=1)["slot-a"].per_field


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
    result = _slot_accuracy(con, split=Split.PUBLIC, seed=1)
    assert result["slot-a"].latency.n == 1


def test_retired_item_is_excluded_from_current_accuracy(con):
    """A private item that a later rotation retired (golden/rotate.py) is marked, never
    deleted, so historical verdicts against it stay valid -- but a *current* leaderboard
    build must not mix its stale outputs back into the active cohort's headline number
    (review finding: retired items were never excluded from the accuracy query)."""
    _populate_two_field_types(con)
    con.execute("UPDATE items SET split = 'private' WHERE item_id = 'i1'")
    con.execute("UPDATE items SET retired_at = now() WHERE item_id = 'i1'")
    result = _slot_accuracy(con, split=Split.PRIVATE, seed=1)
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
