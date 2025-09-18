# Ground Truth — Phase 2: Sweep, Judge, and Statistics (Weeks 23–24) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run the full 9,000-call sweep, add the judge with its bias controls and pre-registered rejection threshold, and produce the leaderboard data, the cost/latency matrix, and the calibration curves Ledger Sense consumes.

**Architecture:** Unchanged from Phase 1 — phase 1 executes and stores, phase 2 analyses. The judge's n≥3 samples are *executions* (stored in `judge_samples`); majority vote, order-effect testing and length-effect reporting are pure phase-2 functions, which is why every bias control here is testable with no network.

**Tech Stack:** Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `hypothesis`, `duckdb`, `scipy`, `numpy`, `scikit-learn`, `pydantic` v2.

**Spec:** `docs/superpowers/specs/2025-09-18-ground-truth-design.md`

**Prerequisite:** Phase 1 exit criteria all met. `git tag phase-1-triage` exists.

**Phase deliverable:** leaderboard-ready numbers with intervals, a published judge-agreement table including where the judge was rejected, and a calibration export file.

## Global Constraints

Every task's requirements implicitly include this section. Identical to Phase 1's, restated because plan files are read independently.

- **Python 3.12+**, `uv`, `ruff`, `mypy --strict` on all of `ground_truth/`.
- **No model name is ever hardcoded** (`00` R1). Slots resolve through `models.yaml`.
- **No secrets in the repo, including fixtures.** `gitleaks` pre-commit.
- **No `[project.scripts]` entry.** Entrypoints are `python -m ground_truth.<module>`.
- **Money uses `Decimal`. Never `float`.** The CI grep gate covers `ground_truth/graders/`, `ground_truth/triage/`, and — added this phase — `ground_truth/matrix/`.
- **`golden/corpus/private/` stays gitignored.** The private seed stays in `.env`.
- **Response cache stays DISABLED for benchmark execution.**
- **The analysis plan is frozen.** Any change to a threshold, a test, or the look calendar is a new plan version with a changelog entry — never an edit in place.
- **Licence Apache-2.0.** Coverage floor 75%.
- **Every task's verification implicitly ends with the non-goal check:** *Did this task add an abstraction whose second implementation does not exist? If yes, STOP and report — that is the platform trap arriving.*

---

### Task 23: Sweep scheduling — batched, quota-aware, resumable

9,000 calls will not complete in one run. This task makes an interrupted sweep resumable without re-spending quota.

**Files:**
- Create: `ground_truth/schedule.py`
- Modify: `ground_truth/runner.py` — add `pending_work`
- Test: `tests/test_schedule.py`

**Interfaces:**
- Consumes: `runner.execute_sweep`, `store.db`, `providers.load_slots`, `golden.schema.Item`.
- Produces: `WorkUnit(sweep_id: str, slot: str, item_id: str, replicate_idx: int)` (frozen); `plan_batches(units: list[WorkUnit], quotas: dict[str, Quota], slot_providers: dict[str, str]) -> list[list[WorkUnit]]`; and in `runner.py`, `pending_work(con, sweep_id: str, items: list[Item], slots: list[str], replicates: int) -> list[WorkUnit]`.

> **Contract alignment (amended 2025-09-18).** Quotas come from
> `bok_core.gateway.governor.Quota(rpm, tpm, rpd)`, queried live via `governor.remaining(provider)`,
> which `INTERFACE-CONTRACT.md` §3.3 exposes as a **public query** specifically so this scheduler can
> ask before dispatching each batch. Do not define a local budget type — a second quota model that
> drifts from the governor's is how a sweep plans against limits that no longer exist. `Quota` fields
> are `int | None`; `None` means the provider does not publish that limit, and the planner must treat
> it as **unbounded, never zero**.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_schedule.py
import pytest

from ground_truth.golden.generate import generate
from ground_truth.runner import execute_sweep, pending_work
from ground_truth._bok_shim import CallContext, Quota
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
    assert all(len(b) <= 100 for b in batches)
    assert sum(len(b) for b in batches) == 250


def test_an_unpublished_daily_limit_is_unbounded_not_zero():
    """Quota fields are int | None. None means the provider does not publish that limit."""
    units = [WorkUnit("s", "slot-a", f"i{i}", 1) for i in range(250)]
    batches = plan_batches(units, {"prov": Quota(rpm=60, tpm=None, rpd=None)}, {"slot-a": "prov"})
    assert len(batches) == 1 and len(batches[0]) == 250


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
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_schedule.py -v`
Expected: FAIL — `ImportError: cannot import name 'pending_work' from 'ground_truth.runner'`.

- [ ] **Step 3: Add `pending_work` to `ground_truth/runner.py`**

```python
def pending_work(
    con: duckdb.DuckDBPyConnection,
    sweep_id: str,
    items: list[Item],
    slots: list[str],
    replicates: int,
) -> list["WorkUnit"]:
    from ground_truth.schedule import WorkUnit

    done = {
        (r[0], r[1], r[2])
        for r in con.execute(
            "SELECT r.model_slot, o.item_id, o.replicate_idx FROM outputs o "
            "JOIN runs r ON r.run_id = o.run_id WHERE r.sweep_id = ?",
            [sweep_id],
        ).fetchall()
    }
    return [
        WorkUnit(sweep_id, slot, item.item_id, replicate)
        for slot in slots
        for item in items
        for replicate in range(1, replicates + 1)
        if (slot, item.item_id, replicate) not in done
    ]
```

The import is function-local to avoid a circular import between `runner` and `schedule`.

- [ ] **Step 4: Write `ground_truth/schedule.py`**

`WorkUnit` is a frozen dataclass; `Quota` comes from the gateway, not from here. `plan_batches` groups units by slot, looks each slot's provider up in `slot_providers` — raising `KeyError` on an unknown slot rather than defaulting silently — and chunks each group into lists no longer than that provider's `rpd`, treating `rpd is None` as unbounded. Batches from different providers stay separate list entries so an overnight run can interleave them.

The module exposes `if __name__ == "__main__":` accepting `--sweep-id` and `--dry-run`. It calls `governor.remaining(provider)` for each configured provider at plan time rather than reading a static table, prints the batch plan and total call count, and **prints the quota it planned against alongside its retrieval time** — so a plan built against yesterday's limits is visible as such rather than silently wrong.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_schedule.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 6: Run the real sweep**

```bash
uv run python -m ground_truth.schedule --sweep-id sweep-v1 --dry-run
uv run python -m ground_truth.schedule --sweep-id sweep-v1
```

Expect this to span several nights. If interrupted, re-run the identical command — `pending_work` resumes without re-spending quota. Record the actual wall-clock and any 429s in `docs/methodology.md` under the run schedule.

- [ ] **Step 7: Commit**

```bash
git add ground_truth/schedule.py ground_truth/runner.py tests/test_schedule.py
git commit -m "feat: resumable quota-aware sweep scheduling"
```

---

### Task 24: Judge execution — constrained output and recorded presentation order

**Files:**
- Create: `ground_truth/graders/judge/__init__.py`
- Create: `ground_truth/graders/judge/prompt.py`
- Test: `tests/graders/judge/test_prompt.py`

**Interfaces:**
- Consumes: `_bok_shim.{Handle, Labelled, Sensitivity, CallContext, CacheMode, FailoverMode}`, `providers.load_slots`, `store.db`, `golden.schema.ItemField`.
- Produces: `SameFamilyJudge(RuntimeError)`; `Presentation(order: int, first: str, second: str)` (frozen); `randomise_presentation(expected: str, observed: str, *, seed: int) -> Presentation`; `build_judgement_prompt(field: ItemField, presentation: Presentation) -> str`; `assert_judge_family_differs(judge_slot: str, model_slot: str, models_yaml: Path) -> None`; `sample_judgements(con, output_id: str, field: ItemField, observed: str, judge_slot: str, model_slot: str, *, n: int, seed: int, resolve_fn, call_fn, context: CallContext) -> int`.

> **Contract alignment.** Judge calls carry the same two flags as the sweep —
> `cache=DISABLED` because the n≥3 samples are replicates, and `failover=DISABLED` because a
> failover to a different family would defeat the same-family check this task exists to enforce.
> A fallback handle is refused outright: a deterministic fallback cannot judge free text, and
> recording its output would publish a non-verdict as a measurement.

- [ ] **Step 1: Write the failing test**

```python
# tests/graders/judge/test_prompt.py
from pathlib import Path

import pytest

from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.judge.prompt import (
    SameFamilyJudge,
    assert_judge_family_differs,
    build_judgement_prompt,
    randomise_presentation,
)

MODELS_YAML = Path(__file__).resolve().parents[3] / "models.yaml"


