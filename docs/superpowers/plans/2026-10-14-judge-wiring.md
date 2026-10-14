# Judge Wiring Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing judge pieces (target selection, sampling, majority vote, agreement) into the sweep, so the one `grader: judge` field type, LINE_ITEM_DESCRIPTION, is scored, gated per judge, and published.

**Architecture:** Phase 1 (network) adds `run_judging`, which samples each model slot's assigned judge three times on the modal output per (item, slot). Phase 2 (pure, no gateway) adds the judge branch to `grade.py`, writing one verdict per target with `grader_id = "judge:<judge_slot>"`. Decisions move from one per field type to one per (field type, judge). The leaderboard counts a judge's verdicts only when that judge has an **accepted** decision; deterministic verdicts are never gated by a judge decision.

**Tech Stack:** Python 3.12+, DuckDB, pydantic, pytest; Next.js 15 for one web table.

**Spec:** `docs/superpowers/specs/2025-09-18-ground-truth-design.md` §8 (the judge) and §15 (run economics); audit H8 in `docs/superpowers/reviews/2026-08-29-ground-truth-audit.md`; the decisions recorded in `docs/providers.md` "Lineup decisions".

## Decisions this plan implements (human partner, 2026-10-14)

1. **One judge per model slot, n=3 samples, majority vote** (spec §8.1). Two judges are needed, since no available judge family differs from all six slots: Gemma judges slots A–E, and gpt-oss-120b judges the Gemini slot. Both run on Cerebras.
2. **The judge scores the modal output per (item, slot)** (audit H8). The selector exists: `select_judge_targets`, commit b44445e.
3. **INCONCLUSIVE (no majority) scores as incorrect,** and the count is published per (slot, judge).
4. **Agreement is decided and published per judge.** A judge's verdicts reach the headline only with an accepted decision **for that judge**. No decision means not scored (CLAUDE.md rule 3: an unmeasured judge cannot be defended). This replaces `matrix/build.py`'s `jd.status IS NULL` branch, which scored an unassessed judge.

## Global Constraints

- TDD, RED-GREEN-REFACTOR, no exceptions (CLAUDE.md). Run pytest with `OPENBLAS_NUM_THREADS=1 .venv/Scripts/python.exe -m pytest -p no:cacheprovider` (`uv` is not on PATH on this machine).
- `ground_truth/grade.py` imports nothing from `runner`, `judge_runner` or `_bok_shim`. Degraded mode (`tests/test_degraded_mode.py`) depends on that.
- No hardcoded model names in Python source (`00` R1). Judge assignment lives in `models.yaml` only.
- `mypy --strict`, `ruff check`, `ruff format --check` clean before each commit.
- `matrix/build.py` and `graders/judge/agreement.py` feed headline numbers: a high-effort `code-review` before merge (CLAUDE.md skill map).
- Commit trailer: `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

---

### Task 1: Judge assignment in models.yaml

**Files:**
- Modify: `ground_truth/providers.py` (SlotSpec; add `judge_assignments`; it reads only YAML, so `grade.py` may import it)
- Modify: `ground_truth/judge_runner.py` (import `judge_assignments`; keep `SameFamilyJudge` importable from here)
- Modify: `models.yaml` (placeholder `slots.slot-a` gains `judge: judge-a`)
- Test: `tests/test_judge_runner.py`

**Interfaces:**
- Produces: `SlotSpec.judge: str | None = None`; `providers.judge_assignments(models_yaml: Path) -> dict[str, str]` (model slot → judge slot). It raises `ValueError` for a slot with no judge or an unknown judge, and `SameFamilyJudge` for a same-family judge, at load time, before any call. Move `SameFamilyJudge` into `providers.py` and re-export it from `judge_runner` (so existing imports keep working).

- [ ] **Step 1: Write the failing tests** (append to `tests/test_judge_runner.py`)

```python
def _yaml(tmp_path, slot_judge):
    p = tmp_path / "models.yaml"
    p.write_text(
        MODELS_YAML.read_text(encoding="utf-8").replace("judge: judge-a", f"judge: {slot_judge}"),
        encoding="utf-8",
    )
    return p


