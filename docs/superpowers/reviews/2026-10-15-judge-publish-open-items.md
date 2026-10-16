# Judge-publish blockers: open items at merge (2026-10-15)

Logged when `judge-publish-blockers` merged to main (`9c19864`). The four blockers themselves are
fixed (see CHANGELOG 2026-10-15). These are what the final review and the merge left open. Ids are
`JP-n` to keep them apart from the 2026-08-29 audit's B/H/M numbering.

Status key: **open** = nothing done yet. Nothing here is fixed.

## Affects published numbers

### JP-1: a field moved from a deterministic grader to the judge counts both sets of verdicts

- **Status:** fixed 2026-10-15 ("judge wins", decided by the project owner): where a judge counts
  on a field type, its deterministic verdicts no longer count. Cut as analysis plan v4 (v3, already
  merged, is left unedited; runs = 0), methodology and CHANGELOG updated. The text below is the original
  finding.
- **Where:** `ground_truth/matrix/build.py`, the headline verdict selection.
- **Problem:** the branch dedupes a re-grade across *deterministic* graders (latest verdict per
  output and field). A deterministic verdict does not compete with a `judge:<slot>` verdict, so a
  field type that moves from a deterministic grader to the judge keeps its old deterministic
  verdicts beside the judge's. The field is scored twice, with two judgements that can disagree.
- **Why it matters:** the leaderboard weights would be wrong for that field type, silently.
- **Next:** failing test first (TDD). Decide the rule: a field type with a judged grader retires its
  deterministic verdicts, or the reverse. That is a methodology decision, so it needs an entry in
  `docs/methodology.md` and the analysis plan.

### JP-2: re-grading at an already-used grader version writes nothing

- **Status:** fixed 2026-10-16 (decided by the project owner: keep append-only, fail loudly). A
  deterministic re-grade that disagrees with the stored verdict at the same grader version keeps
  the stored verdict and raises `GradingConflict` after the pass, naming each verdict; a version
  bump records the new answer. Judge verdicts are exempt (they change legitimately with more
  samples). The original finding follows.
- **Where:** `ground_truth/grade.py`.
- **Problem:** re-grading at a grader version that was already used writes no new verdicts. If an
  output later fails its schema check, the earlier field verdicts stay and the output stays
  excluded by the schema gate, with no way to reinstate it short of a grader version bump.
- **Next:** decide whether a schema re-check should write a verdict regardless of grader version.

## Test and documentation gaps

### JP-3: the moved-modal-target test does not protect the hold-back logic

- **Status:** fixed 2026-10-16. The test now adds a fully judged second item, so the type would
  count if nothing held it back; it passes as written and fails with the hold-back filter
  disabled (checked by mutation). The original finding follows.
- **Where:** `tests/matrix/test_build.py`.
- **Problem:** the test passes even if the hold-back logic is broken. Only the reassigned-judge
  test exercises it. The behaviour is therefore covered once, not twice.
- **Next:** make it fail first by breaking the logic on purpose, then fix the fixture.

### JP-4: `docs/methodology.md:315` is narrower than the code

- **Status:** fixed 2026-10-16. The sentence now says a deterministic verdict counts only while
  its output's latest schema verdict is correct, so a missing one excludes it too. No code change;
  the rule was already enforced that way. The original finding follows.
- **Problem:** the text says a deterministic verdict does not count when the latest schema check
  *failed*. The code also excludes a deterministic verdict with *no* schema verdict at all. Grading
  cannot currently produce that state, so nothing is wrong today, but the document and the code
  disagree about the rule.
- **Next:** change the sentence, or make the code match it.

## Process

### JP-5: Python changes in `matrix/build.py` have had no security review

- **Status:** done 2026-10-16, no findings. A read-only review of
  `git diff 5b6cab7..eae2971` for `matrix/build.py`, `publish/artifacts.py` and
  `scripts/reproduce.py` found no SQL injection (the f-strings interpolate only a literal
  constant; the split is bound), no private-split leak (public and private verdict files each
  use their own split, and the new `counts_toward_headline` and `weight` fields add only a bool
  and an int to already-published rows), and no path or deserialisation issue in
  `reproduce.py`. It read the code and did not run the tests. It noted `weight` reveals, per
  private hash, the count of schema-valid outputs, which is already inferable from published
  rows. The original finding follows.
- **Problem:** CLAUDE.md requires `security-review` for publish steps touching `golden/`, `triage/`
  or the private split. The review run on 2026-10-15 covered `publish.yml`, `web/lib/fixtures.ts`
  and the fixture pages only, and found nothing. The weighting and completeness-gate code in
  `matrix/build.py` was not reviewed.

### JP-6: web package is on Next 16.3.4; CLAUDE.md says Next 15

- **Status:** resolved 2026-10-16. CLAUDE.md now says Next.js 16.
- **Decision:** keep `web/` on 16.3.4 rather than pin back to 15. The Playwright and axe suites pass
  on 16.3.4, and a downgrade would put the web package at risk for no benefit. Older specs and plans
  under `docs/superpowers/` still say 15; they are dated records and were left as written.

## Deferred hardening (accepted for now)

- **JP-7:** fixed 2026-10-16. `tests/test_fixture_routes.py` requires every
  `web/app/**/*-example/page.tsx` to call `requireFixtureRoute()` and carry the marker, and the
  guard to be called nowhere else (checked by adding a rogue unguarded route: it failed). Original
  finding: the publish gate matches the `data-gt-fixture` marker only, so a new fixture page with
  no guard and no marker would pass.
- **JP-8:** fixed 2026-10-16. The same marker scan now runs in the `ci.yml` web job right after the
  build, before Playwright. Not yet run on GitHub Actions; the first push shows it. Original
  finding: a removed guard was caught only at a `v*` tag.
- **JP-9:** fixed 2026-10-16 (reversing the earlier deferral). `_unjudged_field_types` selects
  targets by field name, so a name declared as another type on another item reached its target and
  could list that type as "judging incomplete". It now keeps only targets whose own item declares
  a judged type in play. Original finding: no defensive field-type check in the completeness
  helper.
- **JP-10:** fixed 2026-10-16 (reversing the earlier deferral). `_headline_selection` builds a
  per-selection memo, so `select_judge_targets` runs once per field name instead of twice.
  Original finding: it ran twice per build.
- **JP-11:** analysis plan v3 was amended in place because `data/results.duckdb` held 0 runs on
  2026-10-15. If a sweep ran on another machine, the amendment must become a v4.
- **JP-12:** fixed 2026-10-16 (decided by the project owner: keep the drop, say so). The drop
  stays, but `leaderboard.json` now lists the held-back field types with a reason
  (`held_back_field_types`) and the leaderboard page prints them. Type name and fixed reason only,
  no private-split detail. Original finding: the completeness gate drops a half-judged field type
  rather than refusing to publish, so a half-judged run published quietly without that field.
  Security review (2026-10-16, JP-12 plus the JP-2 `grade.py` change): no finding at or above the
  8/10 confidence bar. Read-only review of the changed files, no tests run. It confirmed that
  `held_back_field_types` carries only the `FieldType` enum value and one of two fixed reasons, and
  that the new SQL is fully parameterised.