def field() -> ItemField:
    return ItemField(field_name="line_1_description", field_type=FieldType.LINE_ITEM_DESCRIPTION,
                     expected_value="Concrete works, phase 1")


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
```

`test_prompt_does_not_label_which_text_is_the_reference` is the control that makes order randomisation meaningful. Randomising position while writing "the expected value is:" above one of them controls nothing.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/graders/judge/test_prompt.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.graders.judge.prompt'`.

- [ ] **Step 3: Configure the judge slots in `models.yaml`**

Under `judge_slots`, add `judge-a` whose `family` differs from `slot-a`'s, and `judge-same-family` whose `family` equals `slot-a`'s — the second exists solely so the rejection test has a real target.

If the provider audit did not yield two distinct families, **stop and report**. A single-family judge configuration cannot satisfy `04` B2, and the judge work is blocked until a second family is reachable. The fallback, if no second family exists, is to publish `LINE_ITEM_DESCRIPTION` as *not measured* and say why — that is an acceptable outcome, but it is a decision to surface, not to make silently.

- [ ] **Step 4: Write `ground_truth/graders/judge/prompt.py`**

```python
from __future__ import annotations

import random
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import duckdb

from ground_truth._bok_shim import (
    CacheMode,
    CallContext,
    FailoverMode,
    Handle,
    Labelled,
    Response,
    Sensitivity,
)
from ground_truth.golden.schema import ItemField
from ground_truth.providers import load_slots


class SameFamilyJudge(RuntimeError):
    def __init__(self, judge_slot: str, model_slot: str, family: str) -> None:
        super().__init__(
            f"judge {judge_slot!r} and model under test {model_slot!r} share family {family!r}; "
            "self-preference bias makes this judgement indefensible"
        )


@dataclass(frozen=True)
class Presentation:
    order: int
    first: str
    second: str


def randomise_presentation(expected: str, observed: str, *, seed: int) -> Presentation:
    order = random.Random(seed).randint(0, 1)
    return (
        Presentation(0, expected, observed) if order == 0 else Presentation(1, observed, expected)
    )


def build_judgement_prompt(field: ItemField, presentation: Presentation) -> str:
    return (
        "Two descriptions of the same line item on a progress billing document are given "
        "below. Decide whether they convey the same work.\n\n"
        f"Text A:\n{presentation.first}\n\nText B:\n{presentation.second}\n\n"
        "Reply with exactly one token and nothing else: EQUIVALENT or NOT_EQUIVALENT."
    )


def assert_judge_family_differs(judge_slot: str, model_slot: str, models_yaml: Path) -> None:
    judges = load_slots(models_yaml, key="judge_slots")
    models = load_slots(models_yaml, key="slots")
    family = judges[judge_slot].family
    if family == models[model_slot].family:
        raise SameFamilyJudge(judge_slot, model_slot, family)


def sample_judgements(
    con: duckdb.DuckDBPyConnection,
    output_id: str,
    field: ItemField,
    observed: str,
    judge_slot: str,
    model_slot: str,
    *,
    n: int,
    seed: int,
    resolve_fn: Callable[[str], Handle],
    call_fn: Callable[..., Response],
    context: CallContext,
    models_yaml: Path = Path("models.yaml"),
) -> int:
    assert_judge_family_differs(judge_slot, model_slot, models_yaml)
    handle = resolve_fn(judge_slot)
    if handle.is_fallback:
        raise ValueError(
            f"judge slot {judge_slot!r} resolved to a deterministic fallback handle. "
            "A fallback cannot judge; report the field type as not measured instead."
        )
    for i in range(n):
        presentation = randomise_presentation(
            field.expected_value, observed, seed=hash((output_id, field.field_name, i)) & 0xFFFF
        )
        payload = Labelled(
            value=build_judgement_prompt(field, presentation),
            sensitivity=Sensitivity.SYNTHETIC,
        )
        # Same two flags as the sweep: the judge's n>=3 samples are replicates, and a
        # failover would attribute one judge family's verdict to another -- which is
        # exactly the self-preference bias the family check exists to prevent.
        result = call_fn(
            handle, payload, context,
            cache=CacheMode.DISABLED, failover=FailoverMode.DISABLED,
        )
        con.execute(
            "INSERT INTO judge_samples VALUES (?,?,?,?,?,?,?,?)",
            [uuid.uuid4().hex, output_id, field.field_name, judge_slot,
             presentation.order, result.text, result.ledger_call_id, datetime.now(UTC)],
        )
    return n
```

Neither text is labelled. The prompt cannot leak which is the reference because it does not know. `sample_judgements` writes no verdict — aggregation is Task 25, in phase 2, with no network.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/graders/judge/test_prompt.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/graders/judge/ models.yaml tests/graders/judge/
git commit -m "feat: judge execution with unlabelled randomised presentation and family rejection"
```

---

### Task 25: Judge aggregation and bias measurement — pure phase 2

**Files:**
- Create: `ground_truth/graders/judge/aggregate.py`
- Test: `tests/graders/judge/test_aggregate.py`

**Interfaces:**
- Consumes: nothing outside the standard library.
- Produces: `JudgeVerdict` (`StrEnum`: `EQUIVALENT`, `NOT_EQUIVALENT`, `INCONCLUSIVE`); `Sample(presentation_order: int, raw: str, observed_length: int)` (frozen); `parse_judgement(raw: str) -> JudgeVerdict`; `majority_vote(samples: list[Sample]) -> JudgeVerdict`; `OrderEffect(order_0_rate: float, order_1_rate: float, difference: float, n: int)` (frozen); `order_effect(samples: list[Sample]) -> OrderEffect`; `LengthEffect(quintile_rates: list[float], n: int)` (frozen); `length_effect(samples: list[Sample]) -> LengthEffect`.

- [ ] **Step 1: Write the failing test**

```python
# tests/graders/judge/test_aggregate.py
import pytest

from ground_truth.graders.judge.aggregate import (
    JudgeVerdict,
    Sample,
    length_effect,
    majority_vote,
    order_effect,
    parse_judgement,
)


def s(order: int, raw: str, length: int = 20) -> Sample:
    return Sample(presentation_order=order, raw=raw, observed_length=length)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("EQUIVALENT", JudgeVerdict.EQUIVALENT),
        ("  equivalent \n", JudgeVerdict.EQUIVALENT),
        ("NOT_EQUIVALENT", JudgeVerdict.NOT_EQUIVALENT),
        ("not_equivalent", JudgeVerdict.NOT_EQUIVALENT),
        ("The answer is EQUIVALENT.", JudgeVerdict.EQUIVALENT),
        ("maybe?", JudgeVerdict.INCONCLUSIVE),
        ("", JudgeVerdict.INCONCLUSIVE),
    ],
)
def test_parse_judgement(raw, expected):
    assert parse_judgement(raw) == expected


def test_majority_of_three_wins():
    assert majority_vote(
        [s(0, "EQUIVALENT"), s(1, "EQUIVALENT"), s(0, "NOT_EQUIVALENT")]
    ) is JudgeVerdict.EQUIVALENT


def test_tie_yields_inconclusive():
    samples = [s(0, "EQUIVALENT"), s(1, "NOT_EQUIVALENT"), s(0, "?")]
    assert majority_vote(samples) is JudgeVerdict.INCONCLUSIVE, "never resolve a tie by coin flip"


def test_all_inconclusive_yields_inconclusive():
    assert majority_vote([s(0, "?"), s(1, "?"), s(0, "?")]) is JudgeVerdict.INCONCLUSIVE


def test_fewer_than_three_samples_raises():
    with pytest.raises(ValueError, match="at least 3"):
        majority_vote([s(0, "EQUIVALENT"), s(1, "EQUIVALENT")])


def test_order_effect_is_zero_when_orders_agree():
    samples = [s(0, "EQUIVALENT"), s(1, "EQUIVALENT"), s(0, "EQUIVALENT"), s(1, "EQUIVALENT")]
    assert order_effect(samples).difference == 0.0


def test_order_effect_detects_position_bias():
    effect = order_effect([s(0, "EQUIVALENT")] * 10 + [s(1, "NOT_EQUIVALENT")] * 10)
    assert effect.difference == pytest.approx(1.0)
    assert effect.n == 20


def test_order_effect_requires_both_orders():
    with pytest.raises(ValueError, match="both presentation orders"):
        order_effect([s(0, "EQUIVALENT")] * 5)


def test_length_effect_returns_five_quintiles():
    effect = length_effect([s(i % 2, "EQUIVALENT", length=i) for i in range(50)])
    assert len(effect.quintile_rates) == 5 and effect.n == 50


