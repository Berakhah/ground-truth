import pytest

from ground_truth._bok_shim import CallContext, ProvidersUnavailable, Quota
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
    return execute_sweep(
        con,
        items,
        slots,
        replicates,
        context=CallContext(),
        resolve_fn=gw.resolve,
        call_fn=gw.call,
        allow_dirty=True,
    )


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


# -- audit H9: resuming a named sweep --------------------------------------------------
#
# `test_pending_work_excludes_what_already_landed` above feeds `execute_sweep`'s *returned*
# uuid back into `pending_work`, so it passes whether or not `--sweep-id` reaches the writer.
# It did not: `main()` planned against `args.sweep_id` and then dispatched a sweep that minted
# its own id, so every restart wrote under a new id, found nothing recorded under the id it was
# asked to resume, and re-spent the whole 9,000-call quota. These exercise that wiring.


def _resume(con, items, gw, *, sweep_id, **overrides):
    """One `main()`-equivalent dispatch: same items, same slots, same named sweep."""
    kwargs = {
        "context": CallContext(),
        "resolve_fn": gw.resolve,
        "call_fn": gw.call,
        "sweep_id": sweep_id,
        "allow_dirty": True,
        **overrides,
    }
    return execute_sweep(con, items, ["slot-a"], 5, **kwargs)


def test_resuming_does_not_duplicate_rows(con):
    items = generate(count=4, seed=1, rubric_version="v1")
    gw = FakeGateway()

    assert _resume(con, items, gw, sweep_id="sweep-v1") == "sweep-v1", (
        "execute_sweep must record under the sweep id it was given, not one of its own"
    )
    first = len(gw.seen)
    assert first == 4 * 5

    _resume(con, items, gw, sweep_id="sweep-v1")
    assert len(gw.seen) == first, "the second run re-spent quota on units already served"
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 4 * 5
    assert con.execute("SELECT count(*) FROM runs").fetchone()[0] == 1, (
        "one run_id per (sweep_id, slot); a second run row forks the sweep's provenance"
    )
    assert pending_work(con, "sweep-v1", items, ["slot-a"], replicates=5) == []


def test_an_interrupted_sweep_resumes_only_the_units_that_did_not_land(con):
    items = generate(count=4, seed=1, rubric_version="v1")
    dying = FakeGateway()
    served = dying.call

    def dies_after_seven(*args, **kwargs):
        if len(dying.seen) >= 7:  # noqa: PLR2004 -- an arbitrary mid-sweep interruption point
            raise ProvidersUnavailable("slot-a")
        return served(*args, **kwargs)

    with pytest.raises(ProvidersUnavailable):
        _resume(con, items, dying, sweep_id="sweep-v1", call_fn=dies_after_seven)
    landed = con.execute("SELECT count(*) FROM outputs").fetchone()[0]
    assert landed == 7  # noqa: PLR2004

    resumed = FakeGateway()
    _resume(con, items, resumed, sweep_id="sweep-v1")
    assert len(resumed.seen) == 4 * 5 - landed, "the resume paid again for calls already served"
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 4 * 5
    assert con.execute("SELECT count(*) FROM runs").fetchone()[0] == 1


def test_resuming_under_a_changed_models_yaml_refuses_rather_than_mixing(con, tmp_path):
    """A stable run_id is only honest while its provenance columns still describe the rows
    filed under it. Rows from two `models.yaml` versions in one run are not one measurement."""
    items = generate(count=1, seed=1, rubric_version="v1")
    gw = FakeGateway()
    _resume(con, items, gw, sweep_id="sweep-v1")

    moved = tmp_path / "models.yaml"
    moved.write_text("slots: []\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="new --sweep-id"):
        _resume(con, items, gw, sweep_id="sweep-v1", models_yaml=moved)


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
