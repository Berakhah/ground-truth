# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

**Release rule:** numbers published here or in the leaderboard are never silently edited. A
corrected number appears as a **new dated entry**, with the superseded value shown struck
through -- e.g. `slot-a accuracy: ~~0.912~~ -> 0.897 [0.87, 0.92] n=180` -- so the history of
what this project claimed, and when it stopped claiming it, stays visible rather than
overwritten in place.

## [Unreleased]

### Changed

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
- **2026-09-27 -- `detect_drift` requires cumulative input** (finding 2): one observation set
  per look from 1 to the current look, pooled internally; a wrong-length input raises.
- **2026-09-28 -- judge decisions publish what `assess` said** (code review 2026-09-27 #2).
  `judge_decisions` gains nullable `statement` and `alpha_method` columns, and
  `judge_agreement.json` publishes both on every row. The publisher no longer writes its own
  reason beside a null alpha; a row recorded before these columns existed says the reason was
  not recorded. The statement now discloses excluded 0/0 resamples and that the interval is
  conditional on alpha being defined. If no resample is defined the interval is published as
  not estimable (null bounds) and the judge is REJECTED; previously this raised `IndexError`.
  `emit_all` now writes into a staging directory and moves the files in only on success, so a
  failed publish no longer leaves new and stale artifacts mixed in the output directory.

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
