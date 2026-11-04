# Judge Publish Blockers Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the four items that block a real publish of judge-graded results, so a judged field can reach the headline only when it is complete, correctly weighted, counted once, and no test fixture ships in the site.

**Architecture:** Tasks 1-3 change one function family in `ground_truth/matrix/build.py` (`_OBSERVATIONS_SQL`, `_headline_observations`). The publisher (`publish/artifacts.py`) and `scripts/reproduce.py` already derive `counts_toward_headline` and `weight` from that function, so they pick the fixes up with no code change. Task 4 is independent and web/CI only.

**Tech Stack:** Python 3.12, DuckDB, pytest, ruff, `mypy --strict`; Next.js 15 static export, Playwright, GitHub Actions.

**Spec:** the open-items list in `.superpowers/sdd/2026-10-14-judge-wiring/progress.md` (inside `.claude/worktrees/judge-wiring/`, untracked); CLAUDE.md rules 2, 3 and 4; `docs/analysis-plan.md` v3; `docs/methodology.md` section on "Which verdicts count".

## Global Constraints

- TDD, RED-GREEN-REFACTOR, no exceptions (CLAUDE.md). Every behaviour change starts with a test seen failing for the stated reason.
- `matrix/build.py` is in the publish workflow's "no `float(` in the money path" grep: do not write `float(` there.
- No hardcoded model names (R1), no secrets, no new dependencies.
- Judge verdicts stay fail-closed: when in doubt a judged field is dropped from the headline and the field falls back to deterministic grading, never half-counted.
- Run Python through the project venv: `.venv\Scripts\python.exe -m pytest ...` (`uv` is not on PATH in this shell). `mypy` is run as `.venv\Scripts\python.exe -m mypy --strict ground_truth` (a bare `.` fails on test paths).
- Analysis plan v3 is already in main. Amend it in place **only if no sweep has run under it**: check that `SELECT count(*) FROM runs` on `data/results.duckdb` is 0 (or the file is absent). If any run exists, add a `v4` plan instead and say so in the changelog.
- Work on a fresh branch from main in a worktree (`superpowers:using-git-worktrees`), not on main.
- Commit trailer: `Co-Authored-By: Claude Sonnet 5.5 <noreply@anthropic.com>`.
- Before merge: `code-review` at high effort over `matrix/build.py` changes (CLAUDE.md treats the numbers path as high risk), and `security-review` for Task 4 (it touches what is published from `web/`).

## File Structure

- Modify `ground_truth/matrix/build.py`: Tasks 1, 2, 3.
- Modify `tests/matrix/test_build.py`: Tasks 1, 2, 3 (reuses its helpers `_two_slots`, `_fields_by_slot`, `_replicated_run`, `_populate_two_field_types`, `TWO_JUDGES`, `JUDGES`, the `con` fixture).
- Create `web/lib/fixtures.ts`: Task 4, the single guard for fixture routes.
- Modify `web/app/judge/multi-judge-example/page.tsx`, `web/app/judge/degraded-example/page.tsx`, `web/playwright.config.ts`: Task 4.
- Modify `.github/workflows/publish.yml`: Task 4, a post-build check.
- Modify `docs/methodology.md`, `docs/analysis-plan.md`, `CHANGELOG.md`: Tasks 1-3 (wording must match behaviour; there are tests that read these docs, so run the full suite after each docs edit).

---

### Task 1: Count only the current verdict per (output, field, grader)

**Why:** `verdicts` is append-only and its UNIQUE key includes `grader_version` and `rubric_version`, so a version bump re-grades an output and appends a second verdict for the same output and field. `_OBSERVATIONS_SQL` returns both and both count, which double-weights the field and can count a stale wrong answer beside a corrected one.

**Rule chosen:** for each `(output_id, field_name, grader_id)`, only the verdict with the latest `computed_at` counts (ties broken by `verdict_id`). Latest-wins needs no registry of "current" versions and works for grader and rubric bumps alike. It applies to deterministic and judge verdicts.

