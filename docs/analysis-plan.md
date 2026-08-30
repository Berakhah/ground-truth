---
plan_version: v1
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

## Judge rejection threshold

**Krippendorff's alpha >= 0.667** (the conventional tentative-conclusions floor) is the pre-registered
threshold for judge-versus-human agreement, frozen here before any agreement number is computed.
Choosing a threshold after seeing the agreement data would be p-hacking.

Below threshold, the judge is barred from headline scoring for that field type: the field type
falls back to deterministic grading where one exists, or is published labelled *not measured*
rather than folded into a passing score. Every field type the judge touched is published,
including rejected ones — labelled rejected — so the published weakness always ships next to the
decision it caused.

## Sequential testing calendar

**Thirteen weekly looks per quarter, O'Brien-Fleming alpha-spending, re-registered every quarter.**
The calendar is declared in advance, once per quarter, and is not adjusted mid-quarter to
accommodate however the data happens to look at look 6.

The alpha-spending function is the Lan-DeMets O'Brien-Fleming closed form,
`alpha(t) = 2 * (1 - Phi(z_{alpha/2} / sqrt(t)))`, and the look boundary at information fraction
`t` is `C / sqrt(t)`, where **`C` is solved so the cumulative type-I error across all 13
correlated looks equals the nominal alpha** — `C` is not `z_{alpha/2}`.

For this pre-registered 13-look quarterly calendar, the calibrated boundary constant is
**`C = 2.1023`**, calibrated once by simulation over correlated Brownian trajectories and committed
together with that simulation as its own test. It must be used explicitly and never replaced by the
naive `z_{alpha/2} = 1.96`: substituting 1.96 spends nearly the full alpha budget at the earliest
interim looks and inflates the true type-I error of this 13-look calendar to **0.0721** against the
nominal **0.05** (audit finding B3, 2026-08-29) — a 2.3x understatement of how often the procedure
would falsely flag a regression. Requesting any other calendar length or alpha requires
recalibrating `C` by the same simulation; `C = 2.1023` is valid only for this exact calendar.

## Unscheduled looks

Any look at the data outside the pre-declared 13-per-quarter calendar **costs alpha and must be
declared in the changelog** before its result is used in any published or internal decision. An
undeclared unscheduled look invalidates the calendar's alpha-spending guarantee for the rest of the
quarter, because the O'Brien-Fleming boundary is calibrated for exactly 13 correlated looks — not
13 scheduled looks plus however many off-calendar peeks turned out to be convenient.
