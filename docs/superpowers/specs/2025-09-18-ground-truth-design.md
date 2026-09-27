# Ground Truth — Design

**Status:** approved 2025-09-18 · **Phase:** weeks 21–26 · **Repo:** `ground-truth`
**Sources of truth:** `../Starting_Documents/00-SHARED-FOUNDATION.md`, `../Starting_Documents/04-GROUND-TRUTH.md`, `../ledger-sense/CLAUDE.md`
**Capacity assumption:** 35–40 h/week, six weeks, one person.

---

## 1. Decisions register

Every decision below is closed. Re-opening one is a design change, not an implementation detail.

### From `04` §13

| # | Decision | Answer |
|---|---|---|
| Q1 | Ledger Sense design partner and labelled corpus? | **Not assumed.** Plan stands alone on a synthetic golden set as the default. A real labelled corpus is a documented upgrade, never a blocker. *Confirmed delivered 2026-09-23: `golden/corpus` and `golden/manifest_{public,private}.json` exist and stand alone — no Ledger Sense corpus was substituted.* |
| Q2 | Own the runner, or adopt `inspect-ai` / `promptfoo`? | **Own a thin executor** (~200 lines). Adopting duplicates `bok-core`'s gateway, cache and ledger, which breaks R7 fingerprint tracking, and version-couples the published methodology to a third party's semantics. |
| Q3 | Leaderboard of models, or of vendor products? | **Models only.** Lower exposure, no ToS benchmark-publishing risk, and the only form that yields calibration curves Ledger Sense can consume. |
| Q4 | Private split size and rotation? | **300 items: 120 public / 180 private (40/60).** Rotate 20% of private (36 items) at each published release, minimum quarterly. Growth path to 500 in the regression phase. |
| Q5 | Publish where the judge is weak? | **Yes, with a pre-registered rejection threshold** (Krippendorff's α ≥ 0.667). Field types below it are barred from headline scoring and appear in the published table labelled *rejected*. |
| Q6 | Triage sellable standalone in week 22? | **Yes — sequenced first.** Weeks 21–22 build the harness spine in client-facing order. *Confirmed delivered 2026-09-23: a built, standalone `triage.html` exists in the static web export (`web/out/triage.html`), independently of the harness sweep.* |
| Q7 | Right-of-reply process? | Public GitHub issue template (`right-of-reply`) plus a `corrections@` alias; outcome published either way. **Acknowledge in 5 business days, resolve in 15.** No advance notice for routine scores; **10 business days' notice for any regression/drift finding naming a provider.** Standing re-run offer, both results published side by side. |

### From `00` §12 (cross-cutting — carry to the other three sessions)

| # | Decision | Answer |
|---|---|---|
| Q1 | Publish or vendor `bok-core` / `bok-ui`? | **Publish.** PyPI and npm. |
| Q2 | Unified `bok` CLI or four independent? | **Four independent.** Ground Truth ships **no** `[project.scripts]` entry; dev entrypoint is `python -m ground_truth.<module>`. Only `agent-perimeter` ships a real CLI. |
| Q3 | Which providers, on what terms? | **Unknown — audit is week-21 task 1.** Design assumes six provider-agnostic lane slots. No provider is named anywhere in this repo. |
| Q4 | Supabase, or compose-only? | **Compose-only, self-hosted.** No third-party data processor. Ground Truth needs no Postgres at all and drops that service from the template compose file. |
| Q5 | Public from commit one, or at first release? | **Public from commit one, all four.** For this project the git history is load-bearing evidence (§5.2). |
| Q6 | Apache-2.0 or AGPL? | **Apache-2.0 everywhere.** |
| Q7 | Capacity? | 35–40 h/week; weeks 21–26. |

### Architecture

**Two-phase: execute, then analyse.** `runner.py` calls models and stores raw outputs, grading nothing. Graders are pure functions with no I/O. Every analysis module reads DuckDB.

---

## 2. Scope, and the non-goal enforced in code

Ground Truth is three things and nothing else:

1. a **vertical harness** for one task — pay-application and invoice field extraction;
2. a **public decision artifact** — a models leaderboard with a stated, reproducible methodology;
3. a **paid diagnostic** — the triage report.

### 2.1 Non-goals

No plugin system. No generic task abstraction. No multi-tenant SaaS. No "bring your own eval". No observability product. No prompt management.

### 2.2 Enforcement

Prose does not enforce. `tests/test_non_goals.py` runs in CI on every commit:

| Test | Assertion | Failure message |
|---|---|---|
| `test_item_schema_is_closed` | `FieldType` contains exactly the eight enumerated types in §5.1 | "The item schema is closed. Adding a field type is a scope decision, not a code change." |
| `test_no_task_registry` | AST scan across `ground_truth/`: no `entry_points`, no `importlib.metadata`, no `register(`, no module-scope `dict[str, Callable]` | "A task registry is the platform trap arriving — stop and escalate." |
| `test_graders_are_pure` | AST scan of `graders/deterministic/`: no import of `httpx`, `requests`, `open`, or `bok_core.gateway` | "Graders are phase-2 pure functions. I/O here breaks degraded mode and reproducibility." |

Additionally, **every task in the implementation plan carries this line in its verification block:**

> *Did this task add an abstraction whose second implementation does not exist? If yes, stop and report before continuing.*

---

## 3. Architecture — two phases

```
PHASE 1  EXECUTE  (needs providers)
  runner.py
    for each (item x model_slot x replicate 1..5):
      handle = bok_core.gateway.lanes.resolve(slot)      # never a model name
      response = handle.call(prompt, cache=DISABLED)      # see section 12
      append to outputs(raw_output, ledger_call_id, provider_served,
                        fingerprint, latency_ms, prompt_hash, observed_at)
    judge sampling writes judge_samples(presentation_order, raw_judgement, ledger_call_id)
  Grades nothing. Computes nothing. Ranks nothing.

PHASE 2  ANALYSE  (needs no providers, ever)
  graders/    (item, raw_output) -> Verdict         pure, no I/O
  stats/      bootstrap, agreement, correction, sequential, mde
  matrix/     cost (list price), latency (distribution)
  calibrate/  isotonic / Platt, export
  regression/ drift detection over a time window
  triage/     expected value, sensitivity, report
  publish/    leaderboard, methodology, artifacts
```

Four required behaviours are **consequences of this split**, not features to maintain:

- **Degraded mode is the normal path.** `test_degraded_mode_still_produces_findings` runs phase 2 with every provider disabled. No second code path exists to be tested.
- **Reproducibility is a phase-2 rerun.** Publish phase-2 inputs plus the analysis script; a sceptic regenerates every headline number without one model call.
- **A rubric or grader fix costs zero calls.** On a 9,000-call sweep spanning multiple overnight runs, re-grading stored outputs is the difference between an afternoon and three days.
- **Judge bias controls are unit-testable with no network.** The judge's n>=3 samples are phase-1 executions; majority vote, order-effect testing and length-effect reporting are phase-2 pure functions.

---

## 4. Module layout

```
ground_truth/
  store/        db.py            DuckDB schema + migrations
                models.py        Pydantic v2 models
  golden/       schema.py        Item, ItemField, FieldType
                rubric.py        rubric versioning + freeze
                generate.py      synthetic corpus (see section 5.3)
                splits.py        public/private assignment
                manifest.py      hash manifests
  graders/
    deterministic/  exact.py numeric_tolerance.py normalised.py schema.py arithmetic.py
    judge/          prompt.py aggregate.py agreement.py
  runner.py     phase 1, ~200 lines
  stats/        bootstrap.py agreement.py correction.py sequential.py mde.py
  matrix/       cost.py latency.py build.py
  calibrate/    curves.py export.py
  regression/   detect.py fingerprint.py schedule.py
  triage/       ingest.py expected_value.py sensitivity.py report.py
  publish/      leaderboard.py methodology.py artifacts.py
web/            Next.js 15, output: 'export'
docs/           methodology.md rubric.md analysis-plan.md providers.md
                non-goals.md security.md
tests/
data/results.duckdb
golden/corpus/public/     committed
golden/corpus/private/    gitignored - manifest only
```

Two deliberate deviations from `04` §6: `runner/` collapses to `runner.py` (a package directory for one file is scaffolding), and `store/` is added so the schema lives in one place rather than across nine modules.

Stack: Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `hypothesis`, `scipy`, `duckdb`, `pydantic` v2. Licence: Apache-2.0. Coverage floor 75%.

---

## 5. The golden set

### 5.1 Item schema — closed

`FieldType` is a closed enum of exactly eight members. Adding one fails `test_item_schema_is_closed`.

| `FieldType` | Example fields | Primary grader |
|---|---|---|
| `MONEY` | contract sum, current payment due, retainage amount, stored materials, line scheduled value | `numeric_tolerance` |
| `PERCENT` | percentage complete, retainage rate | `numeric_tolerance` |
| `DATE` | period-to, application date, through-date | `normalised` |
| `IDENTIFIER` | application no., project no., contract no., invoice no. | `normalised` |
| `PARTY_NAME` | contractor, owner, architect, vendor | `normalised` (acceptable variants) |
| `ENUM_CATEGORY` | lien waiver type, change order status | `exact` |
| `COUNT` | line item count | `exact` |
| `LINE_ITEM_DESCRIPTION` | free text | **judge candidate** — the only type where a deterministic grader genuinely cannot reach |

Two cross-field graders operate above individual fields: `arithmetic` (line sums foot to summary, balance-to-finish reconciles) and `schema` (model output is valid JSON conforming to the item schema).

### 5.2 The rubric is the asset

`docs/rubric.md` defines, per field type, what counts as correct: exact match, numeric tolerance and its magnitude, normalisation rules, acceptable variants, and the adjudication rule for ambiguity. It is authored and frozen **before any labelling**, versioned, and published.

Three witnesses to that claim, in ascending order of strength:

1. `rubric_versions.frozen_at` recorded in the database. Weakest — we control the database.
2. The public git history — `docs/rubric.md`'s commit timestamp precedes the first label commit.
3. **An OpenTimestamps commitment on `docs/rubric.md`, made at authoring time, with the `.ots` file committed alongside.** Strongest, and the one that actually discharges the claim.

**Why 3 rather than 2 (amended 2025-09-18).** This spec originally rested on git history alone. That is insufficient, and `backoffice-kit`'s §1.4 is right about why: `GIT_COMMITTER_DATE` is settable and history is rewritable, so a sceptic auditing a repo cannot distinguish a genuine history from a fabricated one. For a project whose known weakness is single-annotator ground truth (`04` B1), *"trust me, the timestamps are real"* is precisely the move this programme exists to reject. A public repo proves a push date; OpenTimestamps proves the **content existed at that date**, which is what the claim needs. It is free, needs no account, and is one command — and this project already builds hash publication for the private split, so the mechanism is not new.

`00` §12 Q5 stays *public from commit one* for this repo; the amendment is that repo visibility is now supporting evidence rather than the proof.

### 5.3 Synthetic generation

`golden/generate.py` **prefers to wrap Ledger Sense's synthetic pay-application generator** (weeks 5–12, a first-class deliverable there) and implements a minimal local generator only if that repo is unavailable at week 21. Decided as the first action of week-21 task 3.

Either way, two inherited rules bind absolutely:

- **No AIA form artifact anywhere in this repo.** The generator uses our own layout with equivalent column semantics. Mimic the column mathematics, never the form design.
- The non-affiliation notice ships with any published corpus: not developed, endorsed, approved, sponsored by or affiliated with the AIA; AIA(R), G702(R), G703(R) are registered trademarks of the American Institute of Architects; references describe compatibility only.

Labels come free on a synthetic set — they *are* the generation parameters. The generator injects known error classes so grader boundaries are exercised.

### 5.4 Splits and contamination

300 items: **120 public, 180 private.**

The boundary is a filesystem fact, not a code check:

- `golden/corpus/public/` — committed.
- `golden/corpus/private/` — **gitignored.** Only `manifest_private.json` is committed: hashes, count, generation date. Nothing else.
- **The private generator seed is never committed.** Publishing the seed alongside the generator would let anyone reconstruct the private split exactly. The seed lives in `.env`, is backed up outside the repo, and `docs/methodology.md` states that it is withheld and why.

**Amended 2026-08-29 (audit B4). Secrecy is not enough; the commitment needs entropy and a salt.**
Two defects, both fatal to this section's claim:

1. **Public and private items must be generated from two independent seeds, into two disjoint
   corpora.** A single 300-item pool split by `assign_splits(..., seed=GT_PUBLIC_SEED)` — where
   `.env.example` ships `GT_PUBLIC_SEED=42` — makes every private item reconstructible *with its
   labels* from committed data alone. `assign_splits` is restricted to the public pool.
2. **`content_hash = sha256(f"{seed}:{n}:{payload}")` is a commitment over a fully enumerable
   message space,** because `generate.py` is published (§13.1) and the repo is public from commit
   one (`00` §12 Q5). Its strength is therefore *exactly the seed's entropy*: a 32-bit seed is
   4.3e9 generator runs to invert, which is brute-forceable. Published hashes become
   `sha256(salt || canonical_item_bytes)` with a 128-bit `GT_HASH_SALT` in `.env`, revealed only
   when an item is disclosed. `build.py` refuses any seed or salt under 32 hex characters.

Two tests carry this: `test_public_seed_cannot_regenerate_any_private_item` and
`test_seeds_and_salt_meet_the_entropy_floor`. `docs/methodology.md` states the salt scheme and the
entropy floor in place of "the seed is withheld" — a claim that survives the repo being public.

Relatedly (**audit H1**), `item_id` was `content_hash[:16]`, so publishing the hash published the
id and `test_private_item_ids_never_appear_in_published_output` could never pass. `item_id` is now
`sha256(b"item-id:" + content_hash)[:16]`, putting preimage resistance between the two namespaces.

Rotation: 20% of private (36 items) regenerated from a fresh seed at each published release, minimum quarterly. New hashes published at generation time, proving existence at a date without revealing content.

**Reproducibility without revealing.** For the public split, publish outputs *and* verdicts. For the private split, publish **verdicts keyed by item hash only** — grade, grader id, grader version, rubric version. Never item content, never model output (output leaks the item). The reproducibility test then regenerates every headline aggregate from published verdicts plus the published analysis script, on both splits, without exposing a single private item.

What the sample buys, stated on the leaderboard: at private n=180 and accuracy ~0.90, the 95% interval half-width is roughly +/-4.4pp, detecting gaps of about 5pp after multiplicity correction. `stats/mde.py` computes and publishes this rather than asserting it.

---

## 6. Graders

Deterministic wherever possible. All are pure `(item, raw_output) -> Verdict`, no I/O, enforced by `test_graders_are_pure`.

| Grader | Behaviour | Boundary tests |
|---|---|---|
| `exact` | byte equality after whitespace normalisation | empty, whitespace-only, unicode confusables |
| `numeric_tolerance` | absolute or relative tolerance per rubric; `Decimal`, never `float` | exactly at tolerance, one unit inside, one unit outside, negative zero, thousands separators, currency symbols, parenthesised negatives |
| `normalised` | rubric-declared normalisation then equality; acceptable-variant table | each declared variant, a near-variant that must fail, case and accent folding |
| `schema` | output parses as JSON and validates against the item schema | missing field, extra field, wrong type, truncated JSON |
| `arithmetic` | cross-field consistency: line sums foot to summary, balance-to-finish reconciles | off-by-one-cent, rounding at the boundary, deliberately unbalanced fixture |

**No floats in the money path.** `Decimal` with an explicit context; rounding policy documented and tested. `hypothesis` property tests on every arithmetic rule.

Every grader has a fixture that must trip it and a clean control that must not.

---

## 7. Statistics — first-class tested code

Statistics code without tests is how a benchmark becomes fiction. Each module below lists the test that validates it against a known answer, not a smoke test.

### 7.1 `bootstrap.py`

**Cluster bootstrap over `item_id`, carrying replicates.** With five replicates per item, bootstrapping over `(item x replicate)` rows understates every interval by roughly sqrt(5) — silently producing narrow, confident-looking numbers. That is the exact failure this product is sold against, arriving from inside. `scipy.stats.bootstrap` with BCa does the resampling; the wrapper owns the clustering and attaches `n`.

- `test_bootstrap_ci_covers_known_parameter` — 1,000 simulated experiments from a known Bernoulli p; empirical coverage of the nominal 95% interval must land in [0.93, 0.97].
- `test_cluster_bootstrap_wider_than_naive` — on replicated data, clustering must yield a strictly wider interval. This test exists to fail if the clustering is ever "simplified" away.

### 7.2 `agreement.py`

Cohen's kappa (two raters, nominal) and Krippendorff's alpha (any number of raters, tolerates the missing-data pattern a partial second labeller produces).

- `test_krippendorff_alpha_matches_published_worked_example` — Krippendorff's canonical example (3 observers, 12 units, **with missing data**), to 3dp. The missing-data pattern is the point: it is the shape a partial second labeller produces (`04` B1), and Cohen's kappa cannot consume it.
- `test_krippendorff_alpha_matches_hand_derivable_two_rater_table` — a second anchor, fully derivable by hand: 15 units, 2 raters, 13 agreements, `D_o = 4`, `D_e = 664/29`, **alpha = 0.8253**.
- `test_cohens_kappa_zero_on_independent_raters`, `test_cohens_kappa_matches_worked_example` (Po=0.70, Pe=0.50, kappa=0.40 — re-derived and correct).

> **Corrected 2026-08-29 (audit B5).** Plan 2 Task 26 asserted `alpha == 0.743` against a
> 2-observer / 15-unit / no-missing-data table. Re-deriving the coincidence matrix for exactly
> those ratings gives **0.8253**, so the test fails — and it mislabels itself, because 0.743 is
> the *3-observer, 12-unit, missing-data* canonical example, not this one. That matters more than
> an ordinary wrong constant: alpha drives the pre-registered judge rejection threshold (§8.2), so
> an implementer bending the estimator to reach 0.743 would put every published accept/reject
> decision on a broken statistic. Keep **both** anchors — one worked example is not a validation.
> Evidence: `docs/superpowers/reviews/verify/verify_stats.py`.

Prefer the `krippendorff` PyPI package **only after verifying its licence is permissive** (`00` §3). Nominal alpha is ~40 lines if it is not.

### 7.3 `correction.py`

Benjamini–Hochberg via `scipy.stats.false_discovery_control`, wrapped to carry `(model_slot, field_type)` labels through so every alert can name its comparison family.

- `test_bh_matches_worked_example` — the BH 1995 fifteen-hypothesis example.
- `test_bh_controls_fdr_under_null` — 1,000 all-null simulations, empirical FDR <= 0.05.

### 7.4 `sequential.py`

**Alpha-spending on a pre-declared analysis calendar.** Thirteen weekly looks per quarter, O'Brien–Fleming spending across them, re-registered each quarter. Chosen over always-valid confidence sequences because it is standard machinery, implementable and testable inside a six-week phase, and explicable on a methodology page to a non-statistical buyer. An unscheduled look costs alpha and must be declared.

> **Corrected 2026-08-29 (audit B3). The original construction did not control alpha, and its two
> null simulations measured the wrong process.** Plan 2 Task 34 specified the boundary as
> `norm.ppf(1 - alpha/2) / sqrt(t)`. The O'Brien–Fleming boundary is `C / sqrt(t)` where **C is
> solved so the overall type-I error equals alpha** — it is not `z_{alpha/2}`. Using 1.96 spends
> the full alpha at the final look alone, before any interim look is counted.
>
> Simulated over 200,000 correlated Brownian trajectories (`corr(Z_j,Z_k) = sqrt(t_j/t_k)`), 13 looks:
>
> | Procedure | True type-I error |
> |---|---|
> | The original boundary (C = 1.960) | **0.0721** against a nominal 0.05 |
> | Correctly calibrated (C = 2.1023) | 0.0500 |
> | Naive fixed 1.96 at every look | 0.2153 |
>
> Both tests also drew **13 independent** normals per trial. Sequential looks accumulate on the
> same data and are highly correlated; independent draws are a different stochastic process.
> Under that wrong simulation `test_sequential_controls_type_i_under_null` returns **0.1794**
> against its own `<= 0.06` assertion (it fails), and `test_fixed_threshold_inflates_alpha`
> returns **0.4867** — which Task 34 Step 5 instructed be published on the methodology page as a
> measured finding. The truthful figure is **0.2153**. Publishing 0.487 would have been this
> programme's own §2 failure, arriving from inside.
>
> **The corrected design.** Alpha spending is the Lan–DeMets O'Brien–Fleming function, a correct
> closed form in one line: `alpha(t) = 2 * (1 - Phi(z_{alpha/2} / sqrt(t)))`. Verified cumulative
> spend: look 4 -> 0.000410, look 7 -> 0.007563, look 10 -> 0.025437, look 13 -> 0.050000 exactly —
> monotone and totalling alpha with no normalisation fudge, which also removes the tautology in the
> old `spent_alpha` test. The boundary constant `C_OBF_13_LOOKS = 2.1023` is calibrated once by
> simulation and committed *with that simulation as its test*; requesting any other calendar or
> alpha raises, because the constant is calibrated for the pre-registered calendar only.
>
> This changes `docs/analysis-plan.md`, which freezes before the first sweep. **Settle it before
> the freeze.** Evidence: `docs/superpowers/reviews/verify/verify_seq.py`.

- `test_sequential_controls_type_i_under_null` — 20,000 **correlated Brownian** trajectories x 13 looks; proportion with *any* rejection <= 0.055.
- `test_fixed_threshold_inflates_alpha` — the same correlated simulation under a naive per-look threshold, asserting `0.18 <= rate <= 0.25`. **This is the figure that goes on the methodology page.** The test makes the page's central claim executable rather than rhetorical, which is exactly why the simulation behind it has to be the right one.
- `test_calibrated_constant_controls_alpha` — binary-searches `C` under the same simulation and asserts the committed constant lands within Monte Carlo error of nominal alpha.

### 7.5 `mde.py`

Paired design (same items, two model slots) → McNemar. MDE is a function of `(n_items, discordance_rate, alpha, power, n_comparisons)`. For multiplicity it uses Bonferroni alpha/m rather than BH, because BH's effective threshold is data-dependent and unknowable in advance — the conservative choice, stated as such on the methodology page.

- `test_mde_matches_closed_form`, `test_mde_monotone` (falls with n, rises with comparisons).

### 7.6 Pre-registration, enforced

`docs/analysis-plan.md` is committed and frozen, its content hash recorded in `analysis_plan`, before the first sweep.

- **`test_analysis_plan_frozen_before_first_sweep`** — asserts `analysis_plan.frozen_at < min(runs.started_at)`.

Pre-registration you can verify beats pre-registration you assert.

---

## 8. The judge

Used for exactly one field type — `LINE_ITEM_DESCRIPTION` — and only because no deterministic grader reaches it.

### 8.1 Bias controls

| Bias | Control | Test |
|---|---|---|
| Position | presentation order randomised at execution with a recorded seed, stored in `judge_samples.presentation_order`; order-effect statistic computed in phase 2 | `test_order_effect_test_runs_and_is_reported` — the statistic must appear in the published artifact |
| Verbosity | cannot be fully stripped, so it is **measured**: verdict rate by output-length quintile, published | `test_length_effect_reported` |
| Self-preference | judge family declared in `models.yaml`, never inferred from a model name; a same-family judge for the model under test raises | `test_same_family_judge_rejected` |
| Sampling noise | n>=3 samples, majority vote; **ties resolve to `INCONCLUSIVE`, never a coin flip** | `test_tie_yields_inconclusive` |

### 8.2 The rejection threshold — pre-registered

Krippendorff's alpha >= 0.667 (the conventional tentative-conclusions floor), written into `docs/analysis-plan.md` and frozen **before any agreement number is computed**. Choosing it afterwards would be p-hacking.

Below threshold, the judge is barred from headline scoring for that field type; that field falls back to deterministic grading or is published as *not measured*. The agreement table publishes **every** field type the judge touched, including rejected ones, labelled rejected — so the published weakness always ships next to the decision it caused. A vendor cannot claim they were scored by a bad judge, because they were not.

---

## 9. Model x cost x latency matrix

**Cost is list price for the paid tier.** A YAML table derived from the week-21 provider audit, each row carrying the pricing-page URL and retrieval date. Every cost figure renders as a `Claim` with `method=DERIVED` and `caveat="list price for the paid tier, not measured spend"`. Because `00` §4.1 propagates caveats to children, any derived figure inherits it automatically — the honesty requirement is discharged by the substrate primitive, not by remembering a footnote.

**Latency is a distribution, not a rank.** Measured on the free tier, reported as p50/p95 with the ECDF available, carrying a prominent caveat that free-tier latency does not estimate paid-tier latency. `00` B4 permits ranking-with-caveat or distribution-without-ranking; the second is more defensible and less code.

- `test_latency_is_not_ranked` — the published artifact carries no latency rank key.
- `test_cost_claim_carries_list_price_caveat` — every cost `Claim` in the published artifact has the caveat present.

---

## 10. Calibration

Isotonic and Platt, fitted per field type.

**The confidence signal being calibrated is replicate agreement**, not model-reported confidence. For each (item, field, model slot), the score is the proportion of the 5 replicates producing the modal answer. This is chosen because it is available for every model regardless of whether the provider exposes a confidence figure, it is what the n>=5 requirement (`04` B7) already generates, and model-reported confidence is the uncalibrated number this programme exists to distrust. Where a provider *does* expose a confidence or logprob, it is recorded alongside and its own reliability curve published separately, so the two can be compared — but the exported curve Ledger Sense consumes is the replicate-agreement one.

**Fit on the public split (120), validate on the private (180).** This keeps all 180 private items available for headline scoring, and buys a free contamination detector: divergence between the public-fitted and privately-validated reliability curves is itself evidence that the public split has been trained on. The reliability diagram is published for both.

Export is a versioned JSON release artifact with these keys: `field_type`, `method` (isotonic | platt), `curve_points`, `n`, `fitted_at`, `rubric_version`, `source_split`, and `threshold_recommendations` (a list of `{target_precision, threshold}` pairs).

Ledger Sense reads a published file. **No runtime coupling in either direction**, which is what keeps `00` B5 satisfied — neither project can block the other.

- `test_exported_thresholds_match_curve`, `test_calibration_validated_on_held_out`.

---

## 11. Triage — the commercial wedge

### 11.1 Ingest

A CSV, not an importer framework. Columns: `intent`, `volume_per_month`, `current_cost_per_item`, `cost_of_error`, `client_quote`.

`cost_of_error` is **the client's number**; `client_quote` holds their verbatim justification (`04` B11). We never estimate it for them.

### 11.2 Expected value

Per intent, comparing automate against route-to-human:

```
EV = volume * [ accuracy * (current_cost_per_item - automation_cost_per_item)
              - (1 - accuracy) * cost_of_error ]
```

**Corrected 2026-08-29 (audit M7).** This read
`accuracy * saving_per_item - (1-accuracy)*cost_of_error - automation_cost_per_item`,
which subtracts `automation_cost_per_item` **twice** — once inside `saving_per_item` and again
as a standalone term. Plan 1 Task 19's implementation was already correct; the spec was wrong.
The formula is rendered into the client-facing report with the numbers substituted, so the error
would have been published in a paid deliverable. `test_report_formula_matches_the_implementation`
now asserts the rendered string is generated from the expression the code evaluates rather than
typed into the template.

Where the two derived terms come from, so the formula is unambiguous:

- `saving_per_item = current_cost_per_item - automation_cost_per_item` — `current_cost_per_item` is the client's, from the CSV.
- `automation_cost_per_item` is **ours**, computed from `matrix/cost.py`: the list-price token cost for the chosen model slot on that intent, plus the human-review cost of the fraction routed to review at the calibrated threshold. It inherits the list-price caveat from §9, so it propagates into every EV figure in the report.

**Accuracy enters as an interval, never a point** — so EV is an interval:

> *"At n=40, automating this intent has an expected value between -$2,100 and +$8,400 per month. This does not yet support a decision. n=200 would narrow it to roughly +/-$1,600."*

That paragraph is the product. A `never_automate` override fires on unbounded-error intents regardless of EV — a wrong bank detail has no sensible ceiling.

### 11.3 Sensitivity

`sensitivity.py` sweeps `cost_of_error` and reports the **flip point** in the client's own units: *"this becomes route-to-human if a wrong extraction costs more than $312."* A recommendation that flips at a plausible alternative assumption is presented **as flipping**, never as a conclusion.

- `test_recommendation_flips_at_computed_threshold`, `test_ev_interval_propagates_accuracy_interval`, `test_unbounded_error_forces_never_automate`.

### 11.4 Report

HTML with a print stylesheet, rendered to PDF through the browser. No PDF library. One page per intent plus a summary table, with the calculation shown.

**The triage report is `CLIENT_CONFIDENTIAL` and is never published (added 2026-08-29, audit B2).**
The intake carries the client's volumes, their cost-of-error figures, and — by design (`04` B11) —
their **verbatim words**. Under `00` §2.2 R4 that is `CLIENT_CONFIDENTIAL`, which may never reach
a free tier and must never reach a public web page. Plan 3 Task 40 routed `triage.html` into
`artifacts/` and Task 49 deployed `artifacts/` to GitHub Pages, so a paid engagement's confidential
task distribution would have been published. Three rules, each with a test:

- Triage output is written to `deliverables/`, which is **gitignored**. `emit_all` never writes it.
- The web `/triage` screen renders a synthetic worked example (`docs/triage-example.csv`), never a
  real engagement.
- `test_triage_output_is_never_a_published_artifact` and
  `test_no_client_quote_appears_in_any_published_artifact` walk the real emitted files.

The report must also state what its accuracy figure was measured on (**audit M8**): a synthetic
corpus, not the client's documents. `render_report` refuses to render without that provenance
string, because multiplying the client's real volumes by our synthetic accuracy and presenting the
product as a dollar recommendation is the one place this deliverable could mislead a buyer who
trusted it.

### 11.5 The legality gate

The triage deliverable is **billable client work**. Every model call in service of it must route to a provider whose free tier permits commercial use (`00` B3). This is a separate axis from sensitivity: the golden set is `SYNTHETIC` and clears the data boundary, but `commercial_use: false` still makes the call a licence breach.

Runs carry `CallContext(commercial=True)`, and the `runs.commercial_context` column records it. `router.call` raises `SensitivityViolation` before dispatch against any provider whose `commercial_use` is false **or unverified** — the contract fails closed on unknown, so a provider we never checked is ineligible rather than assumed fine. The refusal message quotes the terms URL, retrieval date and the sentence itself, because a refusal a client's counsel cannot audit is not a control.

- `test_commercial_run_refuses_non_commercial_provider`.

---

## 12. The `backoffice-kit` contract

> **Authority note (amended 2025-09-18, after `backoffice-kit` published its contract).**
> `backoffice-kit/docs/INTERFACE-CONTRACT.md` v0.1 is now the authoritative surface. Where this
> section and that document disagree, **that document wins**. Its §7 row for `ground-truth` is the
> binding checklist. The table below is retained because it records *why* each interface is
> load-bearing here; the signatures come from the contract.

**Amendments the contract makes to this spec, all adopted:**

| # | Amendment | Effect here |
|---|---|---|
| A1 | **`router.call(..., failover=DISABLED)` is required for benchmark execution.** Model identity is the variable under study; a silent failover attributes model A's output to model B and corrupts the benchmark invisibly. | New non-negotiable, ranked with the cache rule. `test_benchmark_slot_does_not_failover` joins the test bar. This spec previously missed it. |
| A2 | Payloads are `Labelled[str]` carrying `Sensitivity.SYNTHETIC`, not bare strings; commercial context is `CallContext(commercial=True)`; the refusal is `SensitivityViolation` raised by `router.call`, not a bespoke exception at `resolve`. | §11.5's legality gate keeps its meaning and loses its home-made exception. |
| A3 | `lanes.resolve` returns the lane's **deterministic fallback handle** when no provider is eligible — it does not raise. | The runner must detect a fallback handle and refuse to record its output as a model result. |
| A4 | The shared `≥70%` degraded-mode floor is withdrawn. Ground Truth's floor is **zero gateway calls in phase 2**, asserted by AST across every phase-2 module. | §16 updated. A stronger claim than `00` §7's, and the one this architecture can actually make. |
| A5 | `governor.remaining(provider) -> Quota(rpm, tpm, rpd)` is a public query. | The sweep scheduler uses it directly rather than a local budget type. |
| A6 | `testing.degraded.blackout()` / `assert_blackout_complete()` are provided. | The degraded-mode test uses them rather than rolling its own. |
| A7 | `Claim` carries `derivation` and `calibration`; `ConfidenceMeter` takes the `Calibration` object, never a float; `EmptyState` takes `scope={measured, skipped, reason}` and renders a denominator. | Cost claims and the calibration screen align to these shapes. |

**One deliberate divergence, kept:** `outputs` duplicates `provider_served`, `fingerprint`,
`latency_ms` and `prompt_hash` from `bok_ledger`. That is denormalisation, and it is correct here —
the DuckDB file must be self-contained for the reproducibility test, and a sceptic cannot join
against a ledger they do not have. `outputs.ledger_call_id` remains the foreign key.

Ground Truth **does not build the substrate**. It designs against these interfaces as a contract.

| Interface | Requirement | Consequence if absent |
|---|---|---|
| `gateway.lanes.resolve(lane)` | R1 — lane resolution from `models.yaml` | a model name would enter this repo |
| **`gateway.ledger`** — `call_id`, `model_id`, `provider`, `latency_ms`, `tokens`, `fingerprint`, `sensitivity`, `lane`, `timestamp` | **Hard dependency.** `outputs.ledger_call_id` is a foreign key into it | B6 fingerprint tracking and B8 provider attribution are both impossible; the regression module has no substrate |
| `boundary.policy.commercial_use` | `router.call` must raise `SensitivityViolation` under `CallContext(commercial=True)` against a provider whose `commercial_use` is false **or unverified** — the contract fails closed on unknown — and the message must cite its evidence | the triage legality gate (§11.5) fails open |
| **`router.call(..., failover=FailoverMode.DISABLED)`** | model identity is the variable under study; a silent failover attributes model A's output to model B | the leaderboard is corrupted invisibly, with no error to notice |
| `gateway.governor` | scheduler queries remaining quota before dispatching each sweep batch | the 9,000-call sweep 429s partway and produces a biased partial result |
| **`gateway.cache` — explicitly DISABLED for benchmark execution** | a cache hit returns an identical response for replicates 2–5, fabricating zero variance | B7's entire variance measurement is destroyed. This inverts R6 and needs its own test: `test_benchmark_execution_bypasses_cache` |
| `provenance.Claim` | every published number | caveat propagation (§9) stops working |
| `bok-ui`: `Claim`, `ProvenanceRail`, `FindingsTable`, `ConfidenceMeter`, `EmptyState`, `ErrorState` | the six screens | see fallback below |

**Fallback if `backoffice-kit` slips.** A local `_bok_shim.py` implementing minimum lane resolution plus a ledger table, carrying a `ponytail:` comment naming the upgrade path. On the web side, plain React plus a local `Claim` shim; the JSON artifact layer is unaffected. Ground Truth stays unblocked either way (`00` B5).

---

## 13. Publishing and web

### 13.1 What gets published

Rubric · public split · grader code · analysis scripts · raw results (public split) · verdicts-by-hash (private split) · private hash manifest · changelog · methodology · right-of-reply process.

**Never published:** the triage report or any client intake (§11.4) · private item content · any
model output on a private item · the private generator seed or the hash salt (§5.4).

Publication also carries the analysis seed (**audit H11**): `emit_all(con, out_dir, *, as_of,
analysis_seed)`, with the seed recorded in `leaderboard.json` and in `docs/analysis-plan.md`.
Without it the bootstrap endpoints differ between runs and `test_published_numbers_regenerate`
cannot pass. Because `scripts/reproduce.py` is stdlib-only and cannot re-run a BCa bootstrap, each
row publishes a **percentile** interval alongside the BCa one — percentile bootstrap is ~20 lines
of stdlib, so a stranger regenerates it exactly. `README.md` states plainly which numbers
regenerate without our package and which do not. A stated limitation beats an unverifiable claim.

### 13.2 Publication rules

- **No claim without its sample.** Every headline number carries its `n` and its interval.
- **Overlapping intervals are stated in words:** *"not distinguishable at this sample size."* That single behaviour is the brand.
- **Alerts state their test.** Never a bare red arrow — the test used and the p-value or interval, always.
- **Versioned, dated, changelogged. No silent edits.** A superseded number remains visible, struck.
- **Never characterise a vendor's honesty.** Measured claims only.
- Empty states say what has **not been measured yet**, never imply zero.

### 13.3 Right of reply

Channel: GitHub issue template labelled `right-of-reply`, plus a `corrections@` alias for providers preferring private first — the outcome publishes either way. Acknowledge in 5 business days, resolve in 15. No advance notice for routine scores; **10 business days for any regression or drift finding naming a provider**, because that reads as a defect claim rather than a measurement.

Three outcomes, all published: **correction** (numbers change, changelog entry, superseded numbers struck but visible), **clarification** (methodology text changes, numbers stand), **no change** (with stated reasoning). Standing offer: if a provider names a configuration error, we re-run under their stated configuration and publish both results side by side.

### 13.4 Web

Next.js 15 with `output: 'export'` to GitHub Pages — static, no server, $0. Light-first editorial instrument; slate-blue `oklch(0.52 0.10 232)` for measurement states only. A published document with an interface, not a dashboard.

Six screens: **Leaderboard** (signature — intervals rendered as intervals, methodology link beside the title, never in a footer) · **Item explorer** (filterable by failure mode; ~9,000 rows, which is why this is a React app and not a static generator) · **Judge agreement** (with confusion matrix) · **Calibration** (reliability diagram, sample size, threshold recommendation) · **Regression watch** (test named, p-value or interval shown) · **Triage report** (print-ready, calculation shown).

Quality floor per `00` §5.5: WCAG 2.2 AA via `axe-core` in CI, zero serious/critical; full keyboard operation; designed empty/loading/error/partial-failure states; responsive to 375px; `prefers-reduced-motion`; print stylesheet on every report view; tabular numerals everywhere a number appears.

---

## 14. Regression watch

`regression/detect.py` runs phase 2 over a time window on the pre-declared calendar (§7.4). `fingerprint.py` records model id, any exposed system fingerprint or version metadata, response metadata, provider served, and timestamp — and where a provider exposes no fingerprint at all, **says so** rather than implying we can pin a version we cannot.

Drift is detected statistically, never by threshold: bootstrap CI on the score, BH correction across model x field-type comparisons, alpha-spending across the calendar's looks, and the MDE stated so a null result is legible as *"no change larger than X detectable at this n"* rather than as *"no change"*.

- `test_alert_states_its_test`, `test_no_alert_below_mde_is_reported_as_undetectable_not_absent`.

---

## 15. Run economics

300 items x 6 slots x 5 replicates = **9,000 extraction calls**, plus **5,400 judge calls**
(300 x 6 x 3 — the judge scores the *modal* output per `(item, slot)`, not every replicate) =
**14,400 calls per full sweep.**

**Corrected 2026-08-29 (audit H8).** This section previously said 9,000 and omitted the judge
entirely. Plan 2 Task 24 as written called `sample_judgements` per `(output, field)` with n>=3,
which is 300 x 6 x 5 x 3 = **27,000** judge calls — a 4x underestimate of the free-tier budget,
in the week that already carries the full sweep. Judging the modal output per `(item, slot)`
costs 5,400 and loses nothing: replicate variance is already captured by the deterministic
graders and by the calibration signal, and judging five near-identical strings measures the
same string five times. `test_judge_samples_are_one_output_per_item_slot` enforces it.

Design consequences:

- Batched scheduling across providers with different limits; governor-aware dispatch; overnight runs; a documented run schedule in `docs/methodology.md`.
- **Response cache disabled for benchmark execution** (§12) — replicate variance is the measurement.
- `provider_served` recorded per call: routing one model through two providers may mean measuring the serving stack, not the model (`00` B8).
- Week 22's triage sweep is deliberately reduced: n~40 x 3 slots x 5 = **600 calls**, tractable in a day, and honest at n=40 because the interval says so.

---

## 16. Testing strategy

| Category | Coverage |
|---|---|
| Grader boundaries | every grader: a fixture that must trip, a control that must not; tolerance edges; `hypothesis` on arithmetic |
| Money path | no-float lint rule **and** test; `Decimal` context; rounding policy |
| Statistics | §7 — coverage simulation, worked examples, null simulations, monotonicity |
| Judge bias | §8.1 — four controls, four tests |
| Contamination | `test_private_items_never_in_published_output` (walks real emitted artifacts, not mocks) · `test_published_hashes_match_manifest` · `test_private_corpus_not_tracked_by_git` |
| Pre-registration | `test_analysis_plan_frozen_before_first_sweep` |
| Reproducibility | `test_published_numbers_regenerate` — regenerate every artifact from published inputs with a fixed `--as-of`, assert byte-identical |
| Calibration | fitted curves validated on held out; exported thresholds match the curve |
| Boundary | `test_commercial_run_refuses_non_commercial_provider` · `test_benchmark_execution_bypasses_cache` |
| Degraded mode | **Floor: zero gateway calls in phase 2**, not `00` §7's withdrawn `≥70%`. Two assertions: `test_phase2_imports_no_gateway` AST-scans every phase-2 module for a `bok_core.gateway` import and fails on any; `test_degraded_mode_still_produces_findings` runs the full analysis inside `bok_core.testing.degraded.blackout()` and calls `assert_blackout_complete()`. Published in `docs/methodology.md` with its unit |
| Failover | `test_benchmark_slot_does_not_failover` — a slot whose provider fails must produce **no output row**, never a row served by another provider |
| Non-goals | §2.2 — three AST/schema guard tests |
| E2E + a11y | Playwright including keyboard-only paths; `axe-core`, zero serious/critical |

Coverage floor 75%. Coverage is a floor, not a goal.

---

## 17. Sequence, weeks 21–26

| Week | Work | Gate |
|---|---|---|
| **21** | Provider audit → `docs/providers.md` + `models.yaml` (6 slots) · `store/` schema · **`docs/rubric.md` authored and frozen** · synthetic generator (reuse Ledger Sense's if available) · 300 items split 120/180, private gitignored · `docs/analysis-plan.md` frozen · five deterministic graders | rubric commit **precedes** first label commit, verifiable in public git history |
| **22** | `runner.py` · reduced sweep (~600 calls) · `stats/bootstrap.py` + `stats/mde.py` · `triage/` end to end · print-ready report | **A triage report that can be sold. Revenue.** |
| **23** | Full sweep, 9,000 calls, batched overnight · `graders/judge/` + bias controls · human labels **round 1** · `stats/agreement.py` + `correction.py` | |
| **24** | `matrix/` cost + latency · `calibrate/` fit-public / validate-private + export · `stats/sequential.py` + null simulations | |
| **25** | `regression/` · human labels **round 2** (blind re-label) · `publish/` · contamination + reproducibility tests · `docs/methodology.md` | |
| **26** | Next.js static export, six screens · axe + Playwright · right-of-reply live · first published release · DoD verification | `04` §12, eleven items |

**Hard scheduling constraint:** `04` B1 requires a **two-week gap** before blind re-labelling. Round 1 in week 23 and round 2 in week 25 is the minimum spacing that makes the intra-rater agreement number mean anything. If week 23 slips, round 2 slips with it and the number is not reportable — it is not compressible.

---

## 18. Definition of done — `04` §12 mapping

| # | Item | Week |
|---|---|---|
| 1 | Golden set, 200–500 items, rubric authored before labelling, versioned, published | 21 |
| 2 | Public/private splits enforced in code, contamination policy published, private hashes published | 21 / 25 |
| 3 | Deterministic graders for every field type where possible | 21 |
| 4 | Judge with bias controls; agreement measured, reported with an interval, published including weakness | 23 / 25 |
| 5 | Model x cost x latency matrix; cost as labelled list price, latency correctly caveated | 24 |
| 6 | Calibration curves per field type, exported in a form Ledger Sense consumes | 24 |
| 7 | Regression watch on a schedule, correct statistics, alerts stating their test | 24 / 25 |
| 8 | Triage deliverable end to end for at least one realistic task distribution, with sensitivity analysis | 22 |
| 9 | Public leaderboard deployed with methodology, rubric, grader code, analysis scripts, raw results, changelog, right of reply | 26 |
| 10 | Reproducibility test passes — published numbers regenerate from published data | 25 |
| 11 | `docs/methodology.md` defines every term used in every published number | 25 / 26 |

---

## 19. Risks and fallbacks

| Risk | Trigger | Fallback |
|---|---|---|
| `backoffice-kit` not ready | week 21 | `_bok_shim.py` with minimum ledger + lane resolution, `ponytail:` upgrade note |
| No Ledger Sense corpus or generator | week 21 | Local minimal synthetic generator. Already the default assumption — nothing blocks |
| Fewer than six usable providers after the audit | week 21 | Leaderboard ships with whatever survives, and states the count. MDE widens; the interface says so |
| A model is deleted mid-sweep (`00` B4) | any | Documented substitution procedure; prior results retained and marked with the date the row disappeared; never silently backfilled |
| Free-tier limits make the 9,000-call sweep infeasible | week 23 | Reduce replicates to n=3 (variance still measurable) before reducing items; state the change in the changelog |
| Judge agreement below alpha=0.667 on `LINE_ITEM_DESCRIPTION` | week 23 | Publish the rejection; that field type scores deterministically or is marked *not measured*. Designed for, not a failure |
| Week 23 slips | week 23 | Blind re-label round 2 slips with it; intra-rater agreement is not reportable in this phase. Say so rather than shortening the gap |
| Client pressure to widen the harness to their other task types | week 22+ | The non-goal guard tests fail the change. Escalate rather than accommodate — this is the platform trap wearing a cheque |
| **Every model scores ~1.00 and no pair is distinguishable** | week 23 | Not a sample-size result — a ceiling effect from a corpus whose document is a key→value dump using the requested JSON keys (§20 A8). Verify the corpus is a real extraction task **before** attributing a flat leaderboard to n |
| **A slot scores 180/180 and publishes `[1.000, 1.000]`** | week 24 | The bootstrap's degenerate branch, not a real zero-width interval (§20 A6). Exact binomial interval; correct lower bound at 180/180 is ~~0.9835~~ 0.9797 (two-sided 95%; the one-sided figure was superseded by stats review 2026-09-27, see CHANGELOG) |

---

## 20. Review amendments — 2026-08-29

Full evidence, severity and per-finding fixes: **`docs/superpowers/reviews/2026-08-29-ground-truth-audit.md`**.
Every numeric claim there was re-derived or simulated; reproduce with
`docs/superpowers/reviews/verify/` (stdlib only, no dependencies, no network).

The architecture survived the review unchanged. The two-phase split, the non-goal AST guards, the
pre-registration chaining, the fail-closed commercial gate and the decision to publish the judge's
weakness are all correct. What follows are defects in the arithmetic, in three payload and
identifier bugs, and in what the plans forgot to build.

### Amendments folded into this spec

| # | Amendment | Section |
|---|---|---|
| A1 | EV formula double-counted `automation_cost_per_item`; the spec was wrong and the plan was right | §11.2 |
| A2 | Run economics omitted the judge entirely: 9,000 → **14,400** calls, with the judge scoring the modal output per `(item, slot)` rather than every replicate | §15 |
| A3 | Public and private corpora need **two independent seeds**; the published manifest needs a **128-bit salt**, because the commitment's message space is fully enumerable from published code | §5.4 |
| A4 | `item_id` was a prefix of the published `content_hash` | §5.4 |
| A5 | O'Brien–Fleming used `z_{α/2}` where the calibrated constant is **2.1023**; both null simulations drew independent rather than correlated normals; the methodology-page figure was **0.487** where the truth is **0.215** | §7.4 |
| A6 | Krippendorff test expected 0.743 against data that yields **0.8253**, and mislabelled itself as the canonical example | §7.2 |
| A7 | The triage report is `CLIENT_CONFIDENTIAL` and was routed into the deployed `artifacts/` directory | §11.4, §13.1 |
| A8 | Publication now carries the **analysis seed**, plus a percentile interval so a stdlib-only stranger can reproduce the intervals and not merely the point estimates | §13.1 |

### Amendments that land in the plans, not here

These change task steps rather than design. They are listed so the spec records the full set.

**Blocking:** the runner sends `item.content_hash` where `render_document(item)` belongs, so the
entire sweep would measure a model's ability to extract fields from a hex string (audit B1). Once
fixed, the rendered document is still a key→value dump whose keys are the requested JSON keys —
a string-copy task, not extraction (audit M1). Both are Plan 1, Tasks 8 and 15.

**High:** `--cov-fail-under` in `addopts` makes ~50 per-task verification steps exit non-zero after
passing (H2) · `mypy --strict` fails for want of `types-PyYAML` and module overrides (H13) ·
judge execution under `graders/` breaks `test_phase2_imports_no_gateway` (H3) · `parse_judgement`
inverts the verdict on any prose negation (H4) · the flip-point test cannot pass at a 5.00 grid
step (H6) · `runs.resolved_model_ref` and `models_yaml_hash` are placeholder literals, and `Handle`
has no field to carry the resolved reference (H7) · the sweep resume path is wired to nothing and
would duplicate work rather than resume (H9) · `build_leaderboard` has no parameter for the judge
rejection it is required to honour (H10) · the regression watch cannot run in GitHub Actions,
because the private corpus and results DB are both gitignored (H12) · `test_dod_10` runs pytest
inside pytest and inherits the coverage gate (H14).

**Medium:** three of six `ErrorClass` members are labelled but never injected · the BH null test
measures the per-comparison rate rather than FDR · order and length effects publish bare numbers
against this project's own "no claim without its sample" rule · `parse_decimal` silently strips
currency and prose, so `"1234.56 EUR"` grades equal to USD 1234.56 · the Phase 1 triage report
presents synthetic accuracy as the client's · `DATE_LOCALE_AMBIGUOUS` items are unanswerable by
construction · the contamination label scan will fire on innocent short values · `example.invalid`
placeholders satisfy the provenance test · timestamps are naive, including the pre-registration
proof · `list_price > 0` forces inventing a price for genuinely free models.

**Security gaps against `00`, absent from all three plans:** no `Dockerfile` or `docker-compose.yml`
(§3.5 is a hard constraint) · no `pip-audit`, `npm audit`, Dependabot or SBOM (§8) · nothing
*creates* `SECURITY.md`, `docs/security.md` or `README.md` · provider keys in Actions on a public
repo with no `permissions:` block · mutable action and pre-commit pins · no CSP and no self-hosted
fonts (§5.2) · no `vcrpy` cassettes and no nightly smoke test, which is the stated mitigation for
`00` B4 · `gitleaks` will not match `GT_*_SEED`.

**Performance:** the sweep is fully serial across providers with independent rate limits, where
one worker per provider is roughly a 6× reduction (`04` B8 requires this and the design states but
does not implement it) · ~144,000 single-row DuckDB inserts in `grade.py` · slow simulations run on
every invocation · the item explorer static-imports ~57,600 rows on the false premise that a static
export forbids `fetch()`.

### Sequencing consequence

**A5 and A6 change `docs/analysis-plan.md`, which §7.6 freezes before the first sweep.** Settle
both before the freeze. Fixing them afterwards means the first release ships an amended plan and a
changelog entry saying why — survivable, and honest. Discovering them after publication is not.

Order of work: **B1 · B2 · A3 · A4 · H7 · A2 · M1 · M2** before any provider call, because they
change what gets measured or leaked. **A5 · A6 · H4 · H5 · H10 · M3 · M5 · M6 · A1 · M8** before
any number is published, because they change what the numbers mean. **H2 · H13** first of all, or
nothing runs.
