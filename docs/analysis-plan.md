---
plan_version: v3
status: frozen-before-first-sweep
---

# Ground Truth Pre-Registered Analysis Plan

This plan commits to the statistical methodology used to score every evaluation sweep, before any
sweep runs and before any number exists. It is enforced, not merely asserted: `freeze_plan` records
this file's content hash and freeze timestamp in the `analysis_plan` table, and
`assert_frozen_before_first_sweep` raises if any run's `started_at` predates that freeze. A sweep
that runs before this plan is frozen invalidates every downstream number it produces, because the
methodology could otherwise be chosen — or quietly adjusted — after seeing results that make the
number look better. Changing a procedure below after freezing requires a new `plan_version`, never
a silent edit of `v1`.

## Primary metric

Per-field accuracy on the **private split** of the golden set. The public split exists for
reproducibility of methodology and tooling; headline numbers are always computed against the
private, never-published split.

## Unit of analysis

The **item**, not the `(item, replicate)` row. Each item is run with n>=5 replicates at
temperature zero, because temperature zero is not determinism. Replicates are clustered under
their parent `item_id` in every interval and every hypothesis test that follows. Treating each
replicate as an independent observation understates every interval by roughly `sqrt(5)`, producing
narrow, confident-looking numbers that are not honest — the exact failure this project is sold
against, arriving from inside its own statistics code.

## Confidence intervals

**Cluster BCa (bias-corrected and accelerated) bootstrap, 10,000 resamples, 95% confidence.**
Resampling draws whole item clusters (an item and all of its replicates together), never
individual replicate rows, so the resampled data preserves the clustering structure of the
original sweep.

## Multiplicity correction

**Benjamini-Hochberg, false discovery rate 0.05**, applied across the full family of
`(model_slot, field_type)` comparisons in a sweep. Every alert or headline comparison carries the
family it was corrected against, so a reader can see which other comparisons its significance was
adjusted for.

## Minimum detectable effect — multiplicity treatment

MDE calculations use **Bonferroni alpha/m**, not Benjamini-Hochberg, across the same comparison family.
This is deliberately more conservative than BH: BH's effective per-comparison threshold is
data-dependent and unknowable in advance, so it cannot be used to plan a sample size before the
data exists. The conservative choice is stated as such wherever an MDE figure is published, not
hidden behind a single number.

For the regression watch, the alpha divided across the family is the per-look alpha, 0.003938
(see "Sequential testing calendar"), and the sample is one look's sweep: the MDE describes what
a single look can see, which is what each look's test is run on.

## Judge rejection threshold

**Krippendorff's alpha >= 0.667** (the conventional tentative-conclusions floor) is the pre-registered
threshold for judge-versus-human agreement, frozen here before any agreement number is computed.
Choosing a threshold after seeing the agreement data would be p-hacking.

The decision unit is the **(field type, judge)** pair, not the field type alone: each judge is
assessed against human labels separately, and its decision is recorded and published under its
own name. Below threshold, that judge is barred from headline scoring for that field type: the
field type falls back to deterministic grading where one exists, or is published labelled *not
measured* rather than folded into a passing score. Every (field type, judge) pair the judge
touched is published, including rejected ones -- labelled rejected -- so the published weakness
always ships next to the decision it caused.

- A judge with no recorded decision is not used for headline scoring. Unassessed is not
  accepted: a judge whose agreement has not been measured cannot be defended.