def test_length_effect_detects_verbosity_bias():
    short = [s(0, "NOT_EQUIVALENT", length=i) for i in range(25)]
    long_ = [s(1, "EQUIVALENT", length=100 + i) for i in range(25)]
    rates = length_effect(short + long_).quintile_rates
    assert rates[0] < rates[-1], "longer outputs judged equivalent more often"


def test_length_effect_needs_at_least_five_samples():
    with pytest.raises(ValueError):
        length_effect([s(0, "EQUIVALENT")] * 3)


def test_module_performs_no_io():
    import inspect

    from ground_truth.graders.judge import aggregate

    source = inspect.getsource(aggregate)
    for banned in ("httpx", "requests", "open(", "duckdb"):
        assert banned not in source, "judge aggregation must be a pure phase-2 function"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/graders/judge/test_aggregate.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/graders/judge/aggregate.py`**

`parse_judgement` upper-cases and strips, then checks `"NOT_EQUIVALENT" in text` **before** `"EQUIVALENT" in text` — order matters, because the second is a substring of the first — returning `INCONCLUSIVE` otherwise.

`majority_vote` raises `ValueError("at least 3 samples required")` below three. It counts `EQUIVALENT` and `NOT_EQUIVALENT`, ignoring `INCONCLUSIVE` in the comparison, and returns the strict winner. Equal counts, or no non-inconclusive samples at all, return `INCONCLUSIVE`. There is no tiebreak — a coin flip would manufacture a verdict the evidence does not support.

`order_effect` raises `ValueError("both presentation orders must be present")` when either order is absent, then returns the `EQUIVALENT` rate under each order and their absolute difference.

`length_effect` raises `ValueError` below five samples, sorts by `observed_length`, splits into five near-equal quintiles, and returns the `EQUIVALENT` rate within each. Verbosity cannot be stripped, so it is measured and published.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/graders/judge/test_aggregate.py -v`
Expected: PASS, 19 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/graders/judge/aggregate.py tests/graders/judge/test_aggregate.py
git commit -m "feat: judge majority vote with inconclusive ties, order and length effect measures"
```

---

### Task 26: `stats/agreement.py` — Cohen's κ and Krippendorff's α

**Files:**
- Create: `ground_truth/stats/agreement.py`
- Test: `tests/stats/test_agreement.py`

**Interfaces:**
- Consumes: `numpy`.
- Produces: `cohens_kappa(rater_a: list[str], rater_b: list[str]) -> float`; `krippendorff_alpha(ratings: dict[str, dict[str, str]]) -> float` (outer key rater, inner maps unit id to value, missing units simply absent); `confusion_matrix(rater_a: list[str], rater_b: list[str]) -> dict[tuple[str, str], int]`.

- [ ] **Step 1: Check the licence before choosing an implementation**

Inspect the `krippendorff` PyPI package's licence. If MIT / Apache-2.0 / BSD, add it and wrap it. If it is anything else — GPL, AGPL, or unstated — **implement nominal α directly**, per `00` §3. Record the decision and the licence text you saw in `docs/methodology.md`. The test below is identical either way, which is the point.

- [ ] **Step 2: Write the failing test**

```python
# tests/stats/test_agreement.py
import pytest

from ground_truth.stats.agreement import cohens_kappa, confusion_matrix, krippendorff_alpha


def test_perfect_agreement_is_one():
    assert cohens_kappa(["a", "b", "a"], ["a", "b", "a"]) == pytest.approx(1.0)


def test_cohens_kappa_zero_on_independent_raters():
    a = ["x"] * 50 + ["y"] * 50
    b = (["x"] * 25 + ["y"] * 25) * 2
    assert cohens_kappa(a, b) == pytest.approx(0.0, abs=0.02)


def test_cohens_kappa_matches_worked_example():
    # 2x2 table: both-yes 20, a-yes/b-no 5, a-no/b-yes 10, both-no 15
    # Po = 0.70, Pe = 0.50  ->  kappa = 0.40
    a = ["yes"] * 25 + ["no"] * 25
    b = ["yes"] * 20 + ["no"] * 5 + ["yes"] * 10 + ["no"] * 15
    assert cohens_kappa(a, b) == pytest.approx(0.40, abs=1e-9)


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        cohens_kappa(["a"], ["a", "b"])


def test_krippendorff_alpha_matches_published_worked_example():
    # Krippendorff's canonical nominal example: alpha = 0.743
    ratings = {
        "obs_a": {"1": "1", "2": "2", "3": "3", "4": "3", "5": "2", "6": "1", "7": "4",
                  "8": "1", "9": "2", "10": "1", "11": "1", "12": "3", "13": "3", "14": "4",
                  "15": "3"},
        "obs_b": {"1": "1", "2": "2", "3": "3", "4": "3", "5": "2", "6": "2", "7": "4",
                  "8": "1", "9": "2", "10": "1", "11": "1", "12": "3", "13": "3", "14": "4",
                  "15": "4"},
    }
    assert krippendorff_alpha(ratings) == pytest.approx(0.743, abs=0.005)


def test_alpha_handles_a_partial_second_rater():
    ratings = {
        "primary": {str(i): ("a" if i % 2 else "b") for i in range(100)},
        "partial": {str(i): ("a" if i % 2 else "b") for i in range(20)},
    }
    assert krippendorff_alpha(ratings) == pytest.approx(1.0, abs=1e-6)


def test_alpha_of_total_disagreement_is_negative():
    assert krippendorff_alpha({"a": {"1": "x", "2": "y"}, "b": {"1": "y", "2": "x"}}) < 0


def test_alpha_with_no_overlapping_units_raises():
    with pytest.raises(ValueError):
        krippendorff_alpha({"a": {"1": "x"}, "b": {"2": "y"}})


def test_confusion_matrix_counts_every_pair():
    m = confusion_matrix(["a", "a", "b"], ["a", "b", "b"])
    assert m[("a", "a")] == 1 and m[("a", "b")] == 1 and m[("b", "b")] == 1
```

`test_alpha_handles_a_partial_second_rater` is why α is required rather than optional — a second labeller on 20% of the set is exactly the data shape `04` B1 prescribes, and κ cannot consume it.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/stats/test_agreement.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 4: Write `ground_truth/stats/agreement.py`**

`cohens_kappa` raises `ValueError` on mismatched lengths, computes observed agreement `po` and chance agreement `pe` from the marginals, and returns `(po - pe) / (1 - pe)`, returning `1.0` when `pe == 1.0`.

`krippendorff_alpha` for nominal data: build the coincidence matrix over units rated by two or more raters (raising `ValueError` when no unit has two), compute observed disagreement `Do` and expected disagreement `De` from the value marginals, return `1 - Do / De`. Units rated by a single rater contribute nothing, which is exactly what makes a partial second rater usable.

`confusion_matrix` returns a plain `dict[tuple[str, str], int]` — the judge-agreement screen renders it directly.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/stats/test_agreement.py -v`
Expected: PASS, 9 passed.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/stats/agreement.py tests/stats/test_agreement.py
git commit -m "feat: Cohen's kappa and Krippendorff's alpha against published worked examples"
```

---

### Task 27: Judge-versus-human agreement and the pre-registered rejection

**Files:**
- Create: `ground_truth/graders/judge/agreement.py`
- Test: `tests/graders/judge/test_agreement.py`

**Interfaces:**
- Consumes: `stats.agreement.{krippendorff_alpha, confusion_matrix}`, `stats.bootstrap.{Interval, cluster_bootstrap_ci}`, `graders.judge.aggregate.{OrderEffect, LengthEffect, Sample, order_effect, length_effect}`.
- Produces: `REJECTION_THRESHOLD: float = 0.667`; `JudgeStatus` (`StrEnum`: `ACCEPTED`, `REJECTED`); `AgreementReport(field_type: str, alpha: float, alpha_ci: Interval, status: JudgeStatus, n_units: int, confusion: dict[tuple[str, str], int], order: OrderEffect, length: LengthEffect, statement: str)` (frozen); `assess(field_type: str, judge_verdicts: dict[str, str], human_verdicts: dict[str, str], samples: list[Sample], *, seed: int) -> AgreementReport`.

- [ ] **Step 1: Write the failing test**

```python
# tests/graders/judge/test_agreement.py
from pathlib import Path

import pytest

from ground_truth.graders.judge.agreement import REJECTION_THRESHOLD, JudgeStatus, assess
from ground_truth.graders.judge.aggregate import Sample

PLAN = Path(__file__).resolve().parents[3] / "docs" / "analysis-plan.md"


def samples(n: int = 20) -> list[Sample]:
    return [Sample(presentation_order=i % 2, raw="EQUIVALENT", observed_length=10 + i)
            for i in range(n)]


def agreeing(n: int):
    j = {str(i): ("EQUIVALENT" if i % 3 else "NOT_EQUIVALENT") for i in range(n)}
    return j, dict(j)


