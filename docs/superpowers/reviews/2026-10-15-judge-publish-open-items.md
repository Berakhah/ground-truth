# Judge-publish blockers: open items at merge (2026-10-15)

Logged when `judge-publish-blockers` merged to main (`9c19864`). The four blockers themselves are
fixed (see CHANGELOG 2026-10-15). These are what the final review and the merge left open. Ids are
`JP-n` to keep them apart from the 2026-08-29 audit's B/H/M numbering.

Status key: **open** = nothing done yet. Nothing here is fixed.

## Affects published numbers

### JP-1: a field moved from a deterministic grader to the judge counts both sets of verdicts

- **Status:** open. Predates the branch.
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

- **Status:** open.
- **Where:** `ground_truth/grade.py`.
- **Problem:** re-grading at a grader version that was already used writes no new verdicts. If an
  output later fails its schema check, the earlier field verdicts stay and the output stays
  excluded by the schema gate, with no way to reinstate it short of a grader version bump.
- **Next:** decide whether a schema re-check should write a verdict regardless of grader version.

## Test and documentation gaps

### JP-3: the moved-modal-target test does not protect the hold-back logic

- **Status:** open.
- **Where:** `tests/matrix/test_build.py`.
- **Problem:** the test passes even if the hold-back logic is broken. Only the reassigned-judge
  test exercises it. The behaviour is therefore covered once, not twice.
- **Next:** make it fail first by breaking the logic on purpose, then fix the fixture.

### JP-4: `docs/methodology.md:315` is narrower than the code

- **Status:** open.
- **Problem:** the text says a deterministic verdict does not count when the latest schema check
  *failed*. The code also excludes a deterministic verdict with *no* schema verdict at all. Grading
  cannot currently produce that state, so nothing is wrong today, but the document and the code
  disagree about the rule.
- **Next:** change the sentence, or make the code match it.

## Process

### JP-5: Python changes in `matrix/build.py` have had no security review

- **Status:** open.
- **Problem:** CLAUDE.md requires `security-review` for publish steps touching `golden/`, `triage/`
  or the private split. The review run on 2026-10-15 covered `publish.yml`, `web/lib/fixtures.ts`
  and the fixture pages only, and found nothing. The weighting and completeness-gate code in
  `matrix/build.py` was not reviewed.

### JP-6: web package is on Next 16.3.4; CLAUDE.md says Next 15

- **Status:** open, needs a decision.
- **Options:** update CLAUDE.md to say 16, or pin `web/` back to 15.

## Deferred hardening (accepted for now)

- **JP-7:** the publish gate matches the `data-gt-fixture` marker only. A new fixture page with no
  guard and no marker would pass. Add a note to the publish docs, or a test that every route
  under `web/app/**/*-example` calls `requireFixtureRoute()`.
- **JP-8:** the same marker grep is not in `ci.yml`, so a removed guard is caught only at a `v*`
  tag.
- **JP-9:** no defensive field-type check in the completeness helper.
- **JP-10:** `select_judge_targets` runs twice per build.
- **JP-11:** analysis plan v3 was amended in place because `data/results.duckdb` held 0 runs on
  2026-10-15. If a sweep ran on another machine, the amendment must become a v4.
- **JP-12:** the completeness gate drops a half-judged field type rather than refusing to publish,
  so a half-judged run publishes quietly without that field. Chosen deliberately; revisit if the
  quiet drop causes a surprise.