- An INCONCLUSIVE verdict (no majority among the judge's samples) scores as incorrect, and its
  count is published per (model slot, judge).
- The judge scores the modal output per (item, slot), not every replicate.
- LINE_ITEM_DESCRIPTION's run-to-run variance is therefore not measured by the judge: the
  judge sees one output per (item, slot), and the replicate spread the deterministic graders
  report for other fields does not exist for this one.
- In an item's score, the judged verdict weighs as many times as the (item, slot) has
  schema-valid graded outputs, across all its runs, which is the number of verdicts a
  deterministic field has for it; an output that failed schema validation or has not been
  graded counts for neither. (At least once, if every output failed.) An output is
  schema-valid when its latest schema verdict is correct. Unweighted, an item with two
  deterministic fields and five replicates gave the judged field 1/11 of the score instead of
  1/3, shrinking with every run added. The published verdict files carry each verdict's
  `weight` so the headline recomputes from them.
- Re-grades: verdicts are append-only, and the latest verdict wins (latest `computed_at`, the
  greater verdict id on a tie). A deterministic verdict is superseded by a later one on the
  same output and field from any deterministic grader, so a rubric that moves a field type to
  another grader counts the field once; a judge verdict is superseded only by the same judge's.
  A deterministic verdict counts only while its output's latest schema verdict is correct, so
  an output re-graded as unparseable drops out of the deterministic fields and the judged
  weight together, and returns to both if re-graded as parseable. The judged weight therefore
  equals the number of verdicts each deterministic field has for the (item, slot).
- One field set per leaderboard: a judged field type counts toward any slot's headline only
  when every slot ranked in the split has an assigned judge, and every slot's currently
  assigned judge holds an accepted decision for that field type. Otherwise the field type is
  excluded for all slots alike, so no two slots' intervals are compared over different fields.
- Judging must be complete: a judged field type counts only when every current judge target for
  it in the split, across the ranked slots, has a verdict. While any target is unjudged, the
  field type is dropped for every slot and the headline falls back to deterministic grading, as
  for a rejected judge. Reason: a partial run would rank slots on different field sets (one slot
  on more judged items than another). Dropping rather than refusing keeps a mid-sweep build
  runnable. An inconclusive or not-extracted verdict counts as judged.
- Judge wins: on a field type whose judge verdicts count under the rules above, the judge's
  verdict is the field's only score; the field's deterministic verdicts, left in the
  append-only store by a rubric that moved the field type to the judge, do not count beside it.
  Where the judge does not count (rejected, unassessed, unassigned, or held back as incomplete)
  nothing is dropped, so the field type falls back to deterministic grading as above. A
  decision never removes a deterministic verdict by itself; the judge counting does.

## Sequential testing calendar

**Thirteen weekly looks per quarter, each tested on its own data against a fixed baseline, with
a Šidák per-look boundary of `|z| > 2.8831`, re-registered every quarter.** The calendar is
declared in advance, once per quarter, and is not adjusted mid-quarter to accommodate however
the data happens to look at look 6.

**Baseline.** Each quarter has one baseline: a registration sweep of the same anchor items at the
same replicate count, run before look 1 and fixed for the whole quarter. It is never replaced
mid-quarter -- a baseline that moved with the data would absorb the drift it exists to detect.

**Each look is tested on that look's sweep alone**, never pooled with earlier looks. A silent
provider update is a change at one point in time; pooling every look since the start of the
quarter treats it as an effect present from look 1, so a model swapped at look 10 is diluted by
nine looks of the old model and the test sees about a quarter of the real drop.

**Per-look boundary.** Within one `(model_slot, field_type)` cell, the 13 looks are a family of
13 two-sided tests. Each is run at the Šidák per-look level
`alpha_look = 1 - (1 - 0.05)^(1/13) = 0.003938`, whose two-sided critical value is
**`|z| > 2.8831`**. Šidák's inequality holds for two-sided tests on any multivariate normal, so
the family-wise type-I error across the 13 looks is at most 0.05 whatever the correlation
between looks. The shared baseline makes the looks positively correlated, which makes the
bound conservative: the null simulation committed with this plan measures 0.0501 (exactly 0.05 in theory; Monte Carlo error about ±0.0003) with no
baseline noise and 0.0381 when the baseline is as noisy as one look.

**How the corrections stack.** Each cell's per-look p-value is Šidák-adjusted across the
13-look calendar, `p_adj = 1 - (1 - p)^13`; Benjamini-Hochberg at FDR 0.05 is then applied to
those adjusted p-values across every cell tested at that look. A change is reported only when
its BH-adjusted p is at or below 0.05. With a single cell this is exactly `|z| > 2.8831`.
Every alert states the per-look p, the Šidák-adjusted p, and the BH-adjusted p with the size
of the family it was corrected against. The 13-look family resets each quarter.

**What this cannot see.** A per-look test has one sweep's worth of data, so it has less power
against a small drift that persists across many looks than a test that pools them. Every null
result publishes its minimum detectable effect, computed for one look's sample at the per-look
alpha and Bonferroni-corrected across the cells in the family (see "Minimum detectable effect").

## Unscheduled looks

Any look at the data outside the pre-declared 13-per-quarter calendar **costs alpha and must be
declared in the changelog** before its result is used in any published or internal decision. The
per-look boundary divides the quarter's 0.05 across exactly 13 tests; a 14th test is outside that
budget, so an undeclared unscheduled look invalidates the calendar's family-wise guarantee for the
rest of the quarter.

## Revision history

- **v3, 2026-10-14 -- judge decisions per (field type, judge).** v2 decided agreement once per
  field type. The judge is now wired into grading, and no available judge family differs from
  all six model slots, so two judges are used (the decided lineup, `docs/providers.md`
  "Lineup decisions" and the judge-wiring plan of 2026-10-14: Gemma judges slots A-E and
  gpt-oss-120b judges the Gemini slot, both served on Cerebras; `models.yaml` is not yet filled
  with the real assignment). Gemini is therefore judged by a different model from the other
  five, a disclosed comparability limit. Each judge is assessed against human labels and
  accepted or rejected on its own; a judge with no recorded decision is not scored; INCONCLUSIVE
  scores as incorrect and is counted. The 0.667 threshold is unchanged. **v2 governed zero
  sweeps:** on 2026-10-14 `SELECT count(*) FROM runs` on `data/results.duckdb` returned 0. This
  change is therefore made before any data exists. v2's judge paragraph is kept below,
  unedited. **v3 amended before merge, 2026-10-14:** the final review of the judge-wiring
  branch found two headline rules missing, and both were added to v3's judge section in the
  same unmerged branch rather than as a v4: the judge's verdict is weighted by the number of
  replicate outputs for its (item, slot), and a judged field type counts only when every
  slot's currently assigned judge holds an accepted decision for it. v3 had governed no sweep
  and had never been merged when it was amended, so no data could have informed the change.
  **v3 amended again 2026-10-15 (runs = 0, no sweep under v3),** still before merge, by the
  same branch's later reviews: (a) the judged weight is the number of schema-valid graded
  outputs of the (item, slot), schema validity read from each output's latest schema verdict,
  not the number of stored replicate outputs; (b) completeness: a judged field type is dropped
  for every slot while any current judge target for it in the split has no verdict from the
  slot's current judge; (c) re-grade supersession: the latest verdict wins, across
  deterministic graders for a deterministic field and per judge for a judge verdict, and a
  deterministic verdict counts only while its output's latest schema verdict is correct.
  `SELECT count(*) FROM runs` on `data/results.duckdb` still returned 0 on 2026-10-15.
  **v3 amended a third time 2026-10-15, after the v3 merge (runs = 0, no sweep under v3):**
  judge wins -- on a field type whose judge counts, the judge's verdict is the only score and
  the field's older deterministic verdicts do not count beside it (open item JP-1, decided by
  the project owner). This amendment is post-merge, unlike the two above; it is still made in
  place only because `SELECT count(*) FROM runs` on `data/results.duckdb` returned 0 when it was
  made, so no data could have informed it. If a sweep ran elsewhere, this must become a v4.
