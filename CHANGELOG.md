# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

**Release rule:** numbers published here or in the leaderboard are never silently edited. A
corrected number appears as a **new dated entry**, with the superseded value shown struck
through -- e.g. `slot-a accuracy: ~~0.912~~ -> 0.897 [0.87, 0.92] n=180` -- so the history of
what this project claimed, and when it stopped claiming it, stays visible rather than
overwritten in place.

## [Unreleased]

### Changed

- **2026-10-15 -- a re-grade counts once across graders and across schema re-checks.** A
  deterministic verdict is superseded by a later re-grade of the same output and field
  whichever deterministic grader wrote it, so a rubric that moves a field type to another
  grader no longer counts both graders' verdicts (~~superseded only by the same grader~~); a
  judge verdict is still superseded only by the same judge's. A deterministic verdict counts
  only while its output's latest schema verdict is correct, and the judged weight counts the
  same outputs (~~any correct schema verdict ever~~): an output re-graded as unparseable drops
  out of both, and counts again once re-graded as parseable. The judged weight then equals the
  number of verdicts each deterministic field has for the (item, slot) under any re-grade.
  Analysis plan v3 amended in place (no sweep has run). No live sweep exists, so no published
  figure changes.

- **2026-10-15 -- the judged weight counts schema-valid graded outputs only.** The judge's one
  verdict per (item, slot) is weighted by the number of schema-valid graded outputs of that
  (item, slot), which is the number of verdicts a deterministic field has for it
  (~~the number of replicate outputs stored~~); an output that failed schema validation or has
  not been graded counts for neither, and the weight is at least 1. Analysis plan v3 amended
  in place (no sweep has run).

- **2026-10-15 -- a judged field counts only once every current target is judged.** A judged
  field type counts only when every current judge target for it, across the ranked slots, has a
  verdict; while any is unjudged the field is out for every slot and the headline uses
  deterministic grading, like a rejected judge (a partial run would rank slots on different field
  sets). Inconclusive and not-extracted verdicts count as judged.

- **2026-10-15 -- a re-graded verdict supersedes the old one in the headline.** A verdict
  superseded by a later re-grade of the same output, field and grader no longer counts
  (~~both the old and the re-graded verdict counted~~); `counts_toward_headline` is false for it.

- **2026-10-15 -- judge wins on a judged field type (JP-1).** Where a judge's verdicts count on
  a field type, the headline scores the field from the judge alone; the field's older
  deterministic verdicts, left behind when a rubric moved the type to the judge, no longer count
  beside it (~~both counted, so the field was scored twice~~) and `counts_toward_headline` is
  false for them. Where the judge does not count (rejected, unassessed, unassigned, held back),
  deterministic grading still applies. Analysis plan v3 amended in place, after its merge: no
  sweep had run (`SELECT count(*) FROM runs` returned 0 on 2026-10-15). If one ran elsewhere
  this must become v4.

- **2026-10-15 -- open items left by the judge-publish merge are logged** in
  `docs/superpowers/reviews/2026-10-15-judge-publish-open-items.md` (JP-1 to JP-12). None is
  fixed. JP-1 (a field moved to the judge still counts its old deterministic verdicts) can
  affect published numbers.