def test_every_slot_names_its_judge():
    assert judge_assignments(MODELS_YAML) == {"slot-a": "judge-a"}


def test_an_unknown_judge_is_refused_at_load(tmp_path):
    with pytest.raises(ValueError, match="judge-nope"):
        judge_assignments(_yaml(tmp_path, "judge-nope"))


def test_a_same_family_assignment_is_refused_at_load(tmp_path):
    with pytest.raises(SameFamilyJudge):
        judge_assignments(_yaml(tmp_path, "judge-same-family"))


def test_a_slot_without_a_judge_is_refused(tmp_path):
    p = tmp_path / "models.yaml"
    p.write_text(
        MODELS_YAML.read_text(encoding="utf-8").replace("    judge: judge-a\n", ""), "utf-8"
    )
    with pytest.raises(ValueError, match="slot-a"):
        judge_assignments(p)
```

- [ ] **Step 2: Run them.** They fail on `ImportError: judge_assignments`.
- [ ] **Step 3: Implement.** Add `judge: str | None = None` to `SlotSpec`, after `retrieved_at`. Add `    judge: judge-a` under `slots.slot-a`, after its `retrieved_at` line. Then, in `providers.py`:

```python
class SameFamilyJudge(RuntimeError):
    def __init__(self, judge_slot: str, model_slot: str, family: str) -> None:
        super().__init__(
            f"judge {judge_slot!r} and model under test {model_slot!r} share family {family!r}; "
            "self-preference bias makes this judgement indefensible"
        )


def judge_assignments(models_yaml: Path) -> dict[str, str]:
    """Each model slot's judge, validated before any call: it exists and its family differs.
    Declared in models.yaml, never inferred from a model name (spec 8.1)."""
    slots = load_slots(models_yaml)
    judges = load_slots(models_yaml, key="judge_slots")
    assignments: dict[str, str] = {}
    for name, spec in slots.items():
        if spec.judge is None:
            raise ValueError(f"model slot {name!r} names no judge in {models_yaml}")
        if spec.judge not in judges:
            raise ValueError(f"model slot {name!r} names unknown judge {spec.judge!r}")
        if judges[spec.judge].family == spec.family:
            raise SameFamilyJudge(spec.judge, name, spec.family)
        assignments[name] = spec.judge
    return assignments
```

In `judge_runner.py`, delete its `SameFamilyJudge` class and add `from ground_truth.providers import SameFamilyJudge, judge_assignments, load_slots`.

- [ ] **Step 4: Run the tests, then the full suite.** `tests/test_providers_manifest.py` must still pass.
- [ ] **Step 5: Commit** `feat(judge): declare and validate each slot's judge in models.yaml`.

---

### Task 2: Move target selection into the gateway-free judge package

`grade.py` (Task 4) must call `select_judge_targets`, but `judge_runner` imports `_bok_shim`, which degraded mode forbids for `grade.py`.

**Files:**
- Create: `ground_truth/graders/judge/targets.py` (move `JudgeTarget`, `_observed` and `select_judge_targets` here verbatim from `judge_runner.py`)
- Modify: `ground_truth/judge_runner.py` (delete them; `from ground_truth.graders.judge.targets import JudgeTarget, select_judge_targets`, listed in `__all__` or used, so ruff keeps the re-export)
- Test: `tests/test_degraded_mode.py`

- [ ] **Step 1: Write the failing test**

```python
def test_judge_target_selection_needs_no_gateway():
    import ast  # noqa: PLC0415

    from ground_truth.graders.judge import targets  # noqa: PLC0415

    tree = ast.parse(Path(targets.__file__).read_text(encoding="utf-8"))
    imported = {n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module}
    forbidden = {"ground_truth._bok_shim", "ground_truth.runner", "ground_truth.judge_runner"}
    assert not imported & forbidden
```

