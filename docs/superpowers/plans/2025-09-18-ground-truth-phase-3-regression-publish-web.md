# Ground Truth — Phase 3: Regression, Publication, and Web (Weeks 25–26) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn measured numbers into a published, reproducible, defensible artifact — regression watch on a schedule, contamination-safe publication, a leaderboard someone can re-run, and the six screens.

**Architecture:** Unchanged. Publication is a phase-2 read: `publish/` queries DuckDB and emits static JSON, which the Next.js static export consumes at build time. Nothing in the web layer talks to a database or a model at runtime.

**Tech Stack:** Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `duckdb`, `scipy`; Next.js 15 (`output: 'export'`), `bok-ui`, Playwright, `axe-core`.

**Spec:** `docs/superpowers/specs/2025-09-18-ground-truth-design.md`

**Prerequisite:** Phase 2 exit criteria all met; `git tag phase-2-measurement` exists. **Human labels round 1 was collected at least fourteen days ago** — check the date in `docs/methodology.md` before starting Task 39.

**Phase deliverable:** the public artifact. Leaderboard deployed, methodology published, numbers regenerable by a stranger.

## Global Constraints

Every task's requirements implicitly include this section. Restated because plan files are read independently.

- **Python 3.12+**, `uv`, `ruff`, `mypy --strict`. TypeScript strict mode, no `any` without a comment justifying it.
- **No model name is ever hardcoded** (`00` R1).
- **No secrets in the repo, including fixtures.** `gitleaks` pre-commit.
- **Money uses `Decimal`. Never `float`.**
- **`golden/corpus/private/` stays gitignored; the private seed stays in `.env`.** No private item content, and no model output on a private item, may appear in any published artifact.
- **The analysis plan stays frozen.** A changed threshold is a new plan version with a changelog entry.
- **Publication rules** (spec §13.2), each enforced by a test in this phase: no claim without its sample; overlapping intervals stated in words; alerts state their test; versioned, dated, changelogged, no silent edits; never characterise a vendor's honesty; empty states say what has not been measured.
- **Licence Apache-2.0.** Coverage floor 75%. WCAG 2.2 AA, zero serious/critical `axe` violations.
- **Every task's verification implicitly ends with the non-goal check:** *Did this task add an abstraction whose second implementation does not exist? If yes, STOP and report — that is the platform trap arriving.*

---

### Task 36: `regression/fingerprint.py` — record what you can, admit what you cannot

**Files:**
- Create: `ground_truth/regression/__init__.py`
- Create: `ground_truth/regression/fingerprint.py`
- Test: `tests/regression/test_fingerprint.py`

**Interfaces:**
- Consumes: `store.db`.
- Produces: `FingerprintStatus` (`StrEnum`: `STABLE`, `CHANGED`, `NOT_EXPOSED`); `SlotFingerprint(slot: str, status: FingerprintStatus, values: list[str], first_seen: datetime, last_seen: datetime, statement: str)` (frozen); `observe_fingerprints(con, sweep_id: str) -> list[SlotFingerprint]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/regression/test_fingerprint.py
from datetime import UTC, datetime

import pytest

from ground_truth.regression.fingerprint import FingerprintStatus, observe_fingerprints
from ground_truth.store.db import connect, migrate


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def seed(con, slot: str, fingerprints: list[str | None]) -> None:
    run_id = f"run-{slot}"
    con.execute(
        "INSERT INTO runs VALUES (?,?,NULL,?,'ref','prov',false,'sweep-1','sha','h')",
        [run_id, datetime.now(UTC), slot],
    )
    for i, fp in enumerate(fingerprints):
        con.execute(
            "INSERT INTO outputs VALUES (?,?,?,1,'{}','call','prov',?,10,'ph',?)",
            [f"{slot}-{i}", run_id, f"i{i}", fp, datetime.now(UTC)],
        )


def test_stable_fingerprint_is_reported_stable(con):
    seed(con, "slot-a", ["fp-1"] * 5)
    result = observe_fingerprints(con, "sweep-1")[0]
    assert result.status is FingerprintStatus.STABLE and result.values == ["fp-1"]


def test_changed_fingerprint_is_detected(con):
    seed(con, "slot-a", ["fp-1", "fp-1", "fp-2"])
    result = observe_fingerprints(con, "sweep-1")[0]
    assert result.status is FingerprintStatus.CHANGED
    assert set(result.values) == {"fp-1", "fp-2"}


def test_absent_fingerprint_is_reported_as_not_exposed(con):
    seed(con, "slot-a", [None] * 5)
    assert observe_fingerprints(con, "sweep-1")[0].status is FingerprintStatus.NOT_EXPOSED


def test_not_exposed_statement_does_not_imply_a_pinned_version(con):
    seed(con, "slot-a", [None] * 5)
    statement = observe_fingerprints(con, "sweep-1")[0].statement
    assert "does not expose" in statement
    assert "cannot pin" in statement, (
        "04 B6: say so rather than implying we can pin a version we cannot"
    )


def test_changed_statement_names_both_values(con):
    seed(con, "slot-a", ["fp-1", "fp-2"])
    statement = observe_fingerprints(con, "sweep-1")[0].statement
    assert "fp-1" in statement and "fp-2" in statement


def test_partial_exposure_counts_as_changed(con):
    seed(con, "slot-a", ["fp-1", None, "fp-1"])
    assert observe_fingerprints(con, "sweep-1")[0].status is FingerprintStatus.CHANGED


def test_every_slot_in_the_sweep_is_reported(con):
    seed(con, "slot-a", ["fp-1"])
    seed(con, "slot-b", [None])
    assert {r.slot for r in observe_fingerprints(con, "sweep-1")} == {"slot-a", "slot-b"}
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/regression/test_fingerprint.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.regression.fingerprint'`.

- [ ] **Step 3: Write `ground_truth/regression/fingerprint.py`**

`observe_fingerprints` groups `outputs` by `runs.model_slot` for the given sweep, collecting distinct `fingerprint` values plus first and last `observed_at`. Status is `NOT_EXPOSED` when every value is null, `STABLE` when there is exactly one non-null value and no nulls, and `CHANGED` otherwise — **including partial exposure**, because a slot that sometimes reports a fingerprint and sometimes does not is not a slot whose version you know.

The statements are what get published:

- Stable: `f"{slot} reported a single fingerprint {values[0]!r} across the sweep ({first_seen:%Y-%m-%d} to {last_seen:%Y-%m-%d})."`
- Changed: `f"{slot} reported more than one fingerprint across the sweep: {', '.join(sorted(values))}. Results from this slot span more than one served version."`
- Not exposed: `f"{slot} does not expose a version fingerprint. We cannot pin the served version and do not claim to; results are attributed to the slot as served between {first_seen:%Y-%m-%d} and {last_seen:%Y-%m-%d}."`

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/regression/test_fingerprint.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/regression/ tests/regression/
git commit -m "feat: fingerprint observation that admits when a version cannot be pinned"
```

---

### Task 37: `regression/detect.py` — statistics, not thresholds

**Files:**
- Create: `ground_truth/regression/detect.py`
- Test: `tests/regression/test_detect.py`

**Interfaces:**
- Consumes: `stats.bootstrap.{Interval, cluster_bootstrap_ci}`, `stats.correction.{Comparison, benjamini_hochberg}`, `stats.sequential.evaluate_look`, `stats.mde.describe_mde`.
- Produces: `Alert(slot: str, field_type: str, baseline: Interval, current: Interval, z: float, adjusted_p: float, look: int, total_looks: int, detected: bool, statement: str)` (frozen); `detect_drift(baseline: dict[tuple[str, str], list[tuple[str, bool]]], current: dict[tuple[str, str], list[tuple[str, bool]]], *, look: int, total_looks: int, seed: int) -> list[Alert]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/regression/test_detect.py
import random

import pytest

from ground_truth.regression.detect import detect_drift


def obs(n: int, p: float, seed: int) -> list[tuple[str, bool]]:
    rng = random.Random(seed)
    return [(f"i{i}", rng.random() < p) for i in range(n)]


def test_no_drift_produces_no_detection():
    base = {("slot-a", "money"): obs(180, 0.90, 1)}
    curr = {("slot-a", "money"): obs(180, 0.90, 2)}
    assert not any(a.detected for a in detect_drift(base, curr, look=5, total_looks=13, seed=1))


def test_large_drift_is_detected():
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    assert any(a.detected for a in detect_drift(base, curr, look=5, total_looks=13, seed=1))


def test_alert_states_its_test():
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    alert = next(a for a in detect_drift(base, curr, look=5, total_looks=13, seed=1) if a.detected)
    assert "O'Brien-Fleming" in alert.statement
    assert "Benjamini-Hochberg" in alert.statement
    assert "look 5 of 13" in alert.statement