def disagreeing(n: int):
    j = {str(i): "EQUIVALENT" for i in range(n)}
    h = {str(i): ("EQUIVALENT" if i % 2 else "NOT_EQUIVALENT") for i in range(n)}
    return j, h


def test_threshold_matches_the_pre_registered_plan():
    assert str(REJECTION_THRESHOLD) in PLAN.read_text(encoding="utf-8"), (
        "the threshold in code must be the one frozen in docs/analysis-plan.md"
    )


def test_high_agreement_is_accepted():
    j, h = agreeing(60)
    report = assess("line_item_description", j, h, samples(), seed=1)
    assert report.status is JudgeStatus.ACCEPTED and report.alpha > REJECTION_THRESHOLD


def test_low_agreement_is_rejected():
    j, h = disagreeing(60)
    assert assess("line_item_description", j, h, samples(), seed=1).status is JudgeStatus.REJECTED


def test_rejected_report_states_the_consequence():
    j, h = disagreeing(60)
    statement = assess("line_item_description", j, h, samples(), seed=1).statement
    assert "not used for headline scoring" in statement
    assert str(REJECTION_THRESHOLD) in statement


def test_accepted_report_still_publishes_its_alpha_and_interval():
    j, h = agreeing(60)
    report = assess("line_item_description", j, h, samples(), seed=1)
    assert f"n={report.n_units}" in report.statement
    assert report.alpha_ci.low <= report.alpha_ci.high


def test_confusion_matrix_is_included():
    j, h = agreeing(60)
    assert assess("line_item_description", j, h, samples(), seed=1).confusion


def test_bias_measures_are_included():
    j, h = agreeing(60)
    report = assess("line_item_description", j, h, samples(), seed=1)
    assert report.order.n > 0 and len(report.length.quintile_rates) == 5


def test_no_overlapping_units_raises_rather_than_reporting_perfect_agreement():
    with pytest.raises(ValueError, match="no overlapping"):
        assess("line_item_description", {"1": "EQUIVALENT"}, {"2": "EQUIVALENT"}, samples(), seed=1)
```

`test_threshold_matches_the_pre_registered_plan` is the anti-p-hacking guard: the constant in code is chained to the frozen document, so nudging the threshold after seeing the numbers breaks a test.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/graders/judge/test_agreement.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/graders/judge/agreement.py`**

`assess` intersects the judge and human unit ids, raising `ValueError("no overlapping units")` when the intersection is empty. It computes α across the two raters over the overlap, bootstraps a CI on per-unit agreement through `cluster_bootstrap_ci`, builds the confusion matrix, computes `order_effect` and `length_effect` from `samples`, and sets `status` by comparing α to `REJECTION_THRESHOLD`.

The `statement` is the published sentence, and it always carries the decision alongside the number:

- Accepted: `f"Judge-human agreement on {field_type}: Krippendorff's alpha = {alpha:.3f} [{low:.3f}, {high:.3f}], n={n_units}. Above the pre-registered threshold of {REJECTION_THRESHOLD}; used for headline scoring."`
- Rejected: `f"Judge-human agreement on {field_type}: Krippendorff's alpha = {alpha:.3f} [{low:.3f}, {high:.3f}], n={n_units}. Below the pre-registered threshold of {REJECTION_THRESHOLD}; this field type is not used for headline scoring and is reported as not measured."`

Both statements publish. That is spec §8.2 — the weakness always ships next to the decision it caused.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/graders/judge/test_agreement.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 5: Collect human labels, round 1**

Label the `LINE_ITEM_DESCRIPTION` field for a random sample of at least 60 outputs, **blind to the judge's verdicts**, writing into `human_labels` with `round=1` and your own `labeller_id`.

**Record the date in `docs/methodology.md`.** Phase 3 Task 39 requires a minimum two-week gap before round 2, and that clock starts today. This is not compressible — a blind re-label after three days measures short-term memory, not intra-rater reliability.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/graders/judge/agreement.py tests/graders/judge/test_agreement.py docs/methodology.md
git commit -m "feat: judge-human agreement with pre-registered rejection chained to the frozen plan"
```

---

### Task 28: `stats/correction.py` — Benjamini–Hochberg

**Files:**
- Create: `ground_truth/stats/correction.py`
- Test: `tests/stats/test_correction.py`

**Interfaces:**
- Consumes: `scipy.stats.false_discovery_control`, `numpy`.
- Produces: `Comparison(label: str, p_value: float)` (frozen); `CorrectedComparison(label: str, p_value: float, adjusted_p: float, significant: bool)` (frozen); `benjamini_hochberg(comparisons: list[Comparison], *, fdr: float = 0.05) -> list[CorrectedComparison]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/stats/test_correction.py
import random

import pytest

from ground_truth.stats.correction import Comparison, benjamini_hochberg


def test_bh_matches_worked_example():
    # Benjamini & Hochberg 1995, Table 1 (15 hypotheses); FDR 0.05 -> 4 rejections
    p_values = [0.0001, 0.0004, 0.0019, 0.0095, 0.0201, 0.0278, 0.0298, 0.0344,
                0.0459, 0.3240, 0.4262, 0.5719, 0.6528, 0.7590, 1.0000]
    result = benjamini_hochberg([Comparison(f"h{i}", p) for i, p in enumerate(p_values)], fdr=0.05)
    assert sum(c.significant for c in result) == 4


def test_labels_survive_correction():
    comps = [Comparison("slot-a/MONEY", 0.001), Comparison("slot-b/DATE", 0.9)]
    assert {c.label for c in benjamini_hochberg(comps)} == {"slot-a/MONEY", "slot-b/DATE"}


def test_input_order_is_preserved():
    comps = [Comparison("z", 0.9), Comparison("a", 0.001)]
    assert [c.label for c in benjamini_hochberg(comps)] == ["z", "a"]


def test_adjusted_p_is_never_below_raw_p():
    comps = [Comparison(f"h{i}", i / 20) for i in range(1, 20)]
    assert all(c.adjusted_p >= c.p_value - 1e-12 for c in benjamini_hochberg(comps))


def test_single_comparison_is_unchanged():
    result = benjamini_hochberg([Comparison("only", 0.03)])
    assert result[0].adjusted_p == pytest.approx(0.03) and result[0].significant


def test_empty_input_returns_empty():
    assert benjamini_hochberg([]) == []


def test_invalid_p_value_raises_and_names_the_comparison():
    with pytest.raises(ValueError, match="bad"):
        benjamini_hochberg([Comparison("bad", 1.5)])


@pytest.mark.slow
def test_bh_controls_fdr_under_null():
    rng = random.Random(0)
    false_discoveries, trials, per_trial = 0, 1000, 48
    for _ in range(trials):
        comps = [Comparison(f"h{i}", rng.random()) for i in range(per_trial)]
        false_discoveries += sum(c.significant for c in benjamini_hochberg(comps, fdr=0.05))
    rate = false_discoveries / (trials * per_trial)
    assert rate <= 0.05, f"empirical false-discovery rate {rate:.4f} exceeds the nominal 0.05"
```

- [ ] **Step 2: Run the fast tests to verify they fail**

Run: `uv run pytest tests/stats/test_correction.py -v -m "not slow"`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/stats/correction.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.stats import false_discovery_control


@dataclass(frozen=True)
class Comparison:
    label: str
    p_value: float


@dataclass(frozen=True)
class CorrectedComparison:
    label: str
    p_value: float
    adjusted_p: float
    significant: bool


def benjamini_hochberg(
    comparisons: list[Comparison], *, fdr: float = 0.05
) -> list[CorrectedComparison]:
    if not comparisons:
        return []
    for c in comparisons:
        if not 0.0 <= c.p_value <= 1.0:
            raise ValueError(f"p-value out of range for {c.label!r}: {c.p_value}")
    adjusted = false_discovery_control(
        np.array([c.p_value for c in comparisons], dtype=float), method="bh"
    )
    return [
        CorrectedComparison(
            label=c.label, p_value=c.p_value, adjusted_p=float(adj), significant=bool(adj <= fdr)
        )
        for c, adj in zip(comparisons, adjusted, strict=True)
    ]
```

Input order is preserved so callers can zip results back against their own comparison list without re-sorting, and the label travels with the number so every alert can name its comparison family.

- [ ] **Step 4: Run the fast tests**

Run: `uv run pytest tests/stats/test_correction.py -v -m "not slow"`
Expected: PASS, 7 passed, 1 deselected.

- [ ] **Step 5: Run the null simulation**

Run: `uv run pytest tests/stats/test_correction.py::test_bh_controls_fdr_under_null -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/stats/correction.py tests/stats/test_correction.py
git commit -m "feat: labelled Benjamini-Hochberg correction validated against the 1995 example"
```

