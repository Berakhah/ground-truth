# tests/test_degraded_mode.py
import json
from dataclasses import dataclass
from dataclasses import field as dc_field
from pathlib import Path

import pytest

from ground_truth._bok_shim import (
    CacheMode,
    CallContext,
    FailoverMode,
    Response,
    assert_blackout_complete,
    blackout,
)
from ground_truth.golden.generate import generate
from ground_truth.golden.rubric import loaded_rubric
from ground_truth.golden.schema import Item
from ground_truth.grade import GradingConflict, grade_stored_outputs
from ground_truth.runner import build_prompt, execute_sweep
from ground_truth.store.db import connect, migrate
from tests.test_runner import FakeGateway

_MIN_VERDICTS = 100  # ten items' worth of verdicts is comfortably more
RUBRIC = Path(__file__).resolve().parents[1] / "docs" / "rubric.md"


@dataclass
class CorrectFakeGateway(FakeGateway):
    """Returns each item's own real field values as the "extraction", so grade_schema
    passes and grade_stored_outputs' per-field dispatch chain actually runs.

    FakeGateway's fixed `'{"contract_sum": "1.00"}'` response fails grade_schema for every
    item (missing nearly all of an item's real fields), so every existing test hits
    grade.py's early `continue` before ever reaching grade_exact/grade_normalised/
    grade_numeric_tolerance or grade_arithmetic (final review item 3, grade.py at 66%
    coverage, the lowest in the repo). `call()` has no direct handle on which item it's
    being asked about -- only the prompt text -- so responses are keyed by the exact prompt
    `build_prompt` emits for each item, built once up front via `for_items`.
    """

    responses: dict[str, str] = dc_field(default_factory=dict)

    @classmethod
    def for_items(cls, items: list[Item]) -> "CorrectFakeGateway":
        return cls(
            responses={
                build_prompt(item).value: json.dumps(
                    {f.field_name: f.expected_value for f in item.fields}
                )
                for item in items
            }
        )

    def call(  # noqa: PLR0913 -- mirrors router.call's contract-shaped signature
        self,
        handle,
        payload,
        context,
        *,
        response_schema=None,
        tools_disabled=False,
        cache=CacheMode.ENABLED,
        failover=FailoverMode.ENABLED,
    ) -> Response:
        self.seen.append((handle.slot, cache, failover, payload.sensitivity, context.commercial))
        return Response(
            text=self.responses[payload.value],
            ledger_call_id=f"{handle.slot}-{len(self.seen)}",
            provider_served="fake",
            fingerprint=None,
            latency_ms=42,
            tokens=123,
        )


@pytest.fixture()
def populated(tmp_path):
    con = connect(tmp_path / "t.duckdb")
    migrate(con)
    items = generate(count=10, seed=1, rubric_version="v1")
    gw = FakeGateway()
    execute_sweep(
        con,
        items,
        ["slot-a"],
        replicates=5,
        context=CallContext(),
        resolve_fn=gw.resolve,
        call_fn=gw.call,
        allow_dirty=True,
    )
    yield con, items
    con.close()


def test_degraded_mode_still_produces_findings(populated):
    """Ground Truth's declared floor is ZERO gateway calls in phase 2, not a percentage.

    blackout() makes every lane raise, and defeats the response cache, the probe TTL cache
    and the fallback chain -- so a code path that quietly reached a provider cannot hide.
    assert_blackout_complete() then confirms none did.
    """
    con, items = populated
    with blackout():
        written = grade_stored_outputs(con, items, loaded_rubric(RUBRIC))
        assert_blackout_complete()
    assert written > 0, "phase 2 must produce verdicts with every provider disabled"


def test_grading_never_appends_to_outputs(populated):
    con, items = populated
    before = con.execute("SELECT count(*) FROM outputs").fetchone()[0]
    grade_stored_outputs(con, items, loaded_rubric(RUBRIC))
    after = con.execute("SELECT count(*) FROM outputs").fetchone()[0]
    assert before == after, "phase 2 must never append to the immutable outputs table"


def test_regrading_at_the_same_version_is_idempotent(populated):
    con, items = populated
    rubric = loaded_rubric(RUBRIC)
    grade_stored_outputs(con, items, rubric)
    first = con.execute("SELECT count(*) FROM verdicts").fetchone()[0]
    grade_stored_outputs(con, items, rubric)
    assert con.execute("SELECT count(*) FROM verdicts").fetchone()[0] == first