- [ ] **Step 2: Run it.** It fails on `ImportError`.
- [ ] **Step 3: Move the code.** The selection tests in `tests/test_judge_runner.py` keep importing through `judge_runner`, which proves the re-export works.
- [ ] **Step 4: Run the full suite.** It is green.
- [ ] **Step 5: Commit** `refactor(judge): target selection in the gateway-free judge package`.

---

### Task 3: Phase 1, `run_judging`

**Files:**
- Modify: `ground_truth/judge_runner.py`
- Test: `tests/test_judge_runner.py`

**Interfaces:**
- Consumes: `judge_assignments` (Task 1), `select_judge_targets` (Task 2), `sample_judgements` (existing).
- Produces: `run_judging(con, items: list[Item], rubric: dict[FieldType, RubricRule], *, n: int = 3, resolve_fn, call_fn, context: CallContext, models_yaml: Path = Path("models.yaml"), sensitivity: Sensitivity = Sensitivity.SYNTHETIC) -> int`. It returns the number of judge calls made. Resumable: a target already holding n samples from its judge is skipped.

- [ ] **Step 1: Write the failing tests.** Reuse `_output`/`_desc`. Build items with `ground_truth.golden.schema.Item`, reading that file for the exact constructor: one item `i1` whose fields include `field()`. The rubric is `ground_truth.golden.rubric.loaded_rubric()`.

```python
def test_run_judging_samples_each_target_n_times_with_the_assigned_judge(con):
    for r in range(1, 6):
        _output(con, item_id="i1", slot="slot-a", replicate=r, raw=_desc("Concrete works"))
    gw = FakeGateway()
    calls = run_judging(con, _items(), loaded_rubric(), resolve_fn=gw.resolve,
                        call_fn=gw.call, context=CallContext(), models_yaml=MODELS_YAML)
    assert calls == 3  # noqa: PLR2004 -- one target x n=3, not 5 replicates x 3
    rows = con.execute("SELECT DISTINCT output_id, judge_slot FROM judge_samples").fetchall()
    assert rows == [("o-i1-slot-a-1", "judge-a")]


def test_run_judging_is_resumable(con):
    _output(con, item_id="i1", slot="slot-a", replicate=1, raw=_desc("Concrete works"))
    gw = FakeGateway()
    kwargs = {"resolve_fn": gw.resolve, "call_fn": gw.call, "context": CallContext(),
              "models_yaml": MODELS_YAML}
    run_judging(con, _items(), loaded_rubric(), **kwargs)
    assert run_judging(con, _items(), loaded_rubric(), **kwargs) == 0


def test_a_modally_absent_field_costs_no_judge_call(con):
    _output(con, item_id="i1", slot="slot-a", replicate=1, raw="not json")
    gw = FakeGateway()
    assert run_judging(con, _items(), loaded_rubric(), resolve_fn=gw.resolve,
                       call_fn=gw.call, context=CallContext(), models_yaml=MODELS_YAML) == 0
    assert gw.seen == []
```

- [ ] **Step 2: Run them.** They fail on `ImportError: run_judging`.
- [ ] **Step 3: Implement**

```python
def run_judging(  # noqa: PLR0913 -- the sampler's contract plus the item set
    con: duckdb.DuckDBPyConnection,
    items: list[Item],
    rubric: dict[FieldType, RubricRule],
    *,
    n: int = 3,
    resolve_fn: Callable[[str], Handle],
    call_fn: Callable[..., Response],
    context: CallContext,
    models_yaml: Path = Path("models.yaml"),
    sensitivity: Sensitivity = Sensitivity.SYNTHETIC,
) -> int:
    """Sample each slot's judge n times on the modal output per (item, slot): 300 x 6 x 3 =
    5,400 calls (spec 15). Targets already sampled by their judge are skipped, so an
    interrupted overnight run resumes rather than paying twice."""
    assignments = judge_assignments(models_yaml)  # fails closed before any call
    fields = {
        (item.item_id, f.field_name): f
        for item in items
        for f in item.fields
        if rubric[f.field_type].grader == "judge"
    }
    calls = 0
    for field_name in sorted({name for _, name in fields}):
        for target in select_judge_targets(con, field_name):
            item_field = fields.get((target.item_id, field_name))
            if item_field is None or target.observed is None:
                continue
            judge = assignments[target.model_slot]
            done = con.execute(
                "SELECT count(*) FROM judge_samples WHERE output_id = ? AND field_name = ? "
                "AND judge_slot = ?",
                [target.output_id, field_name, judge],
            ).fetchone()
            if done is not None and done[0] >= n:
                continue
            calls += sample_judgements(
                con, target.output_id, item_field, target.observed, judge, target.model_slot,
                n=n, seed=0, resolve_fn=resolve_fn, call_fn=call_fn, context=context,
                models_yaml=models_yaml, sensitivity=sensitivity,
            )
    return calls
```