- **v2, 2026-09-28 -- sequential testing calendar replaced.** v1 tested a z computed on data
  pooled across looks against the fixed-constant O'Brien-Fleming boundary `C / sqrt(t)`,
  `C = 2.1023`. Two problems (stats review 2026-09-27, finding 1, and code review 2026-09-27
  #2): the pooled z dilutes a change that starts mid-quarter, and the boundary is nearly blind
  early, `2.1023 / sqrt(1/13) = 7.58` at look 1. v1 also named the Lan-DeMets spending function
  as the spending rule, which is not the true spend of a fixed-C boundary. **v1 governed zero
  looks:** on 2026-09-28 the results store held no frozen plan, no sweep run and no recorded
  look, and `detect_drift` had no production caller. This change is therefore made before any
  data exists. v1's text is kept below, unedited.

### Superseded: v2 "Judge rejection threshold" (decision unit: field type)

> The v2 text follows exactly as frozen, for the record. It does not govern any sweep.

> **Krippendorff's alpha >= 0.667** (the conventional tentative-conclusions floor) is the pre-registered
> threshold for judge-versus-human agreement, frozen here before any agreement number is computed.
> Choosing a threshold after seeing the agreement data would be p-hacking.
>
> Below threshold, the judge is barred from headline scoring for that field type: the field type
> falls back to deterministic grading where one exists, or is published labelled *not measured*
> rather than folded into a passing score. Every field type the judge touched is published,
> including rejected ones — labelled rejected — so the published weakness always ships next to the
> decision it caused.

### Superseded: v1 "Sequential testing calendar" and "Unscheduled looks"

> The v1 text follows exactly as frozen, for the record. It does not govern any look.

> ## Sequential testing calendar
>
> **Thirteen weekly looks per quarter, O'Brien-Fleming alpha-spending, re-registered every quarter.**
> The calendar is declared in advance, once per quarter, and is not adjusted mid-quarter to
> accommodate however the data happens to look at look 6.
>
> The alpha-spending function is the Lan-DeMets O'Brien-Fleming closed form,
> `alpha(t) = 2 * (1 - Phi(z_{alpha/2} / sqrt(t)))`, and the look boundary at information fraction
> `t` is `C / sqrt(t)`, where **`C` is solved so the cumulative type-I error across all 13
> correlated looks equals the nominal alpha** — `C` is not `z_{alpha/2}`.
>
> For this pre-registered 13-look quarterly calendar, the calibrated boundary constant is
> **`C = 2.1023`**, calibrated once by simulation over correlated Brownian trajectories and committed
> together with that simulation as its own test. It must be used explicitly and never replaced by the
> naive `z_{alpha/2} = 1.96`: substituting 1.96 spends nearly the full alpha budget at the earliest
> interim looks and inflates the true type-I error of this 13-look calendar to **0.0721** against the
> nominal **0.05** (audit finding B3, 2026-08-29) — a 2.3x understatement of how often the procedure
> would falsely flag a regression. Requesting any other calendar length or alpha requires
> recalibrating `C` by the same simulation; `C = 2.1023` is valid only for this exact calendar.
>
> ## Unscheduled looks
>
> Any look at the data outside the pre-declared 13-per-quarter calendar **costs alpha and must be
> declared in the changelog** before its result is used in any published or internal decision. An
> undeclared unscheduled look invalidates the calendar's alpha-spending guarantee for the rest of the
> quarter, because the O'Brien-Fleming boundary is calibrated for exactly 13 correlated looks — not
> 13 scheduled looks plus however many off-calendar peeks turned out to be convenient.