---

### Task 29: `matrix/cost.py` — list price, caveated at the source

**Files:**
- Create: `ground_truth/matrix/__init__.py`
- Create: `ground_truth/matrix/cost.py`
- Modify: `.github/workflows/ci.yml` — extend the money grep to `ground_truth/matrix/`
- Test: `tests/matrix/test_cost.py`

**Interfaces:**
- Consumes: `providers.SlotSpec`.
- Produces: `LIST_PRICE_CAVEAT: str`; `CostClaim(value: Decimal, unit: str, method: str, source_url: str, retrieved_at: date, caveat: str)` (frozen); `cost_per_1k_items(spec: SlotSpec, mean_tokens_in: int, mean_tokens_out: int) -> CostClaim`.

- [ ] **Step 1: Write the failing test**

```python
# tests/matrix/test_cost.py
from datetime import date
from decimal import Decimal

import pytest

from ground_truth.matrix.cost import LIST_PRICE_CAVEAT, cost_per_1k_items
from ground_truth.providers import SlotSpec


def spec(**over) -> SlotSpec:
    base = dict(slot="slot-a", family="fam", provider="prov", model_ref="ref",
                trains_on_data=False, commercial_use=True, exposes_fingerprint=False,
                list_price_in_per_1m=Decimal("0.10"), list_price_out_per_1m=Decimal("0.40"),
                pricing_url="https://example.invalid/pricing", retrieved_at=date(2026, 8, 31))
    return SlotSpec(**(base | over))


def test_cost_is_computed_from_list_price():
    # 1000 items x (2000 in + 500 out) = 2,000,000 in + 500,000 out
    # = 2 * 0.10 + 0.5 * 0.40 = 0.40
    assert cost_per_1k_items(spec(), 2000, 500).value == Decimal("0.4000")


def test_value_is_decimal_not_float():
    assert isinstance(cost_per_1k_items(spec(), 2000, 500).value, Decimal)


def test_caveat_is_always_attached():
    assert cost_per_1k_items(spec(), 2000, 500).caveat == LIST_PRICE_CAVEAT


def test_caveat_names_list_price_and_denies_measured_spend():
    lowered = LIST_PRICE_CAVEAT.lower()
    assert "list price" in lowered and "not measured spend" in lowered


def test_provenance_travels_with_the_number():
    claim = cost_per_1k_items(spec(), 2000, 500)
    assert claim.source_url == "https://example.invalid/pricing"
    assert claim.retrieved_at == date(2026, 8, 31)
    assert claim.method == "DERIVED"


def test_zero_tokens_raises_rather_than_reporting_free():
    with pytest.raises(ValueError):
        cost_per_1k_items(spec(), 0, 0)


def test_no_float_in_the_module():
    import inspect

    from ground_truth.matrix import cost

    assert "float(" not in inspect.getsource(cost)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/matrix/test_cost.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/matrix/cost.py`**

```python
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from ground_truth.providers import SlotSpec

LIST_PRICE_CAVEAT = (
    "List price for the paid tier, not measured spend. This benchmark runs on free tiers, "
    "where measured cost is zero and therefore meaningless."
)
_PER_MILLION = Decimal("1000000")


@dataclass(frozen=True)
class CostClaim:
    value: Decimal
    unit: str
    method: str
    source_url: str
    retrieved_at: date
    caveat: str


def cost_per_1k_items(spec: SlotSpec, mean_tokens_in: int, mean_tokens_out: int) -> CostClaim:
    if mean_tokens_in <= 0 and mean_tokens_out <= 0:
        raise ValueError("token counts must be positive; a zero cost would be a fabrication")
    value = (
        Decimal(mean_tokens_in) * Decimal(1000) / _PER_MILLION * spec.list_price_in_per_1m
        + Decimal(mean_tokens_out) * Decimal(1000) / _PER_MILLION * spec.list_price_out_per_1m
    ).quantize(Decimal("0.0001"))
    return CostClaim(
        value=value, unit="USD per 1,000 items", method="DERIVED",
        source_url=spec.pricing_url, retrieved_at=spec.retrieved_at, caveat=LIST_PRICE_CAVEAT,
    )
```

The caveat is a field on the value, not a footnote on the page. When `bok-core` lands, `CostClaim` becomes a `bok_core.provenance.Claim` and the caveat propagates to children automatically — the shape here is chosen so that substitution is mechanical.

- [ ] **Step 4: Extend the CI money gate**

In `.github/workflows/ci.yml`, add `ground_truth/matrix/` to the path list in the "no float in the money path" step.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/matrix/test_cost.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/matrix/ tests/matrix/ .github/workflows/ci.yml
git commit -m "feat: list-price cost model with the caveat attached to the value"
```

---

### Task 30: `matrix/latency.py` — a distribution, never a rank

**Files:**
- Create: `ground_truth/matrix/latency.py`
- Test: `tests/matrix/test_latency.py`

**Interfaces:**
- Consumes: `numpy`.
- Produces: `FREE_TIER_LATENCY_CAVEAT: str`; `LatencyDistribution(p50: float, p95: float, n: int, ecdf_x: list[float], ecdf_y: list[float], caveat: str)` (frozen, **no rank field**); `summarise_latency(latencies_ms: list[int]) -> LatencyDistribution`.

- [ ] **Step 1: Write the failing test**

```python
# tests/matrix/test_latency.py
import dataclasses

import pytest

from ground_truth.matrix.latency import (
    FREE_TIER_LATENCY_CAVEAT,
    LatencyDistribution,
    summarise_latency,
)


def test_percentiles_are_computed():
    dist = summarise_latency(list(range(1, 101)))
    assert dist.p50 == pytest.approx(50.5, abs=1.0)
    assert dist.p95 == pytest.approx(95.0, abs=1.0)


def test_n_is_reported():
    assert summarise_latency([1, 2, 3]).n == 3


def test_ecdf_is_monotone_and_complete():
    dist = summarise_latency([5, 1, 3, 2, 4])
    assert dist.ecdf_x == sorted(dist.ecdf_x)
    assert dist.ecdf_y[-1] == pytest.approx(1.0)
    assert len(dist.ecdf_x) == len(dist.ecdf_y) == 5


def test_caveat_is_attached():
    assert summarise_latency([1, 2, 3]).caveat == FREE_TIER_LATENCY_CAVEAT


def test_caveat_denies_paid_tier_estimation():
    lowered = FREE_TIER_LATENCY_CAVEAT.lower()
    assert "free tier" in lowered and "paid" in lowered and "not" in lowered


def test_latency_is_not_ranked():
    names = {f.name for f in dataclasses.fields(LatencyDistribution)}
    for banned in ("rank", "position", "place", "fastest"):
        assert banned not in names, "00 B4: latency is a distribution, never a ranking"


def test_empty_input_raises():
    with pytest.raises(ValueError):
        summarise_latency([])
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/matrix/test_latency.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/matrix/latency.py`**

```python
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

FREE_TIER_LATENCY_CAVEAT = (
    "Measured on free tiers. Free-tier latency does not estimate paid-tier latency and is "
    "not comparable across providers with different serving stacks. Reported as a "
    "distribution; models are not ranked on latency."
)


@dataclass(frozen=True)
class LatencyDistribution:
    p50: float
    p95: float
    n: int
    ecdf_x: list[float]
    ecdf_y: list[float]
    caveat: str


def summarise_latency(latencies_ms: list[int]) -> LatencyDistribution:
    if not latencies_ms:
        raise ValueError("cannot summarise an empty latency sample")
    values = np.sort(np.array(latencies_ms, dtype=float))
    n = int(values.size)
    return LatencyDistribution(
        p50=float(np.percentile(values, 50)),
        p95=float(np.percentile(values, 95)),
        n=n,
        ecdf_x=[float(v) for v in values],
        ecdf_y=[(i + 1) / n for i in range(n)],
        caveat=FREE_TIER_LATENCY_CAVEAT,
    )
```

There is no rank field, and `test_latency_is_not_ranked` inspects the dataclass to keep it that way.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/matrix/test_latency.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/matrix/latency.py tests/matrix/test_latency.py
git commit -m "feat: latency reported as an unranked distribution with its caveat"
```

---

### Task 31: `matrix/build.py` — leaderboard rows and "not distinguishable"

**Files:**
- Create: `ground_truth/matrix/build.py`
- Test: `tests/matrix/test_build.py`