def test_alert_carries_both_intervals():
    base = {("slot-a", "money"): obs(180, 0.95, 1)}
    curr = {("slot-a", "money"): obs(180, 0.55, 2)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert alert.baseline.n == 180 and alert.current.n == 180


def test_a_null_result_reports_undetectable_not_absent():
    base = {("slot-a", "money"): obs(180, 0.90, 1)}
    curr = {("slot-a", "money"): obs(180, 0.90, 2)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1)[0]
    assert not alert.detected
    assert "percentage points" in alert.statement
    assert "not that none exists" in alert.statement, (
        "a null result must state what the sample could not see"
    )


def test_multiplicity_correction_is_applied_across_all_comparisons():
    base = {(f"slot-{i}", "money"): obs(180, 0.90, i) for i in range(12)}
    curr = {(f"slot-{i}", "money"): obs(180, 0.90, 100 + i) for i in range(12)}
    alerts = detect_drift(base, curr, look=5, total_looks=13, seed=1)
    assert len(alerts) == 12
    assert sum(a.detected for a in alerts) == 0, "12 null comparisons should not produce a detection"


def test_missing_baseline_key_raises_rather_than_silently_skipping():
    with pytest.raises(KeyError):
        detect_drift({}, {("slot-a", "money"): obs(10, 0.9, 1)}, look=1, total_looks=13, seed=1)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/regression/test_detect.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/regression/detect.py`**

For each `(slot, field_type)` key in `current`, look up `baseline` — raising `KeyError` on a miss rather than skipping, because a silently skipped comparison is a regression you will never see. Compute both intervals via `cluster_bootstrap_ci`, form a two-proportion z statistic, collect every comparison, run `benjamini_hochberg` across the whole set, and pass each z to `evaluate_look`.

`detected` is `True` only when **both** the sequential boundary is crossed **and** the BH-adjusted p is significant. Two gates, because one look at one comparison is exactly the setup that produces alert spam, then muted alerts, then a missed real regression.

The statement always names both procedures and the look; a null result always carries the MDE:

- Detected: `f"{slot}/{field_type}: {baseline.point:.3f} [{baseline.low:.3f}, {baseline.high:.3f}] -> {current.point:.3f} [{current.low:.3f}, {current.high:.3f}]. Change detected at look {look} of {total_looks} (O'Brien-Fleming alpha spending, |z| = {abs(z):.3f}; Benjamini-Hochberg adjusted p = {adjusted_p:.4f} across {n_comparisons} comparisons)."`
- Not detected: the same interval prefix, then `f"No change detected at look {look} of {total_looks} (O'Brien-Fleming alpha spending; Benjamini-Hochberg adjusted p = {adjusted_p:.4f}). "` followed by `describe_mde(...)`, which already ends with *"not that none exists."*

Never a bare red arrow. The alert **is** the sentence.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/regression/test_detect.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/regression/detect.py tests/regression/test_detect.py
git commit -m "feat: drift detection gated on both sequential boundary and BH correction"
```

---

### Task 38: `regression/schedule.py` — the watch, on a calendar

**Files:**
- Create: `ground_truth/regression/schedule.py`
- Create: `.github/workflows/regression-watch.yml`
- Modify: `ground_truth/store/db.py` — add the `looks` table
- Modify: `tests/store/test_db.py` — add `looks` to `EXPECTED`
- Test: `tests/regression/test_schedule.py`

**Interfaces:**
- Consumes: `stats.sequential.LOOKS_PER_QUARTER`, `store.db`.
- Produces: `LookRecord(quarter: str, look: int, total_looks: int, run_at: datetime)` (frozen); `next_look(con, now: datetime) -> LookRecord`; `record_look(con, record: LookRecord) -> None`; `unscheduled_look_warning(record: LookRecord) -> str | None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/regression/test_schedule.py
from datetime import UTC, datetime, timedelta

import pytest

from ground_truth.regression.schedule import (
    LookRecord,
    next_look,
    record_look,
    unscheduled_look_warning,
)
from ground_truth.stats.sequential import LOOKS_PER_QUARTER
from ground_truth.store.db import connect, migrate


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_first_look_of_a_quarter_is_one(con):
    record = next_look(con, datetime(2026, 10, 5, tzinfo=UTC))
    assert record.look == 1 and record.total_looks == LOOKS_PER_QUARTER


def test_looks_increment_within_a_quarter(con):
    now = datetime(2026, 10, 5, tzinfo=UTC)
    record_look(con, next_look(con, now))
    assert next_look(con, now + timedelta(days=7)).look == 2


def test_a_new_quarter_resets_the_look_counter(con):
    record_look(con, next_look(con, datetime(2026, 10, 5, tzinfo=UTC)))
    assert next_look(con, datetime(2027, 1, 5, tzinfo=UTC)).look == 1


def test_quarter_label_is_recorded(con):
    assert next_look(con, datetime(2026, 10, 5, tzinfo=UTC)).quarter == "2026Q4"


def test_exceeding_the_calendar_warns_about_spent_alpha():
    record = LookRecord(quarter="2026Q4", look=LOOKS_PER_QUARTER + 1,
                        total_looks=LOOKS_PER_QUARTER, run_at=datetime(2026, 12, 30, tzinfo=UTC))
    warning = unscheduled_look_warning(record)
    assert warning is not None and "alpha" in warning and "changelog" in warning


def test_a_scheduled_look_produces_no_warning(con):
    assert unscheduled_look_warning(next_look(con, datetime(2026, 10, 5, tzinfo=UTC))) is None


def test_recording_the_same_look_twice_raises(con):
    now = datetime(2026, 10, 5, tzinfo=UTC)
    record = next_look(con, now)
    record_look(con, record)
    with pytest.raises(Exception):
        record_look(con, record)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/regression/test_schedule.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Add the `looks` table to `ground_truth/store/db.py`**

```sql
CREATE TABLE IF NOT EXISTS looks (
    quarter TEXT NOT NULL, look INTEGER NOT NULL, total_looks INTEGER NOT NULL,
    run_at TIMESTAMP NOT NULL, PRIMARY KEY (quarter, look));
```

Add `"looks"` to the `TABLES` constant, and to `EXPECTED` in `tests/store/test_db.py`. Re-run `uv run pytest tests/store/test_db.py -v` — expected PASS. The composite primary key is what makes `test_recording_the_same_look_twice_raises` pass: an accidentally repeated look would silently spend alpha twice.

- [ ] **Step 4: Write `ground_truth/regression/schedule.py`**

`next_look` derives the quarter label as `f"{now.year}Q{(now.month - 1) // 3 + 1}"`, counts existing rows for that quarter, and returns look `count + 1` with `total_looks = LOOKS_PER_QUARTER`. `record_look` inserts. `unscheduled_look_warning` returns `None` when `record.look <= record.total_looks`, otherwise:

```
f"Look {record.look} exceeds the {record.total_looks} looks pre-registered for {record.quarter}. "
f"This look spends alpha beyond the declared calendar and must be recorded in the changelog "
f"before any result from it is published."
```

- [ ] **Step 5: Write `.github/workflows/regression-watch.yml`**

A weekly `schedule: cron` job that runs the sweep against the private split, then `regression.detect`, then `regression.fingerprint`. It opens a GitHub issue on any detected alert with the alert's **statement** as the body — never a bare arrow, never a bare percentage — and appends any `CHANGED` or `NOT_EXPOSED` fingerprint statement.

Per spec §13.3, a regression finding naming a provider carries a **10-business-day notice** before publication. The workflow therefore opens the issue and stops; it does **not** auto-publish a drift finding. Publishing that finding is a manual step after the notice period, and the workflow's issue body says so.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/regression/test_schedule.py tests/store/test_db.py -v`
Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add ground_truth/regression/schedule.py ground_truth/store/db.py .github/workflows/regression-watch.yml tests/
git commit -m "feat: quarterly look calendar with unscheduled-look alpha warning"
```

---

### Task 39: Human labels round 2 — blind re-label, intra-rater agreement

**Prerequisite check, before anything else:** open `docs/methodology.md`, find the round-1 date, and confirm **at least fourteen days** have passed. If they have not, this task is blocked. Do not shorten the gap — a blind re-label after three days measures short-term memory, not intra-rater reliability, and publishing it as the latter would be the precise failure this project exists to correct. Record the block, proceed to Task 40, and return when the gap is real.

**Files:**
- Create: `ground_truth/labelling.py`
- Test: `tests/test_labelling.py`

**Interfaces:**
- Consumes: `stats.agreement.cohens_kappa`, `stats.bootstrap.{Interval, cluster_bootstrap_ci}`, `store.db`.
- Produces: `MIN_GAP_DAYS: int = 14`; `RelabelGapTooShort(RuntimeError)`; `sample_for_relabel(con, *, fraction: float, seed: int) -> list[tuple[str, str]]`; `IntraRaterReport(kappa: float, kappa_ci: Interval, n_units: int, gap_days: int, disagreements: list[tuple[str, str, str, str]], statement: str)` (frozen); `intra_rater_agreement(con, labeller_id: str, *, seed: int) -> IntraRaterReport`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_labelling.py
from datetime import UTC, datetime, timedelta

import pytest

from ground_truth.labelling import (
    MIN_GAP_DAYS,
    RelabelGapTooShort,
    intra_rater_agreement,
    sample_for_relabel,
)
from ground_truth.store.db import connect, migrate


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def label(con, item_id, round_, value, at, labeller="me"):
    con.execute(
        "INSERT INTO human_labels VALUES (?,?,?,NULL,?,?,?,?)",
        [f"{item_id}-{round_}", item_id, "line_1_description", labeller, round_, value, at],
    )


def seed_rounds(con, n, agree_upto, gap_days=MIN_GAP_DAYS + 1):
    t1 = datetime(2026, 10, 1, tzinfo=UTC)
    t2 = t1 + timedelta(days=gap_days)
    for i in range(n):
        label(con, f"i{i}", 1, "EQUIVALENT", t1)
        label(con, f"i{i}", 2, "EQUIVALENT" if i < agree_upto else "NOT_EQUIVALENT", t2)


def test_relabel_sample_is_the_requested_fraction(con):
    for i in range(100):
        label(con, f"i{i}", 1, "EQUIVALENT", datetime(2026, 10, 1, tzinfo=UTC))
    assert len(sample_for_relabel(con, fraction=0.20, seed=1)) == 20


def test_relabel_sample_is_deterministic(con):
    for i in range(100):
        label(con, f"i{i}", 1, "EQUIVALENT", datetime(2026, 10, 1, tzinfo=UTC))
    assert sample_for_relabel(con, fraction=0.2, seed=1) == sample_for_relabel(con, fraction=0.2, seed=1)


def test_short_gap_raises(con):
    seed_rounds(con, 40, 40, gap_days=3)
    with pytest.raises(RelabelGapTooShort, match="14"):
        intra_rater_agreement(con, "me", seed=1)


def test_perfect_self_agreement_reports_kappa_one(con):
    seed_rounds(con, 40, 40)
    assert intra_rater_agreement(con, "me", seed=1).kappa == pytest.approx(1.0)


def test_disagreements_are_listed_not_hidden(con):
    seed_rounds(con, 40, 30)
    assert len(intra_rater_agreement(con, "me", seed=1).disagreements) == 10


def test_statement_reports_the_disagreement_rate_honestly(con):
    seed_rounds(con, 40, 30)
    statement = intra_rater_agreement(con, "me", seed=1).statement
    assert "25.0%" in statement
    assert "disagree" in statement.lower()


def test_statement_states_the_gap(con):
    seed_rounds(con, 40, 40)
    assert f"{MIN_GAP_DAYS + 1} days" in intra_rater_agreement(con, "me", seed=1).statement


def test_no_round_two_labels_raises(con):
    for i in range(10):
        label(con, f"i{i}", 1, "EQUIVALENT", datetime(2026, 10, 1, tzinfo=UTC))
    with pytest.raises(ValueError, match="no round-2"):
        intra_rater_agreement(con, "me", seed=1)
```

`test_statement_reports_the_disagreement_rate_honestly` is the point of the whole task. `04` B1: reporting the disagreement rate is more credible than a suspiciously clean set.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_labelling.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/labelling.py`**

`sample_for_relabel` selects a deterministic `fraction` of round-1 labelled `(item_id, field_name)` pairs using `random.Random(seed)` over a sorted list, emitting them **in shuffled order with the round-1 values withheld** — the re-label must be blind or it measures nothing.

`intra_rater_agreement` joins round-1 to round-2 labels for the given labeller, raising `ValueError("no round-2 labels")` on an empty join and `RelabelGapTooShort` when `min(round2_at) - max(round1_at) < timedelta(days=MIN_GAP_DAYS)`, with `MIN_GAP_DAYS` named in the message. It computes κ, bootstraps a CI on per-unit self-agreement, and lists **every** disagreement as `(item_id, field_name, round1_value, round2_value)`.

The statement leads with the disagreement rate:

```
f"Intra-rater agreement for {labeller_id} on {n_units} re-labelled items, {gap_days} days after "
f"the first pass: Cohen's kappa = {kappa:.3f} [{low:.3f}, {high:.3f}]. The two passes disagree on "
f"{rate:.1%} of items ({len(disagreements)} of {n_units}); every disagreement is listed in the "
f"item explorer with both values."
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_labelling.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 5: Perform the actual blind re-label**

```bash
uv run python -m ground_truth.labelling --sample --fraction 0.20 --seed 1 --out /tmp/relabel.csv
```

Label the sampled items **without looking at your round-1 values**, load them with `round=2`, then:

```bash
uv run python -m ground_truth.labelling --report --labeller me
```

Paste the resulting statement into `docs/methodology.md` verbatim, disagreement rate included. If the rate is high, that is information about the rubric's ambiguity — record which items disagreed and why, and consider whether the adjudication rules need a new rubric version. **Do not quietly re-label to agree.**

- [ ] **Step 6: Commit**

```bash
git add ground_truth/labelling.py docs/methodology.md tests/test_labelling.py
git commit -m "feat: blind re-label sampling and honest intra-rater agreement reporting"
```

---

### Task 40: `publish/artifacts.py` — contamination-safe publication

**Files:**
- Create: `ground_truth/publish/__init__.py`
- Create: `ground_truth/publish/artifacts.py`
- Test: `tests/publish/test_artifacts.py`

**Interfaces:**
- Consumes: `store.db`, `matrix.build.build_leaderboard`.
- Produces: `PublicVerdict(item_id, slot, field_name, correct, grader_id, grader_version, rubric_version)` (frozen); `PrivateVerdict(content_hash, slot, field_name, correct, grader_id, grader_version, rubric_version)` (frozen, **no `item_id` field, no `raw_output` field**); `emit_public_verdicts(con, path: Path) -> int`; `emit_private_verdicts_by_hash(con, path: Path) -> int`; `emit_all(con, out_dir: Path, *, as_of: datetime) -> list[Path]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/publish/test_artifacts.py
import dataclasses
import json
from datetime import UTC, datetime

import pytest

from ground_truth.publish.artifacts import (
    PrivateVerdict,
    emit_private_verdicts_by_hash,
    emit_public_verdicts,
)
from ground_truth.store.db import connect, migrate


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def seed(con, item_id, split, secret_value, content_hash):
    now = datetime.now(UTC)
    con.execute("INSERT INTO items VALUES (?,?,'v1','synthetic',?,?)",
                [item_id, split, content_hash, now])
    con.execute("INSERT INTO item_fields VALUES (?,'contract_sum','money',?,NULL,'0.01')",
                [item_id, secret_value])
    con.execute(
        "INSERT INTO runs VALUES (?,?,NULL,'slot-a','ref','prov',false,'s1','sha','h')",
        [f"r-{item_id}", now],
    )
    con.execute("INSERT INTO outputs VALUES (?,?,?,1,?,'call','prov',NULL,10,'ph',?)",
                [f"o-{item_id}", f"r-{item_id}", item_id,
                 json.dumps({"contract_sum": secret_value}), now])
    con.execute(
        "INSERT INTO verdicts VALUES (?,?,'contract_sum','exact','1','v1',true,'ok',?)",
        [f"v-{item_id}", f"o-{item_id}", now],
    )


def test_private_verdict_type_carries_no_item_id_and_no_output():
    names = {f.name for f in dataclasses.fields(PrivateVerdict)}
    assert "item_id" not in names and "raw_output" not in names


def test_public_verdicts_include_item_ids(con, tmp_path):
    seed(con, "pub1", "public", "111.11", "hash-pub")
    path = tmp_path / "verdicts_public.jsonl"
    assert emit_public_verdicts(con, path) == 1
    assert "pub1" in path.read_text(encoding="utf-8")


def test_private_verdicts_are_keyed_by_hash_only(con, tmp_path):
    seed(con, "priv1", "private", "999.99", "hash-priv")
    path = tmp_path / "verdicts_private.jsonl"
    assert emit_private_verdicts_by_hash(con, path) == 1
    body = path.read_text(encoding="utf-8")
    assert "hash-priv" in body
    assert "priv1" not in body, "private item ids must never be published"
    assert "999.99" not in body, "private labels must never be published"


def test_public_and_private_emitters_do_not_cross_contaminate(con, tmp_path):
    seed(con, "pub1", "public", "111.11", "hash-pub")
    seed(con, "priv1", "private", "999.99", "hash-priv")
    pub, priv = tmp_path / "pub.jsonl", tmp_path / "priv.jsonl"
    emit_public_verdicts(con, pub)
    emit_private_verdicts_by_hash(con, priv)
    assert "priv1" not in pub.read_text(encoding="utf-8")
    assert "pub1" not in priv.read_text(encoding="utf-8")


def test_output_is_byte_stable(con, tmp_path):
    seed(con, "pub1", "public", "111.11", "hash-pub")
    path = tmp_path / "v.jsonl"
    emit_public_verdicts(con, path)
    first = path.read_text(encoding="utf-8")
    emit_public_verdicts(con, path)
    assert path.read_text(encoding="utf-8") == first


def test_every_line_is_valid_json(con, tmp_path):
    seed(con, "pub1", "public", "111.11", "hash-pub")
    path = tmp_path / "v.jsonl"
    emit_public_verdicts(con, path)
    for line in path.read_text(encoding="utf-8").splitlines():
        json.loads(line)


def test_empty_split_writes_an_empty_file_not_a_crash(con, tmp_path):
    path = tmp_path / "v.jsonl"
    assert emit_private_verdicts_by_hash(con, path) == 0
    assert path.read_text(encoding="utf-8") == ""
```

`test_private_verdict_type_carries_no_item_id_and_no_output` is a structural guarantee: the type cannot leak what it has no field for.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/publish/test_artifacts.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/publish/artifacts.py`**

`emit_public_verdicts` joins `verdicts` → `outputs` → `runs` → `items` filtered to `split='public'`, writing one JSON object per line sorted by `(item_id, slot, field_name, grader_id)` for byte stability.

`emit_private_verdicts_by_hash` does the same for `split='private'` but selects `items.content_hash` **instead of** `item_id`, and never touches `outputs.raw_output` or `item_fields.expected_value` — **the SQL does not select those columns at all.** The safest way not to publish something is not to read it.

`emit_all` writes `leaderboard.json`, `verdicts_public.jsonl`, `verdicts_private_by_hash.jsonl`, `manifest_private.json`, `calibration.json`, `judge_agreement.json`, `regression.json` and `triage.html` into `out_dir`, stamping each with the supplied `as_of` rather than `datetime.now` — otherwise reproduction is impossible by construction.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/publish/test_artifacts.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/publish/ tests/publish/
git commit -m "feat: publication artifacts with private verdicts keyed by hash only"
```

---

### Task 41: Contamination tests against the real emitted artifacts

**Files:**
- Create: `tests/test_contamination.py`

**Interfaces:**
- Consumes: `publish.artifacts.emit_all`, `store.db`.
- Produces: no new symbols. Produces the guarantee the methodology page claims.

- [ ] **Step 1: Write the test**

```python
# tests/test_contamination.py
import json
import subprocess
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ground_truth.publish.artifacts import emit_all
from ground_truth.store.db import connect

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "results.duckdb"
AS_OF = datetime(2026, 10, 15, tzinfo=UTC)


@pytest.fixture()
def emitted(tmp_path):
    if not DB.exists():
        pytest.skip("run the sweep first")
    con = connect(DB)
    paths = emit_all(con, tmp_path, as_of=AS_OF)
    yield con, paths
    con.close()


def test_private_item_ids_never_appear_in_published_output(emitted):
    con, paths = emitted
    ids = {r[0] for r in con.execute("SELECT item_id FROM items WHERE split='private'").fetchall()}
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        leaked = sorted(i for i in ids if i in blob)
        assert leaked == [], f"{path.name} leaks private item ids: {leaked[:5]}"


def test_private_labels_never_appear_in_published_output(emitted):
    con, paths = emitted
    values = {
        r[0]
        for r in con.execute(
            "SELECT f.expected_value FROM item_fields f JOIN items i ON i.item_id = f.item_id "
            "WHERE i.split='private'"
        ).fetchall()
        if len(r[0]) > 6
    }
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        leaked = sorted(v for v in values if v in blob)
        assert leaked == [], f"{path.name} leaks private labels: {leaked[:5]}"


def test_private_model_outputs_never_appear_in_published_output(emitted):
    con, paths = emitted
    outputs = {
        r[0]
        for r in con.execute(
            "SELECT o.raw_output FROM outputs o JOIN items i ON i.item_id = o.item_id "
            "WHERE i.split='private'"
        ).fetchall()
    }
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        for out in outputs:
            assert out not in blob, f"{path.name} leaks a private model output"


def test_published_hashes_match_the_manifest(emitted):
    con, paths = emitted
    manifest = next(p for p in paths if p.name == "manifest_private.json")
    published = set(json.loads(manifest.read_text(encoding="utf-8"))["item_hashes"])
    actual = {
        r[0] for r in con.execute("SELECT content_hash FROM items WHERE split='private'").fetchall()
    }
    assert published == actual


def test_private_corpus_not_tracked_by_git():
    out = subprocess.run(["git", "ls-files", "golden/corpus/private/"], cwd=REPO,
                         capture_output=True, text=True, check=True)
    tracked = [p for p in out.stdout.splitlines() if p.strip() and not p.endswith(".gitkeep")]
    assert tracked == []


def test_private_seed_not_tracked_by_git():
    out = subprocess.run(["git", "ls-files", ".env"], cwd=REPO,
                         capture_output=True, text=True, check=True)
    assert out.stdout.strip() == ""
```

These walk the **real emitted files**, not mocks. That distinction is what separates a test from a reassurance.

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_contamination.py -v`
Expected: PASS, 6 passed.

- [ ] **Step 3: Prove the test catches a real leak**

Temporarily change `emit_private_verdicts_by_hash` to also select `items.item_id`, re-run `test_private_item_ids_never_appear_in_published_output`, and confirm it FAILS naming the leaked ids. Revert. **A contamination test you have never watched fail is a claim, not a control.**

- [ ] **Step 4: Commit**

```bash
git add tests/test_contamination.py
git commit -m "test: contamination guarantees verified against real emitted artifacts"
```

---

### Task 42: `publish/leaderboard.py` and `publish/methodology.py`

**Files:**
- Create: `ground_truth/publish/leaderboard.py`
- Create: `ground_truth/publish/methodology.py`
- Modify: `docs/methodology.md`
- Create: `CHANGELOG.md`
- Test: `tests/publish/test_leaderboard.py`

**Interfaces:**
- Consumes: `matrix.build.{LeaderboardRow, distinguishability_statements}`, `graders.judge.agreement.AgreementReport`, `regression.fingerprint.SlotFingerprint`.
- Produces: `leaderboard_payload(rows, statements, agreements, fingerprints, *, as_of: datetime, version: str) -> dict`; `write_leaderboard(payload: dict, path: Path) -> None`; `required_terms() -> set[str]`; `assert_methodology_defines_every_term(path: Path) -> None`.

- [ ] **Step 1: Write the failing test**

```python
# tests/publish/test_leaderboard.py
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ground_truth.matrix.build import LeaderboardRow, distinguishability_statements
from ground_truth.matrix.cost import cost_per_1k_items
from ground_truth.matrix.latency import summarise_latency
from ground_truth.providers import SlotSpec
from ground_truth.publish.leaderboard import (
    assert_methodology_defines_every_term,
    leaderboard_payload,
    required_terms,
)
from ground_truth.stats.bootstrap import Interval

METHODOLOGY = Path(__file__).resolve().parents[2] / "docs" / "methodology.md"
AS_OF = datetime(2026, 10, 15, tzinfo=UTC)


def spec(slot):
    return SlotSpec(slot=slot, family="fam", provider="prov", model_ref="ref",
                    trains_on_data=False, commercial_use=True, exposes_fingerprint=False,
                    list_price_in_per_1m=Decimal("0.10"), list_price_out_per_1m=Decimal("0.40"),
                    pricing_url="https://example.invalid/p", retrieved_at=AS_OF.date())


def row(slot, low, point, high):
    return LeaderboardRow(
        slot=slot, accuracy=Interval(point=point, low=low, high=high, n=180, method="cluster-BCa"),
        cost=cost_per_1k_items(spec(slot), 2000, 500),
        latency=summarise_latency([100, 200, 300]), per_field={})


def payload():
    rows = [row("slot-a", 0.89, 0.92, 0.95), row("slot-b", 0.90, 0.93, 0.96)]
    return leaderboard_payload(rows, distinguishability_statements(rows), [], [],
                               as_of=AS_OF, version="2026.10.15")


def test_every_row_carries_its_n_and_interval():
    for entry in payload()["rows"]:
        assert set(entry["accuracy"]) >= {"point", "low", "high", "n", "method"}
        assert entry["accuracy"]["n"] == 180


def test_distinguishability_statements_are_included():
    assert any("not distinguishable" in s for s in payload()["distinguishability"])


def test_cost_carries_the_list_price_caveat():
    for entry in payload()["rows"]:
        assert "list price" in entry["cost"]["caveat"].lower()


def test_latency_has_no_rank_key():
    for entry in payload()["rows"]:
        assert "rank" not in entry["latency"]


def test_payload_is_versioned_and_dated():
    body = payload()
    assert body["version"] == "2026.10.15" and body["as_of"] == AS_OF.isoformat()


def test_payload_links_the_methodology():
    assert payload()["methodology_url"]


def test_methodology_defines_every_published_term():
    assert_methodology_defines_every_term(METHODOLOGY)


def test_required_terms_covers_the_published_vocabulary():
    assert {"accurate", "correct", "field", "item", "replicate", "split"} <= required_terms()
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/publish/test_leaderboard.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/publish/leaderboard.py`**

`leaderboard_payload` returns `version`, `as_of` (from the parameter, never `datetime.now`), `methodology_url`, `rows`, `distinguishability`, `judge_agreement`, `fingerprints`, and `mde`. Each row's `accuracy` always serialises all five `Interval` fields — **there is no code path that emits a bare point estimate**, which is how "no claim without its sample" becomes structural rather than editorial.

`required_terms` returns the published vocabulary the methodology must define: `accurate`, `correct`, `field`, `item`, `replicate`, `split`, `public split`, `private split`, `verdict`, `grader`, `judge`, `interval`, `list price`, `not distinguishable`, `minimum detectable effect`, `look`, `rubric`.

`assert_methodology_defines_every_term` reads the methodology, checks each term appears as a definition (a line beginning `**<term>**` or `- **<term>**`), and raises `AssertionError` naming every missing term. That is DoD item 11, made executable.

- [ ] **Step 4: Write the definitions section of `docs/methodology.md`**

A `## Definitions` section covering every term from `required_terms()`. Be specific exactly where the incumbents are vague: *accurate* means the deterministic grader for that field type returned `correct=True` under rubric version X; *correct* is defined per field type by the rubric, not by judgement; *item* is one synthetic pay application; *replicate* is one of five independent calls for the same (item, slot).

- [ ] **Step 5: Write `CHANGELOG.md`**

Keep-a-Changelog format, first entry this release. Record the release rule at the top: **numbers are never silently edited; a corrected number appears as a new dated entry with the superseded value shown struck through.**

- [ ] **Step 6: Write `ground_truth/publish/methodology.py`**

Renders `docs/methodology.md` to HTML for the site and — importantly — injects the **live** figures rather than hand-copied ones: current `n`, the MDE sentence, the intra-rater disagreement rate, the judge agreement statements, the fingerprint statements. A methodology page whose numbers are typed by hand drifts away from the results it describes, usually silently.

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/publish/test_leaderboard.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 8: Commit**

```bash
git add ground_truth/publish/ docs/methodology.md CHANGELOG.md tests/publish/
git commit -m "feat: versioned leaderboard payload and methodology with enforced definitions"
```

---

### Task 43: The reproducibility test

This is DoD item 10 and the single most load-bearing test in the repository.

**Files:**
- Create: `tests/test_reproducibility.py`
- Create: `scripts/reproduce.py`
- Modify: `README.md`

**Interfaces:**
- Consumes: `publish.artifacts.emit_all`, `store.db`.
- Produces: `scripts/reproduce.py`, runnable by a stranger with no repository and no `ground_truth` package.

- [ ] **Step 1: Write the test**

```python
# tests/test_reproducibility.py
import filecmp
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ground_truth.publish.artifacts import emit_all
from ground_truth.store.db import connect

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "results.duckdb"
PUBLISHED = REPO / "artifacts"
AS_OF = datetime(2026, 10, 15, tzinfo=UTC)


@pytest.fixture()
def con():
    if not DB.exists() or not PUBLISHED.exists():
        pytest.skip("run the sweep and publish first")
    c = connect(DB)
    yield c
    c.close()


def test_published_numbers_regenerate(con, tmp_path):
    mismatched = []
    for path in emit_all(con, tmp_path, as_of=AS_OF):
        published = PUBLISHED / path.name
        assert published.exists(), f"{path.name} was regenerated but is not published"
        if not filecmp.cmp(path, published, shallow=False):
            mismatched.append(path.name)
    assert mismatched == [], f"published artifacts do not regenerate: {mismatched}"


def test_regeneration_is_stable_across_two_runs(con, tmp_path):
    first = sorted(emit_all(con, tmp_path / "a", as_of=AS_OF))
    second = sorted(emit_all(con, tmp_path / "b", as_of=AS_OF))
    for a, b in zip(first, second, strict=True):
        assert filecmp.cmp(a, b, shallow=False), f"{a.name} is not deterministic"


def test_headline_accuracy_recomputes_from_published_verdicts_alone():
    """A stranger holding only the published verdict files must reach the published number."""
    leaderboard = json.loads((PUBLISHED / "leaderboard.json").read_text(encoding="utf-8"))
    verdicts = [
        json.loads(line)
        for line in (PUBLISHED / "verdicts_private_by_hash.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    for entry in leaderboard["rows"]:
        rows = [v for v in verdicts if v["slot"] == entry["slot"]]
        by_item: dict[str, list[bool]] = {}
        for v in rows:
            by_item.setdefault(v["content_hash"], []).append(v["correct"])
        recomputed = sum(sum(c) / len(c) for c in by_item.values()) / len(by_item)
        assert recomputed == pytest.approx(entry["accuracy"]["point"], abs=1e-9), (
            f"{entry['slot']}: published {entry['accuracy']['point']}, recomputed {recomputed}"
        )
```

`test_headline_accuracy_recomputes_from_published_verdicts_alone` is the one a sceptic will actually run. It proves the private-split headline is reconstructible from published per-item verdicts keyed by hash, **without any private item ever being revealed** — the whole contamination design, verified end to end.

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/test_reproducibility.py -v`
Expected: PASS, 3 passed.

If the third test fails, the aggregation in `matrix/build.py` and the aggregation implied by the published verdicts have diverged. **Fix the publication, not the test** — a headline number a stranger cannot recompute is precisely the failure this project sells against.

- [ ] **Step 3: Write `scripts/reproduce.py`**

A standalone script depending only on the standard library, taking a directory of published artifacts and printing the recomputed headline table beside the published one with a diff and a non-zero exit code on any mismatch. **It must not import `ground_truth`** — if reproduction requires our package, it is not reproduction.

- [ ] **Step 4: Document reproduction in `README.md`**

A **Reproduce these numbers** section within the first screen: download the artifacts, run `python scripts/reproduce.py artifacts/`, expect zero differences. State plainly that the private split's items are withheld, that its hashes are published so their existence at a date is provable, and that headline numbers are nonetheless recomputable from published per-item verdicts.

- [ ] **Step 5: Verify reproduction the way a stranger would**

```bash
cd $(mktemp -d) && cp -r "$OLDPWD/artifacts" . && cp "$OLDPWD/scripts/reproduce.py" .
python reproduce.py artifacts/
```

Expected: zero differences, in a directory with no repository and no `ground_truth` installed.

- [ ] **Step 6: Commit**

```bash
git add tests/test_reproducibility.py scripts/reproduce.py README.md
git commit -m "test: published numbers regenerate from published data alone"
```

---

### Task 44: Right of reply, correction policy, and the disclosure surface

**Files:**
- Create: `.github/ISSUE_TEMPLATE/right-of-reply.yml`
- Create: `docs/corrections.md`
- Modify: `SECURITY.md`, `README.md`, `CHANGELOG.md`
- Test: `tests/test_publication_policy.py`

**Interfaces:**
- Consumes: nothing.
- Produces: no importable symbols. Produces the published process spec §13.3 commits to.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_publication_policy.py
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CORRECTIONS = REPO / "docs" / "corrections.md"
TEMPLATE = REPO / ".github" / "ISSUE_TEMPLATE" / "right-of-reply.yml"
README = REPO / "README.md"
CHANGELOG = REPO / "CHANGELOG.md"
METHODOLOGY = REPO / "docs" / "methodology.md"


def test_right_of_reply_template_exists_and_is_labelled():
    assert "right-of-reply" in TEMPLATE.read_text(encoding="utf-8")


def test_response_windows_are_stated():
    body = CORRECTIONS.read_text(encoding="utf-8")
    assert "5 business days" in body and "15 business days" in body


def test_advance_notice_rule_is_stated():
    body = CORRECTIONS.read_text(encoding="utf-8")
    assert "10 business days" in body
    assert "regression" in body.lower() or "drift" in body.lower()


def test_three_outcomes_are_named():
    body = CORRECTIONS.read_text(encoding="utf-8").lower()
    for outcome in ("correction", "clarification", "no change"):
        assert outcome in body


def test_no_silent_edit_rule_is_stated():
    assert "never silently" in CHANGELOG.read_text(encoding="utf-8").lower()


def test_rerun_offer_is_stated():
    body = CORRECTIONS.read_text(encoding="utf-8").lower()
    assert "re-run" in body and "side by side" in body


def test_no_characterisation_of_vendor_honesty():
    """Measured claims only. Scan published prose for accusatory vocabulary."""
    banned = ("dishonest", "misleading", "fabricated", "lying", "deceptive", "fraudulent")
    for path in (README, CORRECTIONS, METHODOLOGY):
        lowered = path.read_text(encoding="utf-8").lower()
        for word in banned:
            assert word not in lowered, f"{path.name} characterises a vendor: {word!r}"


def test_readme_carries_a_scope_statement_early():
    head = " ".join(README.read_text(encoding="utf-8").split()[:200]).lower()
    assert "pay application" in head or "invoice" in head
    assert "field extraction" in head
```

`test_no_characterisation_of_vendor_honesty` is worth its awkwardness. This project sells into a market with fabricated numbers; the urge to say so about a named vendor will be real, and acting on it converts your best asset into a liability (`00` B9). Note that this constrains only *published prose about vendors* — the internal design documents discuss the market's failures freely, and should.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_publication_policy.py -v`
Expected: FAIL — `docs/corrections.md` does not exist.

- [ ] **Step 3: Write `docs/corrections.md`**

State concretely: the two channels (a GitHub issue on the `right-of-reply` template, or `corrections@<domain>` for providers preferring private first) and that the outcome publishes either way. The windows — **acknowledge within 5 business days, publish a resolution within 15**. The notice rule — **no advance notice for routine leaderboard scores; 10 business days' notice for any regression or drift finding naming a provider**, because that reads as a defect claim rather than a measurement. The three outcomes — correction, clarification, no change — each published with reasoning. And the standing offer: if a provider names a configuration error, we re-run under their stated configuration and publish both results side by side.

- [ ] **Step 4: Write `.github/ISSUE_TEMPLATE/right-of-reply.yml`**

Fields: the disputed result (version and date), the specific claim, what the provider believes is wrong, and optionally the configuration they would like us to re-run under. Auto-label `right-of-reply`.

- [ ] **Step 5: Add the no-silent-edit rule to `CHANGELOG.md` and the scope statement to `README.md`**

The README's first 200 words must say what this measures — pay-application and invoice field extraction — and what it does not. An early scope statement is the cheapest defence against being read as a general benchmark.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_publication_policy.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 7: Commit**

```bash
git add .github/ISSUE_TEMPLATE/ docs/corrections.md SECURITY.md README.md CHANGELOG.md tests/test_publication_policy.py
git commit -m "docs: right-of-reply process, correction policy, and publication guardrails"
```

---

### Task 45: Web scaffold and the Leaderboard screen

**Files:**
- Create: `web/package.json`, `web/next.config.ts`, `web/tsconfig.json`, `web/playwright.config.ts`
- Create: `web/app/layout.tsx`, `web/app/globals.css`, `web/app/page.tsx`
- Create: `web/components/IntervalBar.tsx`, `web/lib/artifacts.ts`
- Test: `web/e2e/leaderboard.spec.ts`

**Interfaces:**
- Consumes: `artifacts/leaderboard.json` at build time.
- Produces: `loadLeaderboard(): LeaderboardPayload` from `web/lib/artifacts.ts`; `<IntervalBar low high point n />`.

- [ ] **Step 1: Scaffold with static export**

```bash
cd web && npx create-next-app@latest . --typescript --app --no-src-dir --eslint
```

Set `output: 'export'` in `next.config.ts`. Add `bok-ui` if it is published by now; if not, create `web/components/Claim.tsx` as a local shim carrying a `ponytail:` comment naming `bok-ui` as the upgrade path. The JSON artifact layer is unaffected either way.

- [ ] **Step 2: Write the failing E2E test**

```typescript
// web/e2e/leaderboard.spec.ts
import { expect, test } from '@playwright/test';

test('every accuracy figure is rendered as an interval, not a bare number', async ({ page }) => {
  await page.goto('/');
  const rows = page.getByTestId('leaderboard-row');
  const count = await rows.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    await expect(rows.nth(i).getByTestId('accuracy-interval')).toBeVisible();
    await expect(rows.nth(i).getByTestId('accuracy-n')).toContainText(/n=\d+/);
  }
});

test('overlapping models are described in words', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('distinguishability')).toContainText(
    /not distinguishable at this sample size|All models are distinguishable/,
  );
});

test('the methodology link sits beside the title, not in the footer', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByRole('banner').getByRole('link', { name: /methodology/i })).toBeVisible();
});

test('the cost column states that it is list price', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByTestId('cost-caveat')).toContainText(/list price/i);
});

test('latency is not sortable', async ({ page }) => {
  await page.goto('/');
  await expect(
    page.getByRole('columnheader', { name: /latency/i }).getByRole('button'),
  ).toHaveCount(0);
});

test('the page is operable by keyboard alone', async ({ page }) => {
  await page.goto('/');
  await page.keyboard.press('Tab');
  await expect(page.locator(':focus')).toBeVisible();
});
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `cd web && npx playwright test e2e/leaderboard.spec.ts`
Expected: FAIL — no leaderboard renders yet.

- [ ] **Step 4: Build the Leaderboard screen**

`web/lib/artifacts.ts` imports `artifacts/leaderboard.json` at build time — a static import, no fetch, because both the static export and the eventual CSP forbid runtime data loading.

`<IntervalBar>` renders the interval **as an interval**: a horizontal rule spanning `[low, high]` with a mark at `point`, plus a text label `data-testid="accuracy-interval"` reading `0.920 [0.905, 0.935]` and a sibling `data-testid="accuracy-n"` reading `n=180`. Tabular numerals throughout. Light-first; slate-blue `oklch(0.52 0.10 232)` for measurement states only.

The distinguishability statements render as prose above the table with `data-testid="distinguishability"`. When no pair overlaps, render *"All models are distinguishable at this sample size"* — an empty element would imply nothing was checked.

The latency column header is plain text with no sort control, carrying the free-tier caveat in a tooltip and, in print, as a footnote.

- [ ] **Step 5: Run the test to verify it passes**

Run: `cd web && npx playwright test e2e/leaderboard.spec.ts`
Expected: PASS, 6 passed.

- [ ] **Step 6: Commit**

```bash
git add web/
git commit -m "feat: leaderboard screen rendering intervals as intervals"
```

---

### Task 46: Item explorer and Judge agreement screens

**Files:**
- Create: `web/app/items/page.tsx`, `web/app/judge/page.tsx`
- Create: `web/components/ConfusionMatrix.tsx`
- Test: `web/e2e/items.spec.ts`, `web/e2e/judge.spec.ts`

**Interfaces:**
- Consumes: `artifacts/verdicts_public.jsonl`, `artifacts/judge_agreement.json`.
- Produces: `<ConfusionMatrix matrix={...} />`.

- [ ] **Step 1: Write the failing tests**

```typescript
// web/e2e/items.spec.ts
import { expect, test } from '@playwright/test';

test('the explorer states that it shows the public split only', async ({ page }) => {
  await page.goto('/items');
  await expect(page.getByTestId('split-notice')).toContainText(/public split/i);
  await expect(page.getByTestId('split-notice')).toContainText(/withheld/i);
});

test('items can be filtered by failure mode', async ({ page }) => {
  await page.goto('/items');
  const before = await page.getByTestId('item-row').count();
  await page.getByLabel(/failure mode/i).selectOption({ index: 1 });
  await expect.poll(() => page.getByTestId('item-row').count()).toBeLessThan(before);
});

test('an empty filter result renders a denominator, not a celebration', async ({ page }) => {
  // Contract section 6.3: <EmptyState scope={{ measured, skipped, reason }} />
  await page.goto('/items');
  await page.getByLabel(/search/i).fill('zzzz-no-such-item');
  const empty = page.getByTestId('empty-state');
  await expect(empty).toContainText(/no items match/i);
  await expect(empty).toContainText(/of 120/, {
    // "0 of 120 public items match" -- never a bare "no results", which reads as
    // "nothing is wrong" when it actually means "nothing was measured".
  });
});
```

```typescript
// web/e2e/judge.spec.ts
import { expect, test } from '@playwright/test';

test('rejected field types are shown, labelled rejected', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('agreement-table')).toContainText(/accepted|rejected/i);
});