**Files:**
- Modify: `ground_truth/matrix/build.py` (`_OBSERVATIONS_SQL`, lines 61-74)
- Test: `tests/matrix/test_build.py`

**Interfaces:**
- Consumes: the `verdicts` table (`verdict_id, output_id, field_name, grader_id, grader_version, rubric_version, correct, reason, computed_at`).
- Produces: unchanged signatures. `headline_verdict_ids` / `headline_verdict_weights` now exclude superseded verdicts, so published `counts_toward_headline` is false for them.

- [ ] **Step 1: Write the failing tests** (append under the "every slot is ranked on the same field set" section of `tests/matrix/test_build.py`)

```python
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
    assert "v-exact-slot-a" not in headline_verdict_ids(
        con, split=Split.PUBLIC, judges=TWO_JUDGES
    )
```

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/matrix/test_build.py -k "regrade or regraded" -v`
Expected: the first and third FAIL (`{"money": 0.5}` != `{"money": 0.0}`; the old id is still in the set). The second PASSES already; that is fine, it pins the key choice.

- [ ] **Step 3: Implement.** In `_OBSERVATIONS_SQL`, add a `QUALIFY` after the `WHERE`:

```python
_OBSERVATIONS_SQL = """
    SELECT v.verdict_id, r.model_slot, o.output_id, o.item_id, ifld.field_type, v.correct,
           o.latency_ms, o.token_count, v.grader_id, v.field_name
    FROM verdicts v
    JOIN outputs o ON o.output_id = v.output_id
    JOIN runs r ON r.run_id = o.run_id
    JOIN items i ON i.item_id = o.item_id
    JOIN item_fields ifld ON ifld.item_id = o.item_id AND ifld.field_name = v.field_name
    LEFT JOIN judge_decisions jd
           ON jd.field_type = ifld.field_type
          AND v.grader_id = 'judge:' || jd.judge_slot
    WHERE i.split = ? AND i.retired_at IS NULL
          AND (v.grader_id NOT LIKE 'judge:%' OR jd.status = 'accepted')
    QUALIFY row_number() OVER (
        PARTITION BY v.output_id, v.field_name, v.grader_id
        ORDER BY v.computed_at DESC, v.verdict_id DESC
    ) = 1
"""
```

Extend the comment block above the constant with one sentence: "A re-grade at a bumped grader or rubric version appends a second verdict for the same output, field and grader; only the latest counts."

- [ ] **Step 4: Run to verify they pass, then the whole matrix + publish + reproducibility tests**

Run: `.venv\Scripts\python.exe -m pytest tests/matrix tests/publish tests/test_reproducibility.py tests/test_reproduce_script.py -q`
Expected: all PASS. If an existing test inserts two verdicts for one (output, field, grader) on purpose, read it before changing anything: it encodes the old double-count and must be updated with the reason in the commit message.

- [ ] **Step 5: Docs.** In `docs/methodology.md`, in the "Which verdicts count" list, add: "A verdict superseded by a later re-grade of the same output, field and grader does not count; `counts_toward_headline` is false for it." Add the same one line under Task-level notes in `CHANGELOG.md`.

- [ ] **Step 6: Gates and commit**

Run: `.venv\Scripts\python.exe -m ruff check . && .venv\Scripts\python.exe -m ruff format --check . && .venv\Scripts\python.exe -m mypy --strict ground_truth && .venv\Scripts\python.exe -m pytest -q`
Expected: clean, all pass.

```bash
git add ground_truth/matrix/build.py tests/matrix/test_build.py docs/methodology.md CHANGELOG.md
git commit -m "fix(matrix): a re-graded verdict supersedes the old one in the headline"
```

---

### Task 2: Weight the judged field by schema-valid replicates only

**Why:** the judged verdict's weight is the `(item, slot)` replicate count, which includes schema-invalid outputs (no deterministic field verdicts) and outputs not yet graded. A deterministic field only has a verdict per schema-valid graded output, so the judged field outweighs it: about 0.385 vs 0.333 at 20% unparseable, and 0.5 vs 0.167 when five new ungraded outputs arrive before re-grading.

**Rule chosen:** weight = the number of distinct outputs of the `(item, slot)` that have a `__schema__` verdict with `correct = true`, floored at 1 (a judged verdict exists, so it must count at least once; the floor only matters when every replicate is unparseable). This is exactly the number of verdicts a deterministic field has for that `(item, slot)`.

**Files:**
- Modify: `ground_truth/matrix/build.py` (`_REPLICATES_SQL` line 161, its use at line 194-197)
- Test: `tests/matrix/test_build.py`

**Interfaces:**
- Consumes: `__schema__` verdict rows written by `grade.py` (`_SCHEMA_FIELD = "__schema__"`).
- Produces: `_Observation.weight` for judge verdicts changes meaning from "replicate outputs" to "schema-valid graded outputs"; `headline_verdict_weights` returns it.

- [ ] **Step 1: Update the helper so replicates are graded like production.** In `_replicated_run`, add a `__schema__` verdict per output, inside the replicate loop after the `outputs` insert:

```python
        con.execute(
            "INSERT INTO verdicts VALUES (?, ?, '__schema__', 'schema', '1', 'v1', true, 'ok', "
            "now())",
            [f"v-{output_id}-schema", output_id],
        )