**Interfaces:**
- Consumes: `store.db`, `stats.bootstrap.{Interval, cluster_bootstrap_ci}`, `matrix.cost.{CostClaim, cost_per_1k_items}`, `matrix.latency.{LatencyDistribution, summarise_latency}`, `providers.SlotSpec`, `golden.schema.Split`.
- Produces: `LeaderboardRow(slot: str, accuracy: Interval, cost: CostClaim, latency: LatencyDistribution, per_field: dict[str, Interval])` (frozen); `build_leaderboard(con, *, split: Split, seed: int, specs: dict[str, SlotSpec]) -> list[LeaderboardRow]`; `distinguishability_statements(rows: list[LeaderboardRow]) -> list[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/matrix/test_build.py
from datetime import date
from decimal import Decimal

from ground_truth.matrix.build import LeaderboardRow, distinguishability_statements
from ground_truth.matrix.cost import LIST_PRICE_CAVEAT, cost_per_1k_items
from ground_truth.matrix.latency import summarise_latency
from ground_truth.providers import SlotSpec
from ground_truth.stats.bootstrap import Interval


def spec(slot: str) -> SlotSpec:
    return SlotSpec(slot=slot, family="fam", provider="prov", model_ref="ref",
                    trains_on_data=False, commercial_use=True, exposes_fingerprint=False,
                    list_price_in_per_1m=Decimal("0.10"), list_price_out_per_1m=Decimal("0.40"),
                    pricing_url="https://example.invalid/p", retrieved_at=date(2026, 8, 31))


def row(slot: str, low: float, point: float, high: float) -> LeaderboardRow:
    return LeaderboardRow(
        slot=slot,
        accuracy=Interval(point=point, low=low, high=high, n=180, method="cluster-BCa"),
        cost=cost_per_1k_items(spec(slot), 2000, 500),
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
    assert distinguishability_statements(
        [row("slot-a", 0.60, 0.62, 0.64), row("slot-b", 0.90, 0.93, 0.96)]
    ) == []


def test_statement_carries_the_sample_size():
    statements = distinguishability_statements(
        [row("slot-a", 0.89, 0.92, 0.95), row("slot-b", 0.90, 0.93, 0.96)]
    )
    assert all("n=180" in s for s in statements)


def test_every_pair_is_examined():
    rows = [row("a", 0.89, 0.92, 0.95), row("b", 0.90, 0.93, 0.96), row("c", 0.91, 0.94, 0.97)]
    assert len(distinguishability_statements(rows)) == 3


def test_single_row_produces_no_statements():
    assert distinguishability_statements([row("a", 0.89, 0.92, 0.95)]) == []


def test_rows_carry_the_cost_caveat():
    assert row("a", 0.89, 0.92, 0.95).cost.caveat == LIST_PRICE_CAVEAT
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/matrix/test_build.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/matrix/build.py`**

`build_leaderboard` queries `verdicts` joined to `outputs`, `runs`, `items` and `item_fields`, filters to the requested split, **excludes verdicts from any judge whose field type was rejected in Task 27**, and assembles `(item_id, correct)` observations per slot — overall and per field type — feeding each through `cluster_bootstrap_ci`. Latency comes from `outputs.latency_ms` for that slot via `summarise_latency`; cost from `cost_per_1k_items` using the mean token counts recorded for the run.

`distinguishability_statements` walks every unordered pair, calls `a.accuracy.overlaps(b.accuracy)`, and for each overlap emits:

```
f"{a.slot} and {b.slot} are not distinguishable at this sample size: "
f"{a.accuracy.point:.3f} [{a.accuracy.low:.3f}, {a.accuracy.high:.3f}] versus "
f"{b.accuracy.point:.3f} [{b.accuracy.low:.3f}, {b.accuracy.high:.3f}], n={a.accuracy.n}."
```

That sentence is the brand. It has exactly one implementation, and it lives here.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/matrix/test_build.py -v`
Expected: PASS, 6 passed.

- [ ] **Step 5: Build the real leaderboard and read it**

```bash
uv run python -m ground_truth.matrix.build --split private --seed 1
```

Read the distinguishability statements. If **every** pair overlaps, that is a true result about your sample size, not a bug — report it, and let `describe_mde` state what n would be needed to separate them.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/matrix/build.py tests/matrix/test_build.py
git commit -m "feat: leaderboard rows with intervals and plain-language distinguishability"
```

---

### Task 32: `calibrate/curves.py` — replicate agreement, fit public, validate private

**Files:**
- Create: `ground_truth/calibrate/__init__.py`
- Create: `ground_truth/calibrate/curves.py`
- Modify: `pyproject.toml` — add `scikit-learn>=1.5`
- Test: `tests/calibrate/test_curves.py`

**Interfaces:**
- Consumes: `sklearn.isotonic.IsotonicRegression`, `sklearn.linear_model.LogisticRegression`, `numpy`.
- Produces: `ConfidencePoint(item_id: str, score: float, correct: bool)` (frozen); `replicate_agreement(verdicts: list[bool]) -> float`; `CalibrationCurve(field_type: str, method: str, points: list[tuple[float, float]], n_fit: int, n_validate: int, brier_fit: float, brier_validate: float, divergence: float)` (frozen); `fit_curve(fit_points, validate_points, field_type: str, method: str) -> CalibrationCurve`; `threshold_for_precision(curve: CalibrationCurve, target_precision: float) -> float | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/calibrate/test_curves.py
import random

import pytest

from ground_truth.calibrate.curves import (
    ConfidencePoint,
    fit_curve,
    replicate_agreement,
    threshold_for_precision,
)


def test_replicate_agreement_is_the_modal_proportion():
    assert replicate_agreement([True] * 5) == 1.0
    assert replicate_agreement([True, True, True, False, False]) == pytest.approx(0.6)
    assert replicate_agreement([True, False, False, False, False]) == pytest.approx(0.8)


def test_replicate_agreement_rejects_an_empty_sample():
    with pytest.raises(ValueError):
        replicate_agreement([])


def points(n: int, seed: int) -> list[ConfidencePoint]:
    rng = random.Random(seed)
    out = []
    for i in range(n):
        score = rng.uniform(0.5, 1.0)
        out.append(ConfidencePoint(f"i{i}", score, rng.random() < score))
    return out


def test_isotonic_curve_is_monotone():
    curve = fit_curve(points(200, 1), points(200, 2), "money", "isotonic")
    ys = [y for _, y in curve.points]
    assert ys == sorted(ys)


def test_platt_curve_fits():
    curve = fit_curve(points(200, 1), points(200, 2), "money", "platt")
    assert curve.method == "platt" and 0.0 <= curve.brier_validate <= 1.0


def test_unknown_method_raises():
    with pytest.raises(ValueError, match="unknown calibration method"):
        fit_curve(points(50, 1), points(50, 2), "money", "magic")


def test_sample_sizes_are_recorded_separately():
    curve = fit_curve(points(120, 1), points(180, 2), "money", "isotonic")
    assert curve.n_fit == 120 and curve.n_validate == 180


def test_divergence_is_small_when_splits_agree():
    assert fit_curve(points(300, 1), points(300, 2), "money", "isotonic").divergence < 0.1


def test_divergence_is_large_when_splits_disagree():
    fit = [ConfidencePoint(f"f{i}", 0.9, True) for i in range(200)]
    validate = [ConfidencePoint(f"v{i}", 0.9, i % 2 == 0) for i in range(200)]
    curve = fit_curve(fit, validate, "money", "isotonic")
    assert curve.divergence > 0.1, (
        "public-fit vs private-validate divergence is the contamination signal"
    )


def test_threshold_for_precision_is_on_the_curve():
    curve = fit_curve(points(300, 1), points(300, 2), "money", "isotonic")
    threshold = threshold_for_precision(curve, 0.9)
    if threshold is not None:
        calibrated = [y for x, y in curve.points if x >= threshold]
        assert calibrated and min(calibrated) >= 0.9 - 1e-6


def test_unreachable_precision_returns_none():
    fit = [ConfidencePoint(f"f{i}", 0.5, i % 2 == 0) for i in range(200)]
    assert threshold_for_precision(fit_curve(fit, list(fit), "money", "isotonic"), 0.99) is None
```

- [ ] **Step 2: Add the dependency and run the test to verify it fails**

```bash
uv add scikit-learn
uv run pytest tests/calibrate/test_curves.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.calibrate.curves'`.

- [ ] **Step 3: Write `ground_truth/calibrate/curves.py`**

`replicate_agreement(verdicts)` returns `max(count_true, count_false) / len(verdicts)` — the proportion of replicates producing the modal answer — raising `ValueError` on an empty list.

**This is the confidence signal being calibrated**, and the choice is deliberate: it exists for every model regardless of whether the provider exposes a confidence figure, the n≥5 replicate requirement (`04` B7) already generates it, and model-reported confidence is exactly the uncalibrated number this programme exists to distrust. Where a provider does expose a confidence or logprob, record it alongside and publish its own curve for comparison — but the exported curve Ledger Sense consumes is this one.