test('every agreement figure carries its interval and n', async ({ page }) => {
  await page.goto('/judge');
  const cells = page.getByTestId('alpha-value');
  const count = await cells.count();
  expect(count).toBeGreaterThan(0);
  for (let i = 0; i < count; i++) {
    await expect(cells.nth(i)).toContainText(/\[.*,.*\]/);
    await expect(cells.nth(i)).toContainText(/n=\d+/);
  }
});

test('the pre-registered threshold is stated on the page', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('threshold-notice')).toContainText('0.667');
  await expect(page.getByTestId('threshold-notice')).toContainText(/pre-registered/i);
});

test('order and length effects are published', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('order-effect')).toBeVisible();
  await expect(page.getByTestId('length-effect')).toBeVisible();
});

test('the confusion matrix is rendered', async ({ page }) => {
  await page.goto('/judge');
  await expect(page.getByTestId('confusion-matrix')).toBeVisible();
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx playwright test e2e/items.spec.ts e2e/judge.spec.ts`
Expected: FAIL — routes do not exist.

- [ ] **Step 3: Build both screens**

The item explorer renders the public split with a prominent notice: *"This explorer shows the 120-item public split. The 180-item private split is withheld; its hashes are published and headline numbers are computed against it."* Filter by failure mode (derived from `verdicts.reason` and the item's `injected_error`) plus free-text search. The empty state names what was searched for rather than showing a blank table.

The judge screen renders one row per field type the judge touched — **including rejected ones, labelled rejected** — each with α, its interval, `n`, and the accept/reject statement verbatim from `AgreementReport.statement`. The threshold notice states `0.667` and the words *pre-registered*. Order-effect and length-effect figures render as small charts that survive greyscale printing.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx playwright test e2e/items.spec.ts e2e/judge.spec.ts`
Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "feat: item explorer and judge agreement screens including rejected field types"
```

---

### Task 47: Calibration, Regression watch, and Triage report screens

**Files:**
- Create: `web/app/calibration/page.tsx`, `web/app/regression/page.tsx`, `web/app/triage/page.tsx`
- Create: `web/components/ReliabilityDiagram.tsx`
- Test: `web/e2e/calibration.spec.ts`, `web/e2e/regression.spec.ts`, `web/e2e/triage.spec.ts`

**Interfaces:**
- Consumes: `artifacts/calibration.json`, `artifacts/regression.json`, `artifacts/triage.html`.
- Produces: `<ReliabilityDiagram curve={...} />`.

- [ ] **Step 1: Write the failing tests**

```typescript
// web/e2e/calibration.spec.ts
import { expect, test } from '@playwright/test';

test('each curve states its sample size and both splits', async ({ page }) => {
  await page.goto('/calibration');
  await expect(page.getByTestId('source-split')).toContainText(/public-fit\/private-validate/);
  await expect(page.getByTestId('curve-n').first()).toContainText(/n=\d+/);
});

test('the confidence signal is named on the page', async ({ page }) => {
  await page.goto('/calibration');
  await expect(page.getByTestId('signal-notice')).toContainText(/replicate agreement/i);
});

test('threshold recommendations are shown with their target', async ({ page }) => {
  await page.goto('/calibration');
  await expect(page.getByTestId('threshold-table')).toContainText(/0\.9/);
});

test('ConfidenceMeter receives a Calibration object, never a bare float', async ({ page }) => {
  // Contract section 6.3. A float cannot carry state/basis/curve_id/n, so a meter fed one
  // has no way to render "uncalibrated" -- which is 00 B10's entire point.
  await page.goto('/calibration');
  const meter = page.getByTestId('confidence-meter').first();
  await expect(meter).toHaveAttribute('data-calibration-state', /CALIBRATED|UNCALIBRATED/);
  await expect(meter).toContainText(/n=\d+/);
});

test('an uncalibrated field type renders greyed and labelled, not as a number', async ({ page }) => {
  await page.goto('/calibration');
  const uncalibrated = page.getByTestId('confidence-meter').filter({
    has: page.locator('[data-calibration-state="UNCALIBRATED"]'),
  });
  if ((await uncalibrated.count()) > 0) {
    await expect(uncalibrated.first()).toContainText(/uncalibrated/i);
  }
});
```

```typescript
// web/e2e/regression.spec.ts
import { expect, test } from '@playwright/test';

test('every alert states the tests used', async ({ page }) => {
  await page.goto('/regression');
  const alerts = page.getByTestId('alert');
  const count = await alerts.count();
  for (let i = 0; i < count; i++) {
    await expect(alerts.nth(i)).toContainText(/O'Brien-Fleming/);
    await expect(alerts.nth(i)).toContainText(/Benjamini-Hochberg/);
  }
});

test('no alert is rendered as a bare arrow or bare percentage', async ({ page }) => {
  await page.goto('/regression');
  const alerts = page.getByTestId('alert');
  const count = await alerts.count();
  for (let i = 0; i < count; i++) {
    const text = (await alerts.nth(i).textContent()) ?? '';
    expect(text.replace(/[\s↑↓▲▼]/g, '').length).toBeGreaterThan(60);
  }
});

test('a null result states what was not detectable', async ({ page }) => {
  await page.goto('/regression');
  await expect(page.getByTestId('mde-notice')).toContainText(/not that none exists/i);
});

test('fingerprint status is published including where it is absent', async ({ page }) => {
  await page.goto('/regression');
  await expect(page.getByTestId('fingerprints')).toContainText(
    /does not expose|reported a single fingerprint/,
  );
});
```

```typescript
// web/e2e/triage.spec.ts
import { expect, test } from '@playwright/test';

test('the triage report renders under print media', async ({ page }) => {
  await page.goto('/triage');
  await page.emulateMedia({ media: 'print' });
  await expect(page.getByTestId('report')).toBeVisible();
});

test('every recommendation shows its calculation', async ({ page }) => {
  await page.goto('/triage');
  await expect(page.getByTestId('calculation').first()).toBeVisible();
});

test('the flip point is stated for every bounded intent', async ({ page }) => {
  await page.goto('/triage');
  await expect(page.getByTestId('flip-point').first()).toContainText(/costs more than/);
});
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `cd web && npx playwright test e2e/calibration.spec.ts e2e/regression.spec.ts e2e/triage.spec.ts`
Expected: FAIL — routes do not exist.

- [ ] **Step 3: Build all three screens**

The calibration screen renders one reliability diagram per field type with the fitted curve, the diagonal, the sample size, and the threshold recommendation table. It names the confidence signal (replicate agreement) and the fit/validate split design, and shows the divergence figure with one line explaining what a growing value would mean.

The regression screen renders each alert as its **statement** — the full sentence from `Alert.statement`, never an arrow or a bare delta. `test_no_alert_is_rendered_as_a_bare_arrow` enforces a minimum length as a crude proxy for *this is a sentence, not a glyph*, and that crudeness is deliberate. The fingerprint panel publishes every slot's status including `NOT_EXPOSED`.

The triage screen embeds the print-ready report with its calculation visible and its flip points stated.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `cd web && npx playwright test`
Expected: PASS, all specs.

- [ ] **Step 5: Commit**

```bash
git add web/
git commit -m "feat: calibration, regression watch, and triage report screens"
```

---

### Task 48: Accessibility, keyboard paths, print styles

**Files:**
- Create: `web/e2e/a11y.spec.ts`, `web/app/print.css`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: `@axe-core/playwright`.
- Produces: an accessibility gate in CI.

- [ ] **Step 1: Write the failing test**

```typescript
// web/e2e/a11y.spec.ts
import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

const ROUTES = ['/', '/items', '/judge', '/calibration', '/regression', '/triage'];

for (const route of ROUTES) {
  test(`${route} has no serious or critical accessibility violations`, async ({ page }) => {
    await page.goto(route);
    const results = await new AxeBuilder({ page })
      .withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa', 'wcag22aa'])
      .analyze();
    const blocking = results.violations.filter((v) =>
      ['serious', 'critical'].includes(v.impact ?? ''),
    );
    expect(blocking, JSON.stringify(blocking, null, 2)).toHaveLength(0);
  });

  test(`${route} keeps a visible focus ring throughout a tab sweep`, async ({ page }) => {
    await page.goto(route);
    const reached = new Set<string>();
    for (let i = 0; i < 60; i++) {
      await page.keyboard.press('Tab');
      const focused = await page.evaluate(() => {
        const el = document.activeElement as HTMLElement | null;
        if (!el || el === document.body) return null;
        const style = getComputedStyle(el);
        return {
          outline: style.outlineStyle,
          shadow: style.boxShadow,
          id: el.id || el.textContent?.slice(0, 20) || el.tagName,
        };
      });
      if (!focused) continue;
      expect(
        focused.outline !== 'none' || focused.shadow !== 'none',
        `${route}: focused element has no visible focus indicator`,
      ).toBe(true);
      reached.add(String(focused.id));
    }
    expect(reached.size).toBeGreaterThan(1);
  });

  test(`${route} does not scroll horizontally at 375px`, async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto(route);
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1,
    );
    expect(overflow).toBe(false);
  });
}

test('status is never encoded in colour alone', async ({ page }) => {
  await page.goto('/regression');
  const badges = page.getByTestId('status-badge');
  const count = await badges.count();
  for (let i = 0; i < count; i++) {
    await expect(badges.nth(i)).not.toHaveText('');
  }
});
```

- [ ] **Step 2: Run the tests**

Run: `cd web && npx playwright test e2e/a11y.spec.ts`
Expected: FAIL initially. Fix every serious and critical violation. **Do not narrow the tag set to make it pass** — two of the four target markets are regulated for accessibility, and a colour-only encoding is an own goal in a sales conversation (`00` §5.2).

- [ ] **Step 3: Write `web/app/print.css`**

Every report view prints. Force page breaks between intent sections, drop navigation chrome, render link URLs after link text, keep tabular numerals, and ensure charts survive greyscale — no encoding that depends on hue alone.

- [ ] **Step 4: Add the web gate to CI**

```yaml
  web:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with: { node-version: '22' }
      - run: npm ci --prefix web
      - run: npx --prefix web tsc --noEmit
      - run: npm run build --prefix web
      - run: npx --prefix web playwright install --with-deps chromium
      - run: npx --prefix web playwright test
```

- [ ] **Step 5: Verify a print rendering by eye**

Print `/` and `/triage` to PDF and read both. A number that reflows, or a chart that becomes ambiguous in greyscale, is a defect — not a nit. These documents get emailed to auditors.

- [ ] **Step 6: Commit**

```bash
git add web/ .github/workflows/ci.yml
git commit -m "feat: WCAG 2.2 AA gate, keyboard paths, and print stylesheets"
```

---

### Task 49: Deploy and the first published release

**Files:**
- Create: `.github/workflows/publish.yml`
- Modify: `CHANGELOG.md`

**Interfaces:**
- Consumes: everything.
- Produces: a deployed static site and a tagged, dated release.

- [ ] **Step 1: Write `.github/workflows/publish.yml`**

On a tag matching `v*`: run the full Python gate, regenerate artifacts with `--as-of` taken from the **tag date** (never `now`, or the reproducibility test cannot pass on a later re-run), run `tests/test_reproducibility.py` and `tests/test_contamination.py` as **blocking** steps, build the static export, deploy to GitHub Pages.

Those two test files gate the deploy. A release that cannot regenerate its own numbers, or that leaks a private item, must not reach the web.

- [ ] **Step 2: Cut the release**

```bash
uv run python -m ground_truth.publish.artifacts --out artifacts/ --as-of 2026-10-15T00:00:00Z
uv run pytest tests/test_reproducibility.py tests/test_contamination.py -v
git add artifacts/ CHANGELOG.md
git commit -m "chore: publish release 2026.10.15"
git tag -a v2026.10.15 -m "First published leaderboard"
git push origin main --tags
```

- [ ] **Step 3: Verify the deployed site by hand**

Open the Pages URL and check: the methodology link sits beside the title; every accuracy figure shows an interval and its `n`; the distinguishability statements are present and legible; the cost column says list price; the judge table shows rejected field types as rejected; the regression alerts are sentences, not glyphs.

- [ ] **Step 4: Verify reproduction from the deployed site**

Download the artifacts **from the deployed site**, not from your working tree, into a clean directory and run `python reproduce.py artifacts/`. Zero differences. This is the exact path a sceptic takes, so walk it yourself first.

- [ ] **Step 5: Fix and re-tag if needed**

If anything failed, fix it and cut a new dated release. **Never amend a published tag** — the no-silent-edit rule applies to your own releases first, and a buyer who notices you rewrote one has learned everything they need about the rest.

---

### Task 50: Definition-of-done verification

**Files:**
- Create: `docs/definition-of-done.md`
- Test: `tests/test_definition_of_done.py`

**Interfaces:**
- Consumes: the whole repository.
- Produces: a machine-checked statement that `04` §12's eleven items are met.

- [ ] **Step 1: Write the verification test**

```python
# tests/test_definition_of_done.py
import json
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
ARTIFACTS = REPO / "artifacts"
DOCS = REPO / "docs"


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO, capture_output=True, text=True,
                          check=True).stdout


@pytest.fixture(autouse=True)
def _require_release():
    if not ARTIFACTS.exists():
        pytest.skip("cut a release first")


def test_dod_1_golden_set_and_rubric_authored_before_labelling():
    rubric = _git("log", "--format=%ct", "-1", "--", "docs/rubric.md").strip()
    labels = _git("log", "--format=%ct", "--reverse", "--",
                  "golden/manifest_public.json").split()[0]
    assert rubric and labels
    assert int(rubric) < int(labels), "the rubric must be committed before the first labels"
    public = json.loads((REPO / "golden" / "manifest_public.json").read_text(encoding="utf-8"))
    private = json.loads((REPO / "golden" / "manifest_private.json").read_text(encoding="utf-8"))
    assert 200 <= public["count"] + private["count"] <= 500


def test_dod_2_splits_enforced_and_hashes_published():
    assert (REPO / "golden" / "manifest_private.json").exists()
    assert "contamination" in (DOCS / "methodology.md").read_text(encoding="utf-8").lower()
    tracked = [p for p in _git("ls-files", "golden/corpus/private/").splitlines()
               if p.strip() and not p.endswith(".gitkeep")]
    assert tracked == []


def test_dod_3_deterministic_graders_for_every_possible_field_type():
    from ground_truth.golden.rubric import loaded_rubric
    from ground_truth.golden.schema import FieldType

    rubric = loaded_rubric(DOCS / "rubric.md")
    judged = {ft for ft, rule in rubric.items() if rule.grader == "judge"}
    assert judged <= {FieldType.LINE_ITEM_DESCRIPTION}, (
        f"only free text may require a judge; these do too: {judged}"
    )


def test_dod_4_judge_agreement_published_including_weakness():
    body = json.loads((ARTIFACTS / "judge_agreement.json").read_text(encoding="utf-8"))
    assert body["entries"], "the judge agreement table must not be empty"
    for entry in body["entries"]:
        assert entry["status"] in {"accepted", "rejected"}
        assert "alpha_ci" in entry and "n_units" in entry


def test_dod_5_matrix_has_list_price_cost_and_caveated_latency():
    for row in json.loads((ARTIFACTS / "leaderboard.json").read_text(encoding="utf-8"))["rows"]:
        assert "list price" in row["cost"]["caveat"].lower()
        assert "free tier" in row["latency"]["caveat"].lower()
        assert "rank" not in row["latency"]


def test_dod_6_calibration_exported_for_ledger_sense():
    body = json.loads((ARTIFACTS / "calibration.json").read_text(encoding="utf-8"))
    assert body["curves"]
    for curve in body["curves"]:
        assert curve["threshold_recommendations"]
        assert curve["source_split"] == "public-fit/private-validate"


def test_dod_7_regression_watch_scheduled_and_alerts_state_their_test():
    workflow = (REPO / ".github" / "workflows" / "regression-watch.yml").read_text(encoding="utf-8")
    assert "schedule:" in workflow and "cron:" in workflow
    for alert in json.loads((ARTIFACTS / "regression.json").read_text(encoding="utf-8"))["alerts"]:
        assert "O'Brien-Fleming" in alert["statement"]


def test_dod_8_triage_produced_end_to_end_with_sensitivity():
    body = (ARTIFACTS / "triage.html").read_text(encoding="utf-8")
    assert "costs more than" in body and "n=" in body


def test_dod_9_public_leaderboard_ships_its_whole_evidence_chain():
    for name in ("leaderboard.json", "verdicts_public.jsonl",
                 "verdicts_private_by_hash.jsonl", "manifest_private.json"):
        assert (ARTIFACTS / name).exists(), f"missing published artifact: {name}"
    for name in ("methodology.md", "rubric.md", "corrections.md", "analysis-plan.md"):
        assert (DOCS / name).exists(), f"missing published document: {name}"
    assert (REPO / "CHANGELOG.md").exists()
    assert (REPO / ".github" / "ISSUE_TEMPLATE" / "right-of-reply.yml").exists()


def test_dod_10_reproducibility_test_runs_and_does_not_skip():
    result = subprocess.run(
        ["uv", "run", "pytest", "tests/test_reproducibility.py", "-v", "--no-header"],
        cwd=REPO, capture_output=True, text=True,
    )
    assert result.returncode == 0, result.stdout
    assert "skipped" not in result.stdout.lower(), (
        "the reproducibility test must actually run, not skip"
    )


def test_dod_11_methodology_defines_every_published_term():
    from ground_truth.publish.leaderboard import assert_methodology_defines_every_term

    assert_methodology_defines_every_term(DOCS / "methodology.md")
```

- [ ] **Step 2: Run the verification**

Run: `uv run pytest tests/test_definition_of_done.py -v`
Expected: PASS, 11 passed — one test per DoD item.

Any failure here is a genuine gap, not a test problem. Fix the gap.

- [ ] **Step 3: Write `docs/definition-of-done.md`**

The eleven items from `04` §12, each with the test that verifies it and the artifact that satisfies it. This is the page you show a buyer who asks whether the thing is actually finished.

- [ ] **Step 4: Run the complete gate one final time**

```bash
uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -v
cd web && npx tsc --noEmit && npm run build && npx playwright test
```

Expected: everything passes.

- [ ] **Step 5: Commit and tag**

```bash
git add docs/definition-of-done.md tests/test_definition_of_done.py
git commit -m "test: machine-checked verification of all eleven definition-of-done items"
git tag -a phase-3-published -m "Phase 3: regression watch, publication, web, DoD verified"
git push origin main --tags
```

---

### Task 51: Private-split rotation, and the cohort trap it creates

Spec §5.4 commits to rotating 20% of the private split at each published release. That first fires at release *two*, after week 26 — but the mechanism belongs here, because rotation introduces a statistical bug that must be closed in `regression/detect.py` before any second release exists.

**The bug:** rotate 20% of the private split between releases, then compare release N to release N+1, and 20% of the items differ. The measured difference is partly *cohort change*, not model change. Reported as drift, it is a false positive manufactured by your own contamination policy. Every cross-release comparison must therefore be restricted to items present in **both** cohorts, and the alert must state how many items that was.

**Files:**
- Create: `ground_truth/golden/rotate.py`
- Modify: `ground_truth/store/db.py` — add the `rotations` table and two `items` columns
- Modify: `ground_truth/regression/detect.py` — add the `cohort` and `cross_release` parameters
- Modify: `tests/store/test_db.py` — add `rotations` to `EXPECTED`
- Test: `tests/golden/test_rotate.py`

**Interfaces:**
- Consumes: `golden.generate.generate`, `golden.manifest.write_manifest`, `store.db`.
- Produces: `RotationRecord(release: str, rotated_at: datetime, retired_hashes: list[str], added_hashes: list[str], seed_ref: str)` (frozen); `rotate_private_split(con, *, fraction: float, new_seed: int, seed_ref: str, release: str, rubric_version: str) -> RotationRecord`; `cohort_intersection(con, release_a: str, release_b: str) -> set[str]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/golden/test_rotate.py
from datetime import UTC, datetime

import pytest

from ground_truth.golden.rotate import cohort_intersection, rotate_private_split
from ground_truth.store.db import connect, migrate


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    for i in range(100):
        c.execute(
            "INSERT INTO items (item_id, split, rubric_version, source, content_hash, "
            "created_at, introduced_release) VALUES (?,'private','v1','synthetic',?,?,?)",
            [f"i{i}", f"hash-{i}", datetime(2026, 10, 1, tzinfo=UTC), "2026.10.15"],
        )
    yield c
    c.close()


def test_rotation_replaces_the_requested_fraction(con):
    record = rotate_private_split(con, fraction=0.20, new_seed=99,
                                  seed_ref="GT_PRIVATE_SEED_2027Q1",
                                  release="2027.01.15", rubric_version="v1")
    assert len(record.retired_hashes) == 20 and len(record.added_hashes) == 20


def test_active_split_size_is_unchanged_after_rotation(con):
    before = con.execute(
        "SELECT count(*) FROM items WHERE split='private' AND retired_at IS NULL"
    ).fetchone()[0]
    rotate_private_split(con, fraction=0.20, new_seed=99, seed_ref="ref",
                         release="2027.01.15", rubric_version="v1")
    after = con.execute(
        "SELECT count(*) FROM items WHERE split='private' AND retired_at IS NULL"
    ).fetchone()[0]
    assert after == before, "rotation replaces items; it does not grow or shrink the active split"


def test_retired_items_are_marked_not_deleted(con):
    record = rotate_private_split(con, fraction=0.20, new_seed=99, seed_ref="ref",
                                  release="2027.01.15", rubric_version="v1")
    for h in record.retired_hashes:
        row = con.execute("SELECT retired_at FROM items WHERE content_hash = ?", [h]).fetchone()
        assert row is not None and row[0] is not None, (
            "retired items stay in the database — historical verdicts must remain valid"
        )


def test_rotation_record_stores_a_seed_name_never_a_seed_value(con):
    record = rotate_private_split(con, fraction=0.20, new_seed=12345, seed_ref="GT_SEED_2027Q1",
                                  release="2027.01.15", rubric_version="v1")
    assert record.seed_ref == "GT_SEED_2027Q1"
    assert "12345" not in str(record), "publishing the seed would let anyone rebuild the split"


def test_rotation_is_recorded_for_audit(con):
    rotate_private_split(con, fraction=0.20, new_seed=99, seed_ref="ref",
                         release="2027.01.15", rubric_version="v1")
    assert con.execute("SELECT count(*) FROM rotations").fetchone()[0] == 1


def test_cohort_intersection_excludes_rotated_items(con):
    record = rotate_private_split(con, fraction=0.20, new_seed=99, seed_ref="ref",
                                  release="2027.01.15", rubric_version="v1")
    shared = cohort_intersection(con, "2026.10.15", "2027.01.15")
    assert len(shared) == 80
    assert not (shared & set(record.retired_hashes))
    assert not (shared & set(record.added_hashes))


def test_rotating_twice_in_one_release_raises(con):
    rotate_private_split(con, fraction=0.20, new_seed=99, seed_ref="ref",
                         release="2027.01.15", rubric_version="v1")
    with pytest.raises(ValueError, match="already rotated"):
        rotate_private_split(con, fraction=0.20, new_seed=100, seed_ref="ref2",
                             release="2027.01.15", rubric_version="v1")


def test_fraction_out_of_range_raises(con):
    with pytest.raises(ValueError):
        rotate_private_split(con, fraction=1.5, new_seed=99, seed_ref="ref",
                             release="2027.01.15", rubric_version="v1")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/golden/test_rotate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.golden.rotate'`.

- [ ] **Step 3: Extend the schema**

Add to `ground_truth/store/db.py`:

```sql
ALTER TABLE items ADD COLUMN IF NOT EXISTS retired_at TIMESTAMP;
ALTER TABLE items ADD COLUMN IF NOT EXISTS introduced_release TEXT;

CREATE TABLE IF NOT EXISTS rotations (
    release TEXT PRIMARY KEY, rotated_at TIMESTAMP NOT NULL,
    retired_hashes TEXT NOT NULL, added_hashes TEXT NOT NULL, seed_ref TEXT NOT NULL);
```

Add `"rotations"` to `TABLES` and to `EXPECTED` in `tests/store/test_db.py`. Retired items are **marked, never deleted** — historical verdicts reference them, and deleting would silently invalidate every published number from earlier releases.

- [ ] **Step 4: Write `ground_truth/golden/rotate.py`**

`rotate_private_split` raises `ValueError` on a `fraction` outside `(0, 1)`, and on a release that already has a `rotations` row (message contains `"already rotated"`). It selects the `n = round(fraction * active_private_count)` oldest non-retired private items by `created_at`, stamps their `retired_at`, generates `n` replacements via `generate(count=n, seed=new_seed, rubric_version=...)` assigned to the private split with `introduced_release = release`, rewrites `golden/manifest_private.json` with the new active hash set plus an appended `rotations` entry, and inserts the audit row.

**`seed_ref` is a name, not a value** — `"GT_PRIVATE_SEED_2027Q1"`, pointing at an `.env` key. The seed itself is never recorded anywhere published, because publishing it would let anyone reconstruct the private split exactly and defeat the whole mechanism.

`cohort_intersection(con, release_a, release_b)` returns the `content_hash` set of private items active in **both** releases: introduced at or before the earlier release, and not retired before the later one.

- [ ] **Step 5: Close the cohort bug in `regression/detect.py`**

Add keyword-only `cohort: set[str] | None = None` and `cross_release: bool = False` to `detect_drift`. When `cohort` is supplied, every observation list is filtered to it before any interval is computed, and the alert statement gains a clause naming the shared sample:

```
f"Comparison restricted to the {len(cohort)} private items present in both releases; "
f"{n_rotated} items rotated between them and are excluded."
```

When `cross_release=True` and `cohort is None`, raise `ValueError` naming `cohort`.

Add these tests to `tests/regression/test_detect.py`:

```python
def test_cohort_restriction_excludes_rotated_items_and_says_so():
    base = {("slot-a", "money"): obs(100, 0.90, 1)}
    curr = {("slot-a", "money"): obs(100, 0.90, 2)}
    cohort = {f"i{i}" for i in range(80)}
    alert = detect_drift(base, curr, look=5, total_looks=13, seed=1, cohort=cohort)[0]
    assert alert.baseline.n == 80 and alert.current.n == 80
    assert "present in both releases" in alert.statement


def test_comparing_across_a_rotation_without_a_cohort_is_refused():
    base = {("slot-a", "money"): obs(100, 0.90, 1)}
    curr = {("slot-a", "money"): obs(100, 0.90, 2)}
    with pytest.raises(ValueError, match="cohort"):
        detect_drift(base, curr, look=5, total_looks=13, seed=1, cross_release=True)
```

The second is the one that matters: a cross-release comparison **must** be refused without an explicit cohort, rather than silently attributing rotation churn to model drift.

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/golden/test_rotate.py tests/regression/test_detect.py tests/store/test_db.py -v`
Expected: PASS.

- [ ] **Step 7: Document the rotation policy**

In `docs/methodology.md`, under the contamination policy: the rotation fraction and cadence; that retired items are marked rather than deleted so historical numbers stay valid; that the seed is withheld and only its name published; and that **cross-release comparisons are computed on the shared cohort only, with the shared n stated in every such alert.**

- [ ] **Step 8: Commit**

```bash
git add ground_truth/golden/rotate.py ground_truth/store/db.py ground_truth/regression/detect.py docs/methodology.md tests/
git commit -m "feat: private-split rotation with cohort-scoped cross-release comparison"
```

---

## Phase 3 exit criteria — the week-26 definition of done

Every one of `04` §12's eleven items, with the test that proves it:

| # | Item | Verified by |
|---|---|---|
| 1 | Golden set 200–500, rubric authored before labelling, versioned, published | `test_dod_1_...` — compares git commit timestamps |
| 2 | Splits enforced in code, contamination policy published, private hashes published | `test_dod_2_...` + `tests/test_contamination.py` |
| 3 | Deterministic graders for every field type where possible | `test_dod_3_...` |
| 4 | Judge with bias controls; agreement reported with an interval, published including weakness | `test_dod_4_...` |
| 5 | Matrix with list-price cost and caveated, unranked latency | `test_dod_5_...` |
| 6 | Calibration curves per field type, exported for Ledger Sense | `test_dod_6_...` |
| 7 | Regression watch on a schedule, alerts stating their test | `test_dod_7_...` |
| 8 | Triage deliverable end to end with sensitivity analysis | `test_dod_8_...` |
| 9 | Public leaderboard with methodology, rubric, grader code, analysis scripts, raw results, changelog, right of reply | `test_dod_9_...` |
| 10 | Reproducibility test passes — published numbers regenerate from published data | `test_dod_10_...` |
| 11 | `docs/methodology.md` defines every term used in every published number | `test_dod_11_...` |

Plus, carried from the spec's non-negotiables:

- [ ] `tests/test_non_goals.py` passes, and has been **observed failing** against a planted registry.
- [ ] `tests/test_contamination.py` passes against real emitted artifacts, and has been **observed failing** against a planted leak.
- [ ] `test_degraded_mode_still_produces_findings` passes with every provider disabled.
- [ ] `axe` reports zero serious or critical violations on all six screens.
- [ ] A stranger, holding only the deployed site's artifacts and `scripts/reproduce.py`, regenerates the headline numbers with zero differences.