```

Existing `test_a_judged_field_weighs_as_much_as_a_deterministic_field_across_runs` (expects weight 10, score 1/3) must still pass with this helper change: that is the regression guard for the happy path.

- [ ] **Step 2: Write the failing tests** (append after that test)

```python
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
```

Note on the third test: with every output schema-invalid the deterministic verdicts still exist in the fixture, which is not a production state; the test pins only the floor.

- [ ] **Step 3: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/matrix/test_build.py -k "judged_weight or schema_invalid_outputs or ungraded_outputs" -v`
Expected: the first two FAIL (`5 != 3`, `10 != 5`). The floor test may pass under the old code (weight 5); that is acceptable because it pins the floor for the new SQL. Do not skip the red step for the first two.

- [ ] **Step 4: Implement.** Replace `_REPLICATES_SQL` and its comment/use:

```python
# The judged field's weight: how many verdicts a deterministic field has for this (item, slot),
# i.e. the outputs that parsed (a correct `__schema__` verdict). Counting every stored output
# let schema-invalid and not-yet-graded replicates inflate the judged field's share of the item
# score. `count(DISTINCT ...)` because a re-grade appends a second `__schema__` verdict.
_REPLICATES_SQL = """
    SELECT o.item_id, r.model_slot, count(DISTINCT o.output_id)
    FROM outputs o
    JOIN runs r ON r.run_id = o.run_id
    JOIN verdicts v ON v.output_id = o.output_id
                   AND v.field_name = '__schema__' AND v.correct
    GROUP BY o.item_id, r.model_slot
"""
```

and at the weight line (229) use `max(1, replicates.get((item_id, slot), 0))` for judge verdicts. Keep the `_Observation.weight` comment but change "replicate-output count" to "schema-valid graded output count". Import nothing from `grade.py` (avoid a build -> grade dependency); the literal `'__schema__'` is the same constant as `grade._SCHEMA_FIELD`, and the Step 1/2 tests fail if the two drift.

- [ ] **Step 5: Run to verify**

Run: `.venv\Scripts\python.exe -m pytest tests/matrix tests/publish tests/test_reproducibility.py -q`
Expected: PASS, including the existing weight-parity test (weight 10 / score 1/3).

- [ ] **Step 6: Docs.** Fix the "equal weight" wording in `docs/methodology.md`, `docs/analysis-plan.md` (v3) and `CHANGELOG.md` to: "the judged verdict weighs as many times as the (item, slot) has schema-valid graded outputs, which is the number of verdicts a deterministic field has for it; an output that failed schema validation or has not been graded counts for neither." Remove the unconditional "equal weight" claim.

- [ ] **Step 7: Gates and commit**

Run the full gate line from Task 1 Step 6.

```bash
git add ground_truth/matrix/build.py tests/matrix/test_build.py docs CHANGELOG.md
git commit -m "fix(matrix): weigh the judged field by schema-valid graded outputs only"
```