`fit_curve` fits on `fit_points` (public split) and evaluates on `validate_points` (private split), raising `ValueError("unknown calibration method")` for anything but `isotonic` or `platt`. It reports the Brier score on both and sets `divergence = abs(brier_validate - brier_fit)`. Divergence is the free contamination detector: if the public split has been trained on, the fitted curve stops describing the private split.

`threshold_for_precision` returns the smallest raw score `x` such that every calibrated value at or above `x` meets `target_precision`, or `None` when no such point exists.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/calibrate/test_curves.py -v`
Expected: PASS, 11 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/calibrate/ tests/calibrate/ pyproject.toml uv.lock
git commit -m "feat: calibration on replicate agreement, fit public, validate private"
```

---

### Task 33: `calibrate/export.py` — the file Ledger Sense reads

**Files:**
- Create: `ground_truth/calibrate/export.py`
- Test: `tests/calibrate/test_export.py`

**Interfaces:**
- Consumes: `calibrate.curves.{CalibrationCurve, threshold_for_precision}`.
- Produces: `EXPORT_SCHEMA_VERSION: str`; `export_curves(curves: list[CalibrationCurve], path: Path, *, rubric_version: str, fitted_at: datetime, targets: list[float]) -> None`; `load_export(path: Path) -> dict`.

- [ ] **Step 1: Write the failing test**

```python
# tests/calibrate/test_export.py
import json
import random
from datetime import UTC, datetime

from ground_truth.calibrate.curves import ConfidencePoint, fit_curve, threshold_for_precision
from ground_truth.calibrate.export import EXPORT_SCHEMA_VERSION, export_curves, load_export

FITTED_AT = datetime(2026, 10, 1, tzinfo=UTC)
TARGETS = [0.90, 0.95]


def points(n, seed):
    rng = random.Random(seed)
    return [
        ConfidencePoint(f"i{i}", score, rng.random() < score)
        for i in range(n)
        for score in [rng.uniform(0.5, 1.0)]
    ]


def curve(field_type="money"):
    return fit_curve(points(200, 1), points(200, 2), field_type, "isotonic")


def written(tmp_path):
    path = tmp_path / "calibration.json"
    export_curves([curve("money"), curve("percent")], path,
                  rubric_version="v1", fitted_at=FITTED_AT, targets=TARGETS)
    return path


def test_export_carries_the_schema_version(tmp_path):
    assert load_export(written(tmp_path))["schema_version"] == EXPORT_SCHEMA_VERSION


def test_every_required_key_is_present(tmp_path):
    entry = load_export(written(tmp_path))["curves"][0]
    assert set(entry) == {
        "field_type", "method", "curve_points", "n", "fitted_at",
        "rubric_version", "source_split", "threshold_recommendations",
    }


def test_source_split_states_the_design(tmp_path):
    assert load_export(written(tmp_path))["curves"][0]["source_split"] == "public-fit/private-validate"


def test_exported_thresholds_match_the_curve(tmp_path):
    body = load_export(written(tmp_path))
    for entry, source in zip(body["curves"], [curve("money"), curve("percent")], strict=True):
        for rec in entry["threshold_recommendations"]:
            assert rec["threshold"] == threshold_for_precision(source, rec["target_precision"])


def test_every_requested_target_appears(tmp_path):
    entry = load_export(written(tmp_path))["curves"][0]
    assert {r["target_precision"] for r in entry["threshold_recommendations"]} == set(TARGETS)


def test_export_is_byte_stable_for_a_fixed_input(tmp_path):
    path = written(tmp_path)
    first = path.read_text(encoding="utf-8")
    export_curves([curve("money"), curve("percent")], path,
                  rubric_version="v1", fitted_at=FITTED_AT, targets=TARGETS)
    assert path.read_text(encoding="utf-8") == first
    json.loads(first)


def test_n_is_the_validation_sample(tmp_path):
    assert load_export(written(tmp_path))["curves"][0]["n"] == 200, (
        "the published n is the held-out sample the curve was validated on"
    )
```

`test_export_is_byte_stable_for_a_fixed_input` matters for Phase 3's reproducibility test — a file that reorders keys between runs cannot regenerate byte-identically.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/calibrate/test_export.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/calibrate/export.py`**

`export_curves` writes `{"schema_version": EXPORT_SCHEMA_VERSION, "curves": [...]}` with `sort_keys=True` and `indent=2` for byte stability. Each entry carries exactly the eight keys the test asserts. `n` is `n_validate` — the held-out sample the curve was validated on, not the fitting sample. `source_split` is the literal `"public-fit/private-validate"`. `threshold_recommendations` is built by calling `threshold_for_precision` for each target, never by re-deriving a threshold some other way — that is what makes `test_exported_thresholds_match_the_curve` a real check rather than a tautology.

`load_export` reads and returns the parsed dict.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/calibrate/test_export.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Produce the real export and record the consumer contract**

```bash
uv run python -m ground_truth.calibrate.export --out artifacts/calibration.json
```

Add a section to `docs/methodology.md` stating: what the confidence signal is (replicate agreement, and why not model-reported confidence); which split fitted and which validated; the observed divergence and what a growing divergence would mean; and that Ledger Sense consumes this file as a published artifact with **no runtime coupling in either direction**, so neither project can block the other.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/calibrate/export.py artifacts/calibration.json docs/methodology.md tests/calibrate/test_export.py
git commit -m "feat: byte-stable calibration export for Ledger Sense"
```

---

### Task 34: `stats/sequential.py` — alpha spending on a declared calendar

**Files:**
- Create: `ground_truth/stats/sequential.py`
- Test: `tests/stats/test_sequential.py`

**Interfaces:**
- Consumes: `scipy.stats.norm`.
- Produces: `LOOKS_PER_QUARTER: int = 13`; `obrien_fleming_boundary(look: int, total_looks: int, *, alpha: float = 0.05) -> float`; `spent_alpha(look: int, total_looks: int, *, alpha: float = 0.05) -> float`; `SequentialResult(look: int, total_looks: int, z: float, boundary: float, reject: bool, statement: str)` (frozen); `evaluate_look(z: float, look: int, total_looks: int, *, alpha: float = 0.05) -> SequentialResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/stats/test_sequential.py
import random
from pathlib import Path

import pytest

from ground_truth.stats.sequential import (
    LOOKS_PER_QUARTER,
    evaluate_look,
    obrien_fleming_boundary,
    spent_alpha,
)

PLAN = Path(__file__).resolve().parents[2] / "docs" / "analysis-plan.md"


def test_looks_per_quarter_matches_the_pre_registered_plan():
    assert str(LOOKS_PER_QUARTER) in PLAN.read_text(encoding="utf-8")


def test_early_boundaries_are_stricter_than_late_ones():
    assert obrien_fleming_boundary(1, 13) > obrien_fleming_boundary(13, 13)


def test_final_boundary_is_near_the_fixed_sample_critical_value():
    assert obrien_fleming_boundary(13, 13) == pytest.approx(1.96, abs=0.15)


def test_alpha_spent_is_monotone_and_totals_alpha():
    spent = [spent_alpha(k, 13) for k in range(1, 14)]
    assert spent == sorted(spent)
    assert spent[-1] == pytest.approx(0.05, abs=1e-9)


def test_look_out_of_range_raises():
    with pytest.raises(ValueError):
        obrien_fleming_boundary(0, 13)
    with pytest.raises(ValueError):
        obrien_fleming_boundary(14, 13)


def test_result_states_the_test_used():
    result = evaluate_look(4.5, look=2, total_looks=13)
    assert "O'Brien-Fleming" in result.statement
    assert "look 2 of 13" in result.statement


def test_a_null_result_is_not_reported_as_no_change():
    result = evaluate_look(0.2, look=2, total_looks=13)
    assert not result.reject
    assert "no change was detected" in result.statement
    assert "does not mean no change occurred" in result.statement


@pytest.mark.slow
def test_sequential_controls_type_i_under_null():
    rng = random.Random(0)
    trials = 2000
    rejected = sum(
        any(evaluate_look(rng.gauss(0, 1), look=k, total_looks=13).reject for k in range(1, 14))
        for _ in range(trials)
    )
    rate = rejected / trials
    assert rate <= 0.06, f"family-wise type I error {rate:.4f} exceeds nominal 0.05"


@pytest.mark.slow
def test_fixed_threshold_inflates_alpha():
    rng = random.Random(0)
    trials = 2000
    rejected = sum(any(abs(rng.gauss(0, 1)) > 1.96 for _ in range(13)) for _ in range(trials))
    rate = rejected / trials
    assert rate > 0.20, (
        f"a naive per-look threshold rejects {rate:.3f} of null trajectories — this is why "
        "the regression watch uses alpha spending, and this number goes on the methodology page"
    )
