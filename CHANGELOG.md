# Changelog

Format based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

**Release rule:** numbers published here or in the leaderboard are never silently edited. A
corrected number appears as a **new dated entry**, with the superseded value shown struck
through -- e.g. `slot-a accuracy: ~~0.912~~ -> 0.897 [0.87, 0.92] n=180` -- so the history of
what this project claimed, and when it stopped claiming it, stays visible rather than
overwritten in place.

## [Unreleased]

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