---

### Task 3: Judging-completeness gate

**Why:** the decision gate checks that a judge is *accepted*, not that judging is *finished*. If judging is partial, one slot can be ranked on a judged field while another has none for some items, which is the I1 harm again (different field sets inside one leaderboard).

**Rule chosen (fail closed, drop, do not refuse):** a judged field type counts for every slot only if, in this split, every current judge target for that field type has a counted judge verdict. If any target is unjudged, the field type is dropped for all slots and the headline falls back to deterministic grading, exactly as for a rejected judge. Dropping, not refusing, keeps `emit_all` runnable mid-sweep and uses the one rule that `counts_toward_headline` already encodes. A target with a verdict counts as judged even if the verdict is "inconclusive" or "not extracted": those are measurements, and rule 3 requires them reported, not hidden. Only a target with no verdict (fewer than 3 samples) is unjudged.

**Files:**
- Modify: `ground_truth/matrix/build.py` (`_headline_observations`, lines 168-232)
- Test: `tests/matrix/test_build.py`

**Interfaces:**
- Consumes: `select_judge_targets(con, field_name) -> list[JudgeTarget]` (`item_id, model_slot, output_id, observed`); `_current_judge_targets`; the rows from `_OBSERVATIONS_SQL`.
- Produces: new private helper `_unjudged_field_types(con, *, split, slots, judged, field_types) -> frozenset[str]`; `_headline_observations` drops those field types' judge verdicts.

- [ ] **Step 1: Write the failing tests** (append after the I1 tests). `_two_slots` gives one item, two slots, one output each, both judged, both judges accepted. Make a second item whose slot-b output has no judge verdict:

```python
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
```

(`json` is already imported at the top of the test file.) The other-split case needs a private-split item with an unjudged target and a public-split assertion; add it as a fifth test the same way (`UPDATE items SET split = 'private' WHERE item_id = 'i2'`, then assert the public field is still present).

- [ ] **Step 2: Run to verify they fail**

Run: `.venv\Scripts\python.exe -m pytest tests/matrix/test_build.py -k "unjudged or last_target or inconclusive_verdict or completeness_ignores" -v`
Expected: the first FAILS (descriptions still counted). The others should PASS or fail for the stated reason only. If a "ignores" test fails because `select_judge_targets` yields targets for retired or other-split items, that is the bug the filter in Step 3 fixes.

- [ ] **Step 3: Implement.** Add the helper above `_headline_observations`:

```python
def _unjudged_field_types(
    con: duckdb.DuckDBPyConnection,
    *,
    split: Split,
    slots: set[str],
    judged: set[tuple[str, str]],
    field_types: set[str],
) -> frozenset[str]:
    """The judged field types with a current judge target that has no counted verdict yet.

    `judged` is `(output_id, field_name)` for every judge verdict that survived the other
    gates; `field_types` the judged types still in play. A target belongs to this split when its
    item is in the split, is not retired, and declares the field. Fewer than three samples
    leaves a target without a verdict (`judge_verdict` returns None): unjudged, not a
    measurement, so the type is held back for every slot until the sweep finishes it. An
    inconclusive or not-extracted verdict exists and so counts as judged.
    """
    if not field_types:
        return frozenset()
    declared = con.execute(
        "SELECT i.item_id, f.field_name, f.field_type FROM items i "
        "JOIN item_fields f ON f.item_id = i.item_id "
        "WHERE i.split = ? AND i.retired_at IS NULL",
        [split.value],
    ).fetchall()
    type_of = {(item_id, name): ftype for item_id, name, ftype in declared}
    names = sorted({name for (_, name), ftype in type_of.items() if ftype in field_types})
    return frozenset(
        type_of[(target.item_id, name)]
        for name in names
        for target in select_judge_targets(con, name)
        if (target.item_id, name) in type_of
        and target.model_slot in slots
        and (target.output_id, name) not in judged
    )
```