- [ ] **Step 4: Run the tests, then the full suite.**
- [ ] **Step 5: Commit** `feat(judge): run_judging samples each slot's judge on the modal output`.

---

### Task 4: Phase 2, judge verdicts in grade.py

**Files:**
- Modify: `ground_truth/grade.py`. Add the keyword `judges: dict[str, str] | None = None` (model slot → judge slot, from `providers.judge_assignments`). With `None`, judge fields are skipped exactly as today, so degraded mode and existing callers are unchanged.
- Modify: `ground_truth/graders/judge/targets.py` (add `judge_verdict`)
- Test: `tests/graders/judge/test_judge_verdicts.py` (create)

**Interfaces:**
- Produces: one verdict per **target output**, `grader_id = f"judge:{judge_slot}"` (the slot's assigned judge in every case, so Task 5's single join gates all of them), `grader_version = JUDGE_GRADER_VERSION = "1"`. The reasons are:
  - EQUIVALENT gives correct=True, reason `f"judge majority EQUIVALENT ({k} of {n})"`.
  - NOT_EQUIVALENT gives correct=False, reason `f"judge majority NOT_EQUIVALENT ({k} of {n})"`.
  - INCONCLUSIVE gives correct=False, reason `f"judge inconclusive: no majority in {n} samples"`. The prefix `"judge inconclusive: "` is what Task 5 counts.
  - A modally absent field gives correct=False, reason `"field not extracted in the modal output; not judged"`, with no judge call made.
- A target with fewer than 3 samples writes **no** verdict: it hasn't been judged, and an unjudged output is not a measurement.
- `judge_verdict(con, target: JudgeTarget, judge_slot: str) -> Verdict | None`.

- [ ] **Step 1: Write the failing tests.** Build a store with one item, one slot and five replicates, using `_output`/`_desc` copied into the new test file. Insert three `judge_samples` rows directly for the target. Call `grade_stored_outputs(con, items, loaded_rubric(), judges={"slot-a": "judge-a"})` and assert:
  - samples `["EQUIVALENT", "EQUIVALENT", "NOT_EQUIVALENT"]` give exactly one `line_1_description` verdict, `correct is True`, `grader_id == "judge:judge-a"`, on the target output only;
  - samples `["EQUIVALENT", "NOT_EQUIVALENT", "garbage"]` (a tie) give `correct is False` with a reason starting `"judge inconclusive: "`;
  - all five replicates unparseable gives one verdict on replicate 1, `correct is False`, the absent reason, and `grader_id == "judge:judge-a"`;
  - two samples give no verdict;
  - re-grading writes nothing new;
  - `judges=None` gives no judge verdict at all (unchanged behavior).
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement.** In `grade_stored_outputs`, when `judges` is given, build `targets = {(t.output_id, name): t for name in judge_field_names for t in select_judge_targets(con, name)}` before the output loop, where `judge_field_names` are the field names whose rubric grader is `"judge"`. Write a judge verdict through `_write_judge(output_id, item)` at two points:
  - **in the schema-failure path**, before `continue`, because an unparseable target is still the modal target and must score as absent;
  - **in the `grader_name == "judge"` branch**, replacing the bare `continue`.

  In both, `target = targets.get((output_id, field.field_name))`; skip if `None` (not the modal output); otherwise `verdict = judge_verdict(con, target, judges[slot])` and write it if not `None`. The slot comes from `SELECT model_slot FROM runs JOIN outputs USING (run_id) WHERE output_id = ?`; or extend the output loop's query to select `r.model_slot`. `judge_verdict` returns the absent verdict when `target.observed is None`. Otherwise it reads `presentation_order, raw_judgement FROM judge_samples WHERE output_id=? AND field_name=? AND judge_slot=?`, returns `None` below 3 rows, and builds `Sample(order, raw, len(target.observed))` for `majority_vote`.
