# Definition of done

`04` §12 lists eleven items that define "finished" for this project. Each one has a
machine-checked test in [`tests/test_definition_of_done.py`](../tests/test_definition_of_done.py)
and is satisfied by a real, named artifact in this repository — not a claim.

**Current status: not yet verifiable.** Every test below skips rather than passes or fails,
because no live provider sweep has ever run. `artifacts/` holds only the hand-written
placeholder data committed alongside the web screens (Tasks 45–48) — explicitly flagged
`"placeholder": true` — not a real release. Running these tests against that placeholder data
would produce a meaningless pass, so the shared `_require_release` fixture skips all eleven
until a real `emit_all` run replaces it. This page will be updated with real PASS results, and
the release tagged (`git tag phase-3-published`), once that sweep has happened.

| # | Item (verbatim, `04` §12) | Test | Satisfying artifact |
|---|---|---|---|
| 1 | Golden set built, 200–500 items, with a written rubric authored before labelling, versioned and published. | `test_dod_1_golden_set_and_rubric_authored_before_labelling` | `docs/rubric.md` (committed before the first labels — checked via git history), `golden/manifest_public.json` + `golden/manifest_private.json` (combined item count) |
| 2 | Public and private splits enforced in code, contamination policy published, private hashes published. | `test_dod_2_splits_enforced_and_hashes_published` | `golden/manifest_private.json` (hashes only, no content), `docs/methodology.md`'s contamination-policy section, `golden/corpus/private/` untracked by git |
| 3 | Deterministic graders for every field type where one is possible. | `test_dod_3_deterministic_graders_for_every_possible_field_type` | `docs/rubric.md`, parsed via `ground_truth.golden.rubric.loaded_rubric` — only `LINE_ITEM_DESCRIPTION` may route to the judge grader |
| 4 | Judge implemented with bias controls, and judge-versus-human agreement measured, reported with an interval, and published — including where it is weak. | `test_dod_4_judge_agreement_published_including_weakness` | `artifacts/judge_agreement.json` (`decisions[]`, each with `alpha_low`/`alpha_high`/`n_units`/`status`, published regardless of accepted/rejected) |
| 5 | Model × cost × latency matrix, with cost as labelled list price and latency correctly caveated. | `test_dod_5_matrix_has_list_price_cost_and_caveated_latency` | `artifacts/leaderboard.json` (`rows[].cost.caveat` states list price, `rows[].latency.caveat` states free tier, no latency ranking) |
| 6 | Calibration curves fitted per field type and exported in a form Ledger Sense consumes. | `test_dod_6_calibration_exported_for_ledger_sense` | `artifacts/calibration.json` (`curves[]`, each with `threshold_recommendations` and `source_split: "public-fit/private-validate"`) |
| 7 | Regression watch running on a schedule with correct statistics and alerts that state their test. | `test_dod_7_regression_watch_scheduled_and_alerts_state_their_test` | `.github/workflows/regression-watch.yml` (`schedule:`/`cron:`, secondary check), `ground_truth.regression.schedule`'s pre-registered 13-look quarterly calendar with monotone O'Brien–Fleming alpha spend (load-bearing check, per the plan's 2026-08-29 amendment to Task 38), `artifacts/regression.json` (`alerts[].statement` names the test) |
| 8 | Triage deliverable produced end to end for at least one real or realistic task distribution, with sensitivity analysis. | `test_dod_8_triage_produced_end_to_end_with_sensitivity` | `deliverables/triage.html` (gitignored, CLIENT_CONFIDENTIAL — never `artifacts/`, per audit B2) — skips honestly until an engagement has actually been delivered |
| 9 | Public leaderboard deployed, with methodology, rubric, grader code, analysis scripts, raw results, changelog and right-of-reply process. | `test_dod_9_public_leaderboard_ships_its_whole_evidence_chain` | `artifacts/{leaderboard,verdicts_public,verdicts_private_by_hash,manifest_private}`, `docs/{methodology,rubric,corrections,analysis-plan}.md`, `CHANGELOG.md`, `.github/ISSUE_TEMPLATE/right-of-reply.yml` |
| 10 | Reproducibility test passes: published numbers regenerate from published data. | `test_dod_10_reproducibility_test_runs_and_does_not_skip` | `tests/test_reproducibility.py`, run with `GT_REQUIRE_DB=1` so a skip counts as a failure — a green tick here must have real assertions behind it |
| 11 | `docs/methodology.md` defines every term used in every published number. | `test_dod_11_methodology_defines_every_published_term` | `docs/methodology.md`, checked via `ground_truth.publish.leaderboard.assert_methodology_defines_every_term` |

## Why every test skips today, not fails

Two structural blockers, both already documented elsewhere in this repo, gate real completion:

1. **No live provider sweep has ever run** (blocked on the provider security audit). Without
   one, there is no real accuracy, cost, judge-agreement, or calibration data to publish —
   only the synthetic golden set and the hand-written placeholder artifacts used to build and
   test the web screens.
2. **`matrix/build.py`'s cost model** needed real per-call token counts before it could compute
   a non-placeholder cost figure; that gap was closed (`docs/methodology.md`, `CHANGELOG.md`),
   but closing it doesn't manufacture a sweep that hasn't happened.

`_require_release` (this test file's shared fixture) treats an `artifacts/` directory that
exists but is flagged `"placeholder": true` the same way it treats a missing one: an honest
skip, not a run against fabricated numbers. This mirrors the same convention already
established in `tests/test_reproducibility.py`'s `_only_placeholder_published` check.

## What "done" will look like

Once a real sweep runs and `ground_truth.publish.artifacts.emit_all` is invoked against real
data (Task 49 Steps 2–5, deferred alongside this task for the same reason):

1. `uv run pytest tests/test_definition_of_done.py -v` reports **11 passed**, not skipped.
2. This page is updated to record the pass and the date.
3. `git tag -a phase-3-published -m "Phase 3: regression watch, publication, web, DoD verified"`
   is cut and pushed — the one step in this file's history that is genuinely irreversible, and
   therefore genuinely gated on the eleven items being true, not merely testable.