```

`test_fixed_threshold_inflates_alpha` makes the methodology page's central claim executable. The number it produces is the number you publish.

- [ ] **Step 2: Run the fast tests to verify they fail**

Run: `uv run pytest tests/stats/test_sequential.py -v -m "not slow"`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/stats/sequential.py`**

`obrien_fleming_boundary(look, total_looks, alpha)` raises `ValueError` outside `1 <= look <= total_looks`, computes the information fraction `t = look / total_looks`, and returns `norm.ppf(1 - alpha / 2) / sqrt(t)` — strict early, approaching the fixed-sample critical value at the final look.

`spent_alpha(look, total_looks, alpha)` returns the cumulative alpha spent through that look under the same boundary, computed as the accumulated `2 * (1 - norm.cdf(boundary_k))` across looks `1..look`, normalised so the value at the final look equals `alpha` exactly.

`evaluate_look` compares `abs(z)` to the boundary and composes a statement that always names the test, the look, and the boundary:

- Reject: `f"Change detected at look {look} of {total_looks}: |z| = {abs(z):.3f} exceeds the O'Brien-Fleming boundary of {boundary:.3f} (alpha spent to date {spent:.4f})."`
- No reject: `f"At look {look} of {total_looks}, no change was detected: |z| = {abs(z):.3f} is within the O'Brien-Fleming boundary of {boundary:.3f}. This does not mean no change occurred — see the minimum detectable effect for this sample."`

Alerts state their test. That is a publication rule, and it lives inside the string that produces the alert rather than in a style guide someone has to remember.

- [ ] **Step 4: Run the fast tests**

Run: `uv run pytest tests/stats/test_sequential.py -v -m "not slow"`
Expected: PASS, 7 passed, 2 deselected.

- [ ] **Step 5: Run both null simulations**

Run: `uv run pytest tests/stats/test_sequential.py -v -m slow`
Expected: PASS, 2 passed. **Record the exact figure `test_fixed_threshold_inflates_alpha` reports** — it goes on the methodology page as the measured reason the naive approach was rejected.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/stats/sequential.py tests/stats/test_sequential.py
git commit -m "feat: O'Brien-Fleming alpha spending validated under null simulation"
```

---

### Task 35: Phase 2 integration gate

**Files:**
- Create: `tests/test_phase2_e2e.py`
- Modify: `docs/methodology.md`

**Interfaces:**
- Consumes: everything built in Phases 1 and 2.
- Produces: no new symbols. Produces a verified phase boundary against the real database.

- [ ] **Step 1: Write the integration test**

```python
# tests/test_phase2_e2e.py
from pathlib import Path

import pytest

from ground_truth.analysis_plan import assert_frozen_before_first_sweep
from ground_truth.golden.rubric import loaded_rubric
from ground_truth.golden.schema import FieldType
from ground_truth.store.db import connect

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "results.duckdb"


@pytest.fixture()
def con():
    if not DB.exists():
        pytest.skip("run the sweep first: python -m ground_truth.schedule")
    c = connect(DB)
    yield c
    c.close()


def test_pre_registration_held_across_the_real_sweep(con):
    assert_frozen_before_first_sweep(con)


def test_every_slot_has_five_replicates_per_item(con):
    bad = con.execute(
        "SELECT r.model_slot, o.item_id, count(*) c FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id GROUP BY 1, 2 HAVING c <> 5"
    ).fetchall()
    assert bad == [], f"incomplete replicate sets: {bad[:5]}"


def test_replicates_are_not_all_identical(con):
    """If every replicate matches, the cache was on and the variance is fabricated."""
    identical = con.execute(
        "SELECT count(*) FROM (SELECT o.item_id, r.model_slot FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id GROUP BY 1, 2 "
        "HAVING count(DISTINCT o.raw_output) = 1)"
    ).fetchone()[0]
    total = con.execute(
        "SELECT count(*) FROM (SELECT o.item_id, r.model_slot FROM outputs o "
        "JOIN runs r ON r.run_id = o.run_id GROUP BY 1, 2)"
    ).fetchone()[0]
    assert identical < total, (
        "every replicate set is identical — check that runner.BENCHMARK_CACHE is False"
    )


def test_provider_served_is_recorded_for_every_call(con):
    missing = con.execute(
        "SELECT count(*) FROM outputs WHERE provider_served IS NULL OR provider_served = ''"
    ).fetchone()[0]
    assert missing == 0, "00 B8: which provider served each call must be recorded"


def test_ledger_call_id_recorded_for_every_call(con):
    missing = con.execute(
        "SELECT count(*) FROM outputs WHERE ledger_call_id IS NULL OR ledger_call_id = ''"
    ).fetchone()[0]
    assert missing == 0, "00 R7: fingerprint tracking depends on the ledger foreign key"


def test_judge_touched_only_the_free_text_field(con):
    fields = {r[0] for r in con.execute("SELECT DISTINCT field_name FROM judge_samples").fetchall()}
    assert fields <= {"line_1_description"}, f"the judge must only score free text; it touched {fields}"


def test_both_presentation_orders_occurred(con):
    orders = {r[0] for r in con.execute("SELECT DISTINCT presentation_order FROM judge_samples").fetchall()}
    assert orders == {0, 1}, "order randomisation did not actually vary the presentation"


def test_every_deterministic_field_type_has_verdicts(con):
    rubric = loaded_rubric(REPO / "docs" / "rubric.md")
    deterministic = {ft.value for ft, rule in rubric.items() if rule.grader != "judge"}
    graded = {
        r[0]
        for r in con.execute(
            "SELECT DISTINCT f.field_type FROM verdicts v "
            "JOIN item_fields f ON f.field_name = v.field_name"
        ).fetchall()
    }
    assert deterministic - graded == set(), f"field types with no verdicts: {deterministic - graded}"
```

- [ ] **Step 2: Run the integration test against the real database**

Run: `uv run pytest tests/test_phase2_e2e.py -v`
Expected: PASS, 8 passed.

Two of these deserve attention if they fail. `test_replicates_are_not_all_identical` failing means the response cache was active and **the entire sweep's variance is fabricated** — fix the setting and re-run the sweep; do not weaken the test. `test_both_presentation_orders_occurred` failing means the seed derivation collapsed to one order, and every judge bias control downstream is measuring nothing.

- [ ] **Step 3: Write the Phase 2 sections of `docs/methodology.md`**

With actual numbers, not placeholders: the run schedule and observed wall-clock; how many slots survived the audit and why any were dropped; the judge configuration and its family separation; the judge-agreement table covering **every** field type the judge touched, with accept/reject status; the order-effect and length-effect figures; the calibration confidence signal and the observed public-fit/private-validate divergence; and the figure from `test_fixed_threshold_inflates_alpha` as the measured justification for alpha spending.

- [ ] **Step 4: Run the complete gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -v`
Expected: all four pass, coverage ≥ 75%.

- [ ] **Step 5: Commit and tag**

```bash
git add tests/test_phase2_e2e.py docs/methodology.md
git commit -m "test: phase-2 integration gate over the real sweep"
git tag -a phase-2-measurement -m "Phase 2: full sweep, judge, statistics, matrix, calibration"
```

---

## Phase 2 exit criteria

All of these must hold before starting Phase 3:

- [ ] `uv run pytest -v` passes with coverage ≥ 75%; `uv run mypy` passes under `--strict`.
- [ ] The full sweep completed: every (item × slot) has exactly 5 replicates, and `test_replicates_are_not_all_identical` passes on the real database.
- [ ] `assert_frozen_before_first_sweep` passes against the **real** `data/results.duckdb`, not a fixture.
- [ ] The judge's family differs from every model slot it scored, with `test_same_family_judge_rejected` exercised against real `models.yaml` entries.
- [ ] `REJECTION_THRESHOLD` and `LOOKS_PER_QUARTER` in code are chained to `docs/analysis-plan.md` by passing tests, and neither has been edited since the plan was frozen.
- [ ] Human labels round 1 collected, **with the date recorded in `docs/methodology.md`** — Phase 3's round 2 needs a minimum two-week gap from it.
- [ ] `artifacts/calibration.json` exists, is byte-stable across reruns, and its thresholds match the curves.
- [ ] The `test_fixed_threshold_inflates_alpha` figure is recorded in `docs/methodology.md`.
- [ ] Both null simulations (`test_bh_controls_fdr_under_null`, `test_sequential_controls_type_i_under_null`) have been run at full trial count and passed.

**Definition-of-done items satisfied by this phase:** `04` §12 items **4** (measured and reported — publication lands in Phase 3), **5**, **6**, and the statistical half of **7**.

Items 2 (publication), 7 (running on a schedule), and 9–11 belong to Phase 3.