def test_regrading_that_disagrees_with_a_stored_verdict_fails_loudly(
    populated_with_correct_outputs,
):
    """JP-2: the verdict key has no outcome in it, so a re-grade at the same grader version that
    reaches a different answer used to be dropped by INSERT OR IGNORE, leaving the old verdict
    standing. Grader versions only change by a bump, so a disagreement at the same version means
    an output or a grader changed under the record: say so, naming the verdict."""
    con, items = populated_with_correct_outputs
    rubric = loaded_rubric(RUBRIC)
    grade_stored_outputs(con, items, rubric)
    output_id = con.execute("SELECT output_id FROM outputs LIMIT 1").fetchone()[0]
    con.execute("UPDATE outputs SET raw_output = 'not json' WHERE output_id = ?", [output_id])
    with pytest.raises(GradingConflict, match=output_id) as excinfo:
        grade_stored_outputs(con, items, rubric)
    assert "__schema__" in str(excinfo.value)
    stored = con.execute(
        "SELECT correct FROM verdicts WHERE output_id = ? AND field_name = '__schema__'",
        [output_id],
    ).fetchall()
    assert stored == [(True,)], "the stored verdict must be left as it was, not overwritten"


class _CountingConnection:
    """Delegates to a real connection and keeps every SQL string it was asked to run."""

    def __init__(self, con):
        self._con = con
        self.sql: list[str] = []

    def execute(self, query, *args, **kwargs):
        self.sql.append(" ".join(query.split()).upper())
        return self._con.execute(query, *args, **kwargs)

    def __getattr__(self, name):
        return getattr(self._con, name)


def test_grading_writes_with_a_plain_insert_and_a_regrade_writes_nothing(
    populated_with_correct_outputs,
):
    """`INSERT OR IGNORE` against the verdicts table's unique index cost 6-10 ms a row however
    the writes were grouped, 99% of a grading pass (a plain INSERT: ~1 ms). `_write_verdict`
    already looks the key up first, so a key that exists is skipped there and a new one is a
    plain INSERT. A re-grade of an unchanged store therefore issues no INSERT at all."""
    con, items = populated_with_correct_outputs
    rubric = loaded_rubric(RUBRIC)
    first = _CountingConnection(con)
    written = grade_stored_outputs(first, items, rubric)
    inserts = [q for q in first.sql if q.startswith("INSERT")]
    assert len(inserts) == written > _MIN_VERDICTS
    assert not [q for q in inserts if "OR IGNORE" in q]
    again = _CountingConnection(con)
    assert grade_stored_outputs(again, items, rubric) == 0
    assert not [q for q in again.sql if q.startswith("INSERT")]


def test_grade_module_imports_no_provider_code():
    import inspect  # noqa: PLC0415

    from ground_truth import grade  # noqa: PLC0415

    source = inspect.getsource(grade)
    assert "_bok_shim" not in source and "from ground_truth.runner" not in source


@pytest.fixture()
def populated_with_correct_outputs(tmp_path):
    con = connect(tmp_path / "t.duckdb")
    migrate(con)
    items = generate(count=10, seed=1, rubric_version="v1")
    gw = CorrectFakeGateway.for_items(items)
    execute_sweep(
        con,
        items,
        ["slot-a"],
        replicates=1,
        context=CallContext(),
        resolve_fn=gw.resolve,
        call_fn=gw.call,
        allow_dirty=True,
    )
    yield con, items
    con.close()


def test_grade_stored_outputs_per_field_dispatch_chain_actually_runs(
    populated_with_correct_outputs,
):
    """Final review item 3. Before this test existed, nothing in the suite ever produced a
    stored output that passed grade_schema, so grade_stored_outputs' per-field loop, the
    grade_arithmetic call, and the "__arithmetic__" verdict were dead code as far as the test
    suite could tell -- including the exact code path that would have caught item 1's
    grade_exact bug. This is the composition-point guard: it fails again if that regresses.
    """
    con, items = populated_with_correct_outputs
    written = grade_stored_outputs(con, items, loaded_rubric(RUBRIC))
    assert written > 0

    field_names = {
        row[0] for row in con.execute("SELECT DISTINCT field_name FROM verdicts").fetchall()
    }
    assert field_names - {"__schema__"}, "the per-field dispatch chain never ran"
    assert "__arithmetic__" in field_names, "grade_arithmetic was never reached"

    schema_verdicts = con.execute(
        "SELECT correct FROM verdicts WHERE field_name = '__schema__'"
    ).fetchall()
    assert schema_verdicts and all(correct for (correct,) in schema_verdicts), (
        "a genuinely correct extraction must pass grade_schema, or nothing downstream runs"
    )


def test_judge_target_selection_needs_no_gateway():
    import ast  # noqa: PLC0415

    from ground_truth.graders.judge import targets  # noqa: PLC0415

    tree = ast.parse(Path(targets.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    forbidden = {"ground_truth._bok_shim", "ground_truth.runner", "ground_truth.judge_runner"}
    assert not imported & forbidden
