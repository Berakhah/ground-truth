import pytest

from ground_truth._bok_shim import CallContext, Quota
from ground_truth.golden.generate import generate
from ground_truth.runner import execute_sweep, pending_work
from ground_truth.schedule import WorkUnit, plan_batches
from ground_truth.store.db import connect, migrate
from tests.test_runner import FakeGateway


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_pending_work_is_everything_before_any_run(con):
    items = generate(count=4, seed=1, rubric_version="v1")
    units = pending_work(con, "sweep-1", items, ["slot-a", "slot-b"], replicates=5)
    assert len(units) == 4 * 2 * 5


def _sweep(con, items, slots, replicates):
    gw = FakeGateway()
    return execute_sweep(con, items, slots, replicates, context=CallContext(),
                         resolve_fn=gw.resolve, call_fn=gw.call)


def test_pending_work_excludes_what_already_landed(con):
    items = generate(count=4, seed=1, rubric_version="v1")
    sweep_id = _sweep(con, items, ["slot-a"], 5)
    units = pending_work(con, sweep_id, items, ["slot-a", "slot-b"], replicates=5)
    assert len(units) == 4 * 5, "slot-a is done; only slot-b remains"
    assert all(u.slot == "slot-b" for u in units)


def test_resuming_a_complete_sweep_is_empty(con):
    items = generate(count=2, seed=1, rubric_version="v1")
    sweep_id = _sweep(con, items, ["slot-a"], 3)
    assert pending_work(con, sweep_id, items, ["slot-a"], replicates=3) == []


def test_batches_respect_the_daily_ceiling():
    units = [WorkUnit("s", "slot-a", f"i{i}", 1) for i in range(250)]
    batches = plan_batches(units, {"prov": Quota(rpm=60, tpm=None, rpd=100)}, {"slot-a": "prov"})
    assert all(len(b) <= 100 for b in batches)  # noqa: PLR2004
    assert sum(len(b) for b in batches) == 250  # noqa: PLR2004


def test_an_unpublished_daily_limit_is_unbounded_not_zero():
    """Quota fields are int | None. None means the provider does not publish that limit."""
    units = [WorkUnit("s", "slot-a", f"i{i}", 1) for i in range(250)]
    batches = plan_batches(units, {"prov": Quota(rpm=60, tpm=None, rpd=None)}, {"slot-a": "prov"})
    assert len(batches) == 1 and len(batches[0]) == 250  # noqa: PLR2004


def test_batches_never_mix_providers():
    units = [WorkUnit("s", "slot-a", "i1", 1), WorkUnit("s", "slot-b", "i1", 1)]
    batches = plan_batches(
        units,
        {"p1": Quota(60, None, 1000), "p2": Quota(60, None, 1000)},
        {"slot-a": "p1", "slot-b": "p2"},
    )
    for batch in batches:
        assert len({u.slot for u in batch}) == 1


def test_unknown_provider_raises_rather_than_defaulting():
    with pytest.raises(KeyError):
        plan_batches([WorkUnit("s", "slot-z", "i1", 1)], {}, {})