- **2026-10-14 -- the LLM judge is wired in: analysis plan v3, judge decisions per (field type,
  judge).** `docs/analysis-plan.md` is now `plan_version: v3` (threshold 0.667 unchanged; v2's
  judge paragraph kept below). v2 governed zero sweeps (`SELECT count(*) FROM runs` on
  `data/results.duckdb` returned 0 on 2026-10-14).
  - `models.yaml` declares each slot's judge and it is validated, including family separation.
    Decided lineup: Gemma judges slots A-E, gpt-oss-120b judges the Gemini slot, both on
    Cerebras; Gemini is judged by a different model from the other five (disclosed
    comparability limit). The real `models.yaml` is not yet filled.
  - `run_judging` samples each slot's judge three times on the modal output per (item, slot);
    `grade` scores LINE_ITEM_DESCRIPTION from the majority vote (`grader_id` `judge:<slot>`).
    No majority is INCONCLUSIVE, which scores as incorrect.
  - Decisions are recorded per (field type, judge). A judge with no decision is not scored in
    the headline (~~an unassessed judge was scored~~); its verdicts are still published. Today
    every judge is undecided: `record_decision` has no production caller and there are no human
    labels, so LINE_ITEM_DESCRIPTION is reported as not measured in the headline.
  - Headline counts a judge verdict only from the slot's currently assigned judge, with an
    accepted decision for that field type, on the current modal target. Every published verdict
    carries `counts_toward_headline`; `judge_agreement.json` names each judge and gains an
    `inconclusive` list (count and n per slot and judge, over both splits and all judge
    verdicts, not the headline's judged share). The web judge table shows per-judge agreement
    and inconclusive counts.
  - Final-review rulings, added to v3 before merge: a judged field type counts toward any
    slot's headline only when every slot has an assigned judge and every slot's currently
    assigned judge holds an accepted decision for it, otherwise it is excluded for all slots;
    and the judge's one verdict per (item, slot) is weighted by the number of replicate outputs
    for that (item, slot), so the judged field weighs as much as one deterministic field at any
    run count (refined 2026-10-15, below). Every published verdict also carries `weight`, and
    `scripts/reproduce.py` recomputes a weighted mean per item.
  - Target order changed to run-major (runs in start order, then replicate, then output id), so
    targets judged under the older replicate-major order may move once in a multi-run store.
    No live sweep exists, so no published figure changes. `judge_decisions` changed shape:
    a local store with an old-shape `judge_decisions` table holding rows makes `migrate`
    refuse.

- **2026-09-29 -- the release job can pass: two-stage release gate.** `publish.yml` regenerated
  artifacts from `data/results.duckdb` and ran the DB-backed gates in CI, but that database is
  gitignored (it holds private-split outputs) and never exists on a runner, so no tag could
  ever pass, even after a real sweep. Now `python -m ground_truth.publish.release` emits the
  artifacts, runs the reproducibility and contamination gates where the database lives, and
  writes `artifacts/release.json` (each artifact's sha256, `as_of`, seed) only if they pass.
  CI runs `scripts/reproduce.py --require-release`, which refuses unattested, changed or
  missing files. `reproduce.py` also now refuses placeholder data and an empty leaderboard
  instead of passing vacuously; `emit_all` drops a stale `release.json`; the reproducibility
  gate reads `as_of` and seed from the published leaderboard instead of a hardcoded
  2026-10-15. No live sweep has run, so no release has been cut.

- **2026-09-27 -- constant-data intervals are two-sided 95%** (stats review 2026-09-27,
  finding 3). The exact Clopper-Pearson bound used when every observation is identical was
  one-sided, so it was not 95% on the same footing as the BCa intervals beside it. Now one
  shared helper (`stats.bootstrap.zero_count_upper_bound`) serves accuracy and judge alpha.
  Effect: 180/180 correct lower bound ~~0.9835~~ -> 0.9797; 0/180 upper bound ~~0.0165~~ ->
  0.0203; zero-disagreement alpha lower bound on the 60-unit test sample ~~0.8913~~ -> 0.8670.
  No release had published these figures.
- **2026-09-27 -- undefined judge alpha is published as undefined** (finding 4 and code
  review 2026-09-27). When judge and human give every unit one verdict, alpha is 0/0: it is
  now stored as NaN, published as JSON `null` with a statement giving the reason, and the
  field type is REJECTED. Previously this raised. In the alpha bootstrap, a 0/0 resample is
  now excluded (and counted in the interval's `method`) instead of being scored as 1.0, which
  had pulled upper bounds to 1.000 on class-imbalanced samples.
- **2026-09-27 -- regression-watch boundary wording** (finding 1). The sequential test's
  statement no longer prints an "alpha spent to date" figure (that was the Lan-DeMets function,
  not this fixed-C boundary's true spend) and states the family-wise guarantee instead.
  `docs/analysis-plan.md` still names Lan-DeMets and changes only with a `plan_version` bump.
  *Resolved 2026-09-28 by plan v2.*
- **2026-09-27 -- `detect_drift` requires cumulative input** (finding 2): one observation set
  per look from 1 to the current look, pooled internally; a wrong-length input raises.
  *Superseded 2026-09-28 by analysis plan v2, below.*
- **2026-09-28 -- regression watch: analysis plan v2, per-look Šidák test** (stats review
  2026-09-27 finding 1; code review 2026-09-27 #2 findings 1, 2, 7, 8, 10). Each look is now
  tested on its own sweep against the quarter's fixed baseline at `|z| > 2.8831`
  (~~O'Brien-Fleming `2.1023 / sqrt(t)` on data pooled across looks~~, which was 7.58 at look 1
  and diluted a mid-quarter change). Benjamini-Hochberg is applied to Šidák-adjusted p-values
  across cells. `detect_drift` takes this look's observations only. Alerts state the per-look,
  Šidák-adjusted and BH-adjusted p-values. The minimum detectable effect uses the per-look alpha,
  is Bonferroni-corrected across cells (it used alpha 0.05 and a family of one), and is computed
  from every replicate of the compared cohort (it used each item's last replicate, unfiltered).
  A look outside the calendar raises even when nothing is tested. Methodology figure: naive
  fixed-threshold error ~~0.2119~~ -> 0.334. `docs/analysis-plan.md` is now `plan_version: v2`
  with v1's text kept; v1 governed zero looks (no frozen plan, run or look existed).
  `artifacts/regression.json` placeholder alerts regenerated by running `detect_drift` on seeded
  synthetic data; the previous hand-written demo stated a z (3.41) its own intervals did not give
  (2.85). Follow-up review (code review 2026-09-27 #3): the regression-watch MDE now uses the
  standard error of the z test that decides detection (it quoted the paired McNemar formula,
  which describes a more powerful test and so overstated what a null look could see); p-values
  no longer underflow to 0 at large |z| and are printed to significant figures (a BH p printed
  as ~~0.0000~~); only the registered 13-look, alpha 0.05 calendar is accepted; a cell with no
  observations is refused by name instead of crashing the look.
- **2026-09-28 -- judge decisions publish what `assess` said** (code review 2026-09-27 #2).
  `judge_decisions` gains nullable `statement` and `alpha_method` columns, and
  `judge_agreement.json` publishes both on every row. The publisher no longer writes its own
  reason beside a null alpha; a row recorded before these columns existed says the reason was
  not recorded. The statement now discloses excluded 0/0 resamples and that the interval is
  conditional on alpha being defined. If no resample is defined the interval is published as
  not estimable (null bounds) and the judge is REJECTED; previously this raised `IndexError`.
  `emit_all` now writes into a staging directory and moves the files in only on success, so a
  failed publish no longer leaves new and stale artifacts mixed in the output directory.
- **2026-09-28 -- third review of the stats-audit fixes** (code review 2026-09-28, findings
  1-6 and 9). The earlier underflow fix held only for moderate drift: `norm.sf` is itself
  exactly 0 past |z| ~ 37.5, and a collapse from 180/180 to 3/180 published "p = 0" in all
  three p-value fields. The p-value is now clamped to the smallest positive float and any p
  below `1e-10` publishes as `p < 1e-10` (stated on the methodology page). A p-value that
  cannot be computed now raises instead of being Šidák-adjusted to 1.0 and reported as "No
  change detected". `detect_drift` checks for empty cells after the cohort filter and on both
  the baseline and current sides, naming every empty cell in one error. `emit_all` now swaps
  the whole output folder in (rename aside, rename in, roll back on failure) instead of
  moving files one at a time. It carries over `triage_example.json` (written there by
  `triage.export_example`), a committed `regression.json`, and folder metadata (`.gitkeep`,
  `.DS_Store`), and refuses before running the analysis, changing nothing, if the folder holds
  any other entry it does not write -- a stray file is neither republished nor deleted.
  Previously (since 5ada687) every publish overwrote the hand-committed regression-watch
  result with an empty stub; the stub is now written only when none is committed, and the
  reproducibility gate no longer compares that file, which is not regenerated from the
  results database. A failed rollback keeps the original exception and notes the folder
  holding the previous release. A cell whose z cannot be computed (NaN or infinite bound,
  zero-width pair) is refused by name, every such cell in one error, instead of aborting
  anonymously or publishing z = 0. The judge's "conditional on alpha being defined" caveat is
  decided from a counted `n_undefined_excluded`, not by searching the interval's `method`
  string.
  Methodology figure: naive fixed-threshold error ~~"about a third of quarters"~~ -> 0.334
  with a look-sized baseline to 0.487 with a noiseless one, assumption stated for each.
  Published shape: `leaderboard.json`'s `judge_agreement[].alpha_ci` gains
  `n_undefined_excluded` and `n_resamples`, on every row including undefined alpha. No
  committed artifact's contents change: none carries `alpha_ci`, and every p-value in the
  committed placeholders is above the floor.

### Added

- `ground_truth/publish/leaderboard.py`: `leaderboard_payload()` builds the published
  leaderboard JSON (versioned, dated, methodology-linked, every accuracy figure a full
  bootstrap `Interval`, never a bare point estimate). `required_terms()` and
  `assert_methodology_defines_every_term()` make DoD item 11 (a published definition for
  every term used) an executable check against `docs/methodology.md`.
- `ground_truth/publish/methodology.py`: renders `docs/methodology.md` to HTML with a "Live
  figures" section injecting current `n`, the MDE sentence, the intra-rater disagreement
  rate, judge agreement statements, and fingerprint statements -- each one honestly labelled
  "not yet measured" when not supplied, never silently omitted.
- `docs/methodology.md`: added a `## Scope` section stating the corpus population (synthetic,
  not real pay applications, external validity unmeasured -- audit M1) and a `## Definitions`
  section defining all 17 terms the published leaderboard relies on.
- `docs/corrections.md`, `.github/ISSUE_TEMPLATE/right-of-reply.yml`, `SECURITY.md`: the
  right-of-reply process -- two dispute channels, 5/15-business-day response windows, a
  10-business-day advance-notice rule for any regression or drift finding naming a provider,
  the three possible outcomes (correction, clarification, no change), and the standing offer
  to re-run under a provider-stated configuration and publish both results side by side.