Then in `_headline_observations`, split the loop in two. Pass 1 builds the candidates exactly as now (including the three `continue` gates and the `weight`), and for each judge observation also records its `field_name`. Keep them together, e.g. `candidates: list[tuple[_Observation, str | None]]` where the second element is the `field_name` for a judge verdict and `None` for a deterministic one. After pass 1:

```python
    judged = {(o.output_id, name) for o, name in candidates if name is not None}
    held_back = _unjudged_field_types(
        con,
        split=split,
        slots={o.slot for o, _ in candidates},
        judged=judged,
        field_types={o.field_type for o, name in candidates if name is not None},
    )
    return [o for o, name in candidates if name is None or o.field_type not in held_back]
```

Update the `_headline_observations` docstring bullet list with the fourth rule. The requirement is the behaviour, not this exact shape; a small private dataclass is fine if it reads better.

- [ ] **Step 4: Run to verify they pass, then everything touching the headline**

Run: `.venv\Scripts\python.exe -m pytest tests/matrix tests/publish tests/test_reproducibility.py tests/test_reproduce_script.py -q`
Expected: PASS. Existing tests that build a judged field for one slot with one item are unaffected (their only target is judged). If an existing test has a judge target with no verdict and expects the field counted, it encoded the gap this task closes; update it and say why in the commit message.

- [ ] **Step 5: Docs.** `docs/methodology.md` "Which verdicts count": add "A judged field type counts only when every current judge target for it, across the ranked slots, has a verdict; while any is unjudged the field is out for every slot and the headline uses deterministic grading, like a rejected judge." Add the same to `CHANGELOG.md`, and to `docs/analysis-plan.md` v3 beside the I1 ruling, noting the reason (a partial run would rank slots on different field sets).

- [ ] **Step 6: Gates and commit**

Run the full gate line from Task 1 Step 6.

```bash
git add ground_truth/matrix/build.py tests/matrix/test_build.py docs CHANGELOG.md
git commit -m "fix(matrix): a judged field counts only once every current target is judged"
```

---

### Task 4: Keep the fixture routes out of the published site

**Why:** `/judge/multi-judge-example` and `/judge/degraded-example` are exported into `web/out` and uploaded to GitHub Pages on `v*` tags. Their alpha numbers are synthetic. They are noindexed and bannered, but a published page of invented agreement numbers is exactly the failure this project exists to correct.

**Rule chosen:** both pages call a shared guard that 404s unless `GT_E2E_FIXTURES=1` is set at build or dev time. Playwright's web server sets it. The publish workflow never sets it, and a post-build step fails the release if any fixture marker is found in `web/out`.

**Files:**
- Create: `web/lib/fixtures.ts`
- Modify: `web/app/judge/multi-judge-example/page.tsx`, `web/app/judge/degraded-example/page.tsx`, `web/playwright.config.ts`, `.github/workflows/publish.yml`
- Test: build-and-grep verification (Steps 3-5); the existing e2e specs `judge.spec.ts`, `judge-degrades.spec.ts`, `a11y.spec.ts` stay green with the flag set.

**Interfaces:**
- Produces: `requireFixtureRoute(): void` in `web/lib/fixtures.ts`, and the marker attribute `data-gt-fixture` rendered by each fixture page.

- [ ] **Step 1: Red first.** Before touching any file, show the leak.

Run: `npm run build --prefix web`, then `grep -rlE "slot_one|judge_b" web/out`
Expected: matches under `web/out/judge/multi-judge-example/`. This is the failing state the task fixes.

- [ ] **Step 2: Write the guard**

```ts
// web/lib/fixtures.ts
import { notFound } from "next/navigation";

// Test-only routes render synthetic numbers. They exist for Playwright and must never reach the
// published site: without GT_E2E_FIXTURES=1 the route 404s. publish.yml also greps web/out for
// the data-gt-fixture marker after the build and fails the release if it finds one.
export function requireFixtureRoute(): void {
  if (process.env.GT_E2E_FIXTURES !== "1") {
    notFound();
  }
}
```

- [ ] **Step 3: Use it in both pages.** In each page component, call it first and render the marker:

