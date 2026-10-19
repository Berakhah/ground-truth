import pytest

from ground_truth._bok_shim import CallContext, ProvidersUnavailable, Quota
from ground_truth.golden.build import _insert_items
from ground_truth.golden.generate import generate, render_document
from ground_truth.golden.schema import Split
from ground_truth.runner import build_prompt, execute_sweep, pending_work
from ground_truth.schedule import WorkUnit, _load_items, plan_batches
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


def test_a_daily_token_budget_binds_before_the_request_ceiling():
    """Groq: 1K RPD but 200K TPD. At 1,500 tokens a call only 133 calls fit in a day."""
    units = [WorkUnit("s", "slot-a", f"i{i}", 1) for i in range(300)]
    batches = plan_batches(
        units,
        {"prov": Quota(rpm=30, tpm=None, rpd=1000)},
        {"slot-a": "prov"},
        tokens_per_call={"slot-a": 1500},
        daily_token_budget={"prov": 200_000},
    )
    assert [len(b) for b in batches] == [133, 133, 34]


def test_slots_on_one_provider_share_its_daily_pool():
    """Two slots on one provider must not each be handed the full daily ceiling."""
    units = [WorkUnit("s", "slot-a", f"i{i}", 1) for i in range(80)] + [
        WorkUnit("s", "slot-b", f"i{i}", 1) for i in range(80)
    ]
    batches = plan_batches(
        units,
        {"prov": Quota(rpm=None, tpm=None, rpd=100)},
        {"slot-a": "prov", "slot-b": "prov"},
    )
    assert [len(b) for b in batches] == [80, 20, 60]
    assert all(len({u.slot for u in b}) == 1 for b in batches)


def test_a_token_budget_without_a_per_call_estimate_raises():
    units = [WorkUnit("s", "slot-a", "i1", 1)]
    with pytest.raises(KeyError):
        plan_batches(
            units,
            {"prov": Quota()},
            {"slot-a": "prov"},
            daily_token_budget={"prov": 200_000},
        )


def test_a_call_larger_than_the_whole_daily_budget_raises_instead_of_looping():
    units = [WorkUnit("s", "slot-a", "i1", 1)]
    with pytest.raises(ValueError, match="never fit"):
        plan_batches(
            units,
            {"prov": Quota()},
            {"slot-a": "prov"},
            tokens_per_call={"slot-a": 5000},
            daily_token_budget={"prov": 4000},
        )


# -- _load_items: the items a live sweep prompts with ---------------------------------------
#
# `_load_items` used to return `fields=[]`, so a live `build_prompt` asked for no keys, and an
# Item read back from the DB carries no `layout`, so it could not render a document either. The
# document the model sees is the corpus file `golden.build` wrote, read back verbatim.


def _built(con, tmp_path, count=3):
    items = generate(count=count, seed=1, rubric_version="v1")
    _insert_items(con, items, "2026-10-19")
    for split in Split:
        (tmp_path / split.value).mkdir(exist_ok=True)
    for item in items:
        path = tmp_path / item.split.value / f"{item.item_id}.txt"
        path.write_text(render_document(item), encoding="utf-8")
    return items


def test_loaded_items_carry_their_labelled_fields_in_build_order(con, tmp_path):
    items = _built(con, tmp_path)
    loaded = {i.item_id: i for i in _load_items(con, tmp_path)}
    assert set(loaded) == {i.item_id for i in items}
    for original in items:
        assert loaded[original.item_id].fields == original.fields


def test_a_loaded_item_prompts_exactly_as_the_built_item_does(con, tmp_path):
    items = _built(con, tmp_path)
    loaded = {i.item_id: i for i in _load_items(con, tmp_path)}
    for original in items:
        assert build_prompt(loaded[original.item_id]) == build_prompt(original)


def test_a_missing_corpus_file_raises_rather_than_prompting_without_a_document(con, tmp_path):
    items = _built(con, tmp_path)
    (tmp_path / items[0].split.value / f"{items[0].item_id}.txt").unlink()
    with pytest.raises(FileNotFoundError):
        _load_items(con, tmp_path)


def test_unknown_provider_raises_rather_than_defaulting():
    with pytest.raises(KeyError):
        plan_batches([WorkUnit("s", "slot-z", "i1", 1)], {}, {})
