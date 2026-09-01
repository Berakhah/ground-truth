# tests/test_degraded_mode.py
from pathlib import Path

import pytest

from ground_truth._bok_shim import CallContext, assert_blackout_complete, blackout
from ground_truth.golden.generate import generate
from ground_truth.golden.rubric import loaded_rubric
from ground_truth.grade import grade_stored_outputs
from ground_truth.runner import execute_sweep
from ground_truth.store.db import connect, migrate
from tests.test_runner import FakeGateway

RUBRIC = Path(__file__).resolve().parents[1] / "docs" / "rubric.md"


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


def test_grade_module_imports_no_provider_code():
    import inspect  # noqa: PLC0415

    from ground_truth import grade  # noqa: PLC0415

    source = inspect.getsource(grade)
    assert "_bok_shim" not in source and "from ground_truth.runner" not in source