```tsx
import { requireFixtureRoute } from "@/lib/fixtures";

export default function JudgeMultiJudgeExamplePage() {
  requireFixtureRoute();
  return (
    <>
      <span hidden data-gt-fixture="multi-judge-example" />
      <JudgeAgreementView judge={MULTI_JUDGE} methodologyUrl="/methodology" />
    </>
  );
}
```

and the same for `JudgeDegradedExamplePage` with `data-gt-fixture="degraded-example"`.

- [ ] **Step 4: Verify the guard on the production build**

Run: `npm run build --prefix web` (flag unset), then `grep -rl "data-gt-fixture" web/out` and `grep -rlE "slot_one|judge_b" web/out`
Expected: both print nothing.

**If the build itself fails** because `notFound()` is not allowed in a static-export page, STOP and report: do not improvise another mechanism. The fallbacks to bring back as a decision are (a) a `pageExtensions` switch in `next.config.ts`, or (b) moving the fixtures into a path excluded by the export step.

- [ ] **Step 5: Verify the flagged build still serves them.** PowerShell: `$env:GT_E2E_FIXTURES = "1"; npm run build --prefix web; Remove-Item Env:GT_E2E_FIXTURES`, then `grep -rl "data-gt-fixture" web/out`.
Expected: both routes' files listed. Rebuild without the flag (or delete `web/out`) afterwards so the flagged output is not left lying around.

- [ ] **Step 6: Playwright sets the flag.** In `web/playwright.config.ts`, add to `webServer`:

```ts
    env: { GT_E2E_FIXTURES: "1" },
```

Run: `npx --prefix web playwright test judge judge-degrades a11y`
Expected: PASS, including the two fixture routes. Then run the full Playwright suite once, which also covers the e2e/axe re-run that was skipped on the final judge-wiring tree.

- [ ] **Step 7: Publish check.** In `.github/workflows/publish.yml`, after `- run: npm run build --prefix web` insert:

```yaml
      - name: no test fixture routes in the published site
        # web/app/judge/*-example render synthetic numbers for Playwright only. They 404 unless
        # GT_E2E_FIXTURES=1, which this workflow never sets; this fails the release if one slips
        # into the export anyway.
        run: |
          if grep -rl "data-gt-fixture" web/out; then
            echo "a fixture route reached web/out"; exit 1
          fi
```

- [ ] **Step 8: Commit**

```bash
git add web/lib/fixtures.ts web/app/judge web/playwright.config.ts .github/workflows/publish.yml
git commit -m "fix(web): fixture routes 404 unless GT_E2E_FIXTURES=1; publish fails if one is exported"
```

---

## Finish

- [ ] Run `.venv\Scripts\python.exe -m pytest -q` (also `-m slow` once), ruff, `mypy --strict ground_truth`, and the full Playwright suite on the final tree. Report the counts; compare to main's 617 passed / 28 skipped.
- [ ] `code-review` at high effort over the `matrix/build.py` diff; `security-review` over Task 4.
- [ ] Update the docs and the progress ledger so the four items are marked closed, and say what remains open: the smaller deferred items in the judge-wiring ledger, the human labelling, and the sweep schedule (none of which this plan touches).
- [ ] Use `superpowers:finishing-a-development-branch`.

## Self-review

- **Coverage:** completeness gate (Task 3), weight fix with docs (Task 2), re-grade double count (Task 1), fixture routes with the e2e flag and a publish check (Task 4): all four items from the report. Docs wording is updated inside each task because tests read the docs.
- **Placeholders:** none. The two spots that depend on code I could not see (an existing test that may encode the old behaviour, and whether `notFound()` is allowed in a static-export page) each have an explicit instruction for what to do if they bite.
- **Consistency:** `_headline_observations`, `headline_verdict_weights`, `headline_verdict_ids`, `_unjudged_field_types`, `requireFixtureRoute` and `data-gt-fixture` are named identically wherever they appear. Task 2 changes the helper `_replicated_run`; Task 3's tests do not depend on it.
- **Ordering:** Tasks 1 to 3 edit the same function and must go in order; Task 4 is independent and can run in parallel.