- [ ] **Step 4: Run the tests, the full suite, and `tests/test_degraded_mode.py`.**
- [ ] **Step 5: Commit** `feat(grade): score LINE_ITEM_DESCRIPTION from the judge's majority vote`.

---

### Task 5: Decisions per (field type, judge), gating the headline

**Files:**
- Modify: `ground_truth/store/db.py` (`judge_decisions` gains `judge_slot TEXT NOT NULL`, PK `(field_type, judge_slot)`; a guarded rebuild in `migrate`)
- Modify: `ground_truth/graders/judge/agreement.py` (`record_decision(con, report, *, rubric_version, judge_slot)`)
- Modify: `ground_truth/matrix/build.py` (`_OBSERVATIONS_SQL`)
- Modify: `ground_truth/publish/artifacts.py` (publish `judge_slot` per decision, plus a top-level `inconclusive` list)
- Test: `tests/matrix/test_build.py`, `tests/graders/judge/test_agreement.py`, the store migration tests, `tests/publish/test_artifacts.py`

**Interfaces:**
- Produces: the `judge_decisions` key `(field_type, judge_slot)`. In `judge_agreement.json`, each decision carries `"judge_slot"`, and there is a new `"inconclusive": [{"slot", "judge_slot", "count", "n"}]`, sorted by (slot, judge_slot), where `n` is the number of judge verdicts for that pair.

- [ ] **Step 1: Write the failing tests.**
  - **build, new rule:**
    - a `judge:judge-a` verdict with **no** decision is absent from `per_field`;
    - with `accepted` for `(line_item_description, judge-a)`, it is present;
    - with `accepted` for `judge-b` only, it is absent (the wrong judge's decision);
    - with `rejected` for `judge-a`, it is absent.
  - **build, the replaced rule:** `test_rejected_field_type_is_absent_from_headline_accuracy` and its siblings encoded "a decision row removes every verdict of that field type, deterministic ones included". Rewrite them so a decision never removes a **deterministic** verdict, since a rejected judge falls back to deterministic grading where one exists (analysis plan, "Judge rejection threshold"). Keep the original intent, that a rejected judge's verdicts never reach the headline, asserted on judge verdicts.
  - **migration:**
    - an old-shape `judge_decisions` table (no `judge_slot`) **holding rows** makes `migrate` raise, naming the table and saying the rows cannot be re-keyed honestly;
    - an empty old-shape table is rebuilt to the new shape.
  - **record_decision:** two judges for one field type store two rows, and re-recording one judge replaces only its own row.
  - **publish:** each decision carries `judge_slot`, and the `inconclusive` counts equal the verdicts whose reason starts `"judge inconclusive: "`.
- [ ] **Step 2: Run them.** They fail.
- [ ] **Step 3: Implement.**
  - **Schema:** add `judge_slot TEXT NOT NULL` and `PRIMARY KEY (field_type, judge_slot)`.
  - **`migrate`:** before `_SCHEMA`, check `information_schema.columns` for `judge_decisions`. If the table exists without a `judge_slot` column, raise if it has rows; otherwise `DROP TABLE judge_decisions`, so `_SCHEMA` recreates it. As of 2026-10-14 no store holds a real decision.
  - **Build exclusion:**

```sql
    LEFT JOIN judge_decisions jd
           ON jd.field_type = ifld.field_type
          AND v.grader_id = 'judge:' || jd.judge_slot
    WHERE i.split = ? AND i.retired_at IS NULL
          AND (v.grader_id NOT LIKE 'judge:%' OR jd.status = 'accepted')
```

- [ ] **Step 4: Run the full suite. Then run a high-effort `code-review` on the diff to `matrix/build.py`, `agreement.py` and `db.py`** (CLAUDE.md: stats-adjacent, highest-risk), and resolve its findings.
- [ ] **Step 5: Commit** `feat(judge): agreement decided per judge; unassessed judges never score`.

---

### Task 6: Web judge table shows the judge

**Files:**
- Modify: `web/app/judge/page.tsx` (rows keyed `` `${field_type}:${judge_slot}` ``; a "Judge" column; an "Inconclusive" table showing `count of n` per slot and judge)
- Modify: `web/lib/artifacts.ts` types for `judge_slot` and `inconclusive` (optional fields)
- Modify: `artifacts/judge_agreement.json` placeholder (each decision gains `judge_slot`; add `"inconclusive": []`)
- Test: the web e2e/axe suite (the script named in `web/package.json`)

- [ ] **Step 1:** Write an e2e assertion that each agreement row shows its judge, and that two rows sharing a field type both render.
- [ ] **Step 2:** Run it. It fails.
- [ ] **Step 3:** Implement. Treat `judge_slot` and `inconclusive` as optional, as the page already does for placeholder-only fields.
- [ ] **Step 4:** Run `npx --prefix web tsc --noEmit`, the e2e suite and axe. Then run the React/TypeScript reviewer (CLAUDE.md skill map).
- [ ] **Step 5: Commit** `feat(web): judge agreement per judge, with inconclusive counts`.

---

### Task 7: Analysis plan v3 and methodology

**Files:**
- Modify: `docs/analysis-plan.md` (`plan_version: v3`; the "Judge rejection threshold" section; a revision-history entry)
- Modify: `docs/methodology.md` (the judge section)
- Modify: `CHANGELOG.md`

- [ ] **Step 1:** In the "Judge rejection threshold" section, change the decision unit from field type to **(field type, judge)**, keeping the `0.667` threshold text verbatim (`test_threshold_matches_the_pre_registered_plan`). Add four sentences:
  - a judge with no recorded decision is not used for headline scoring;
  - INCONCLUSIVE scores as incorrect, and its count is published;
  - the judge scores the modal output per (item, slot);
  - LINE_ITEM_DESCRIPTION's run-to-run variance is therefore not measured by the judge.
- [ ] **Step 2:** Add a revision-history entry for **v3, 2026-10-14**, in v2's form. State that v2 governed zero sweeps, verifying first with `SELECT count(*) FROM runs` (0 in `data/results.duckdb`). Keep v2's judge paragraph quoted below, unedited.
- [ ] **Step 3:** In the methodology, state the two judges, which slots each scores, and that agreement is published per judge. State that Gemini is judged by a different model from the other five, as a disclosed comparability limit.
- [ ] **Step 4:** Run the full suite (the plan-pairing test) and `ruff`/`mypy`.
- [ ] **Step 5: Commit** `docs: analysis plan v3 -- judge decisions per judge`.

---

## Out of scope (stated so it isn't assumed done)

- **Human labels for agreement.** `assess` needs judge-versus-human verdicts on a sample. Labelling is the human partner's work (a single annotator, with a blind re-label of 20% after two weeks, per CLAUDE.md "Watch for"), and nothing here can produce it. Until it exists, every judge is undecided, so LINE_ITEM_DESCRIPTION is correctly reported as not measured.
- **The real models.yaml.** The real judge assignments (Gemma for A–E, gpt-oss-120b for F) are written when the live audit fills `models.yaml`, after provider keys exist.
- **Calling `run_judging` from a CLI or the schedule.** It belongs with the sweep's overnight schedule, planned once rate limits are observed live.
