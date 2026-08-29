# Ground Truth

An eval and regression harness for one regulated task.
Weeks 21–26 · Accent: measure slate-blue `oklch(0.52 0.10 232)` · Licence: Apache-2.0 (pending `00` §12 Q6)

**Pitch:** *"Before you build anything, I will tell you which of your intents are safe to automate, which must route to a human, and what it costs — with a published methodology and a number you can reproduce."*

## Source of truth

- `../Starting_Documents/00-SHARED-FOUNDATION.md` — the substrate. Read in full before anything.
- `../Starting_Documents/04-GROUND-TRUTH.md` — this project's brief. Read in full.
- `../ledger-sense/` — if it exists by now, read its brief too. This project consumes its golden set and supplies its calibration curves.

The briefs win over anything summarised here. This file exists so a fresh session cannot violate a hard rule by accident.

## Workflow

superpowers, in order: `brainstorming` → `using-git-worktrees` → `writing-plans` → `subagent-driven-development` → `test-driven-development` → `requesting-code-review` → `verification-before-completion`. TDD is RED-GREEN-REFACTOR, no exceptions.

## Skill map

Phase-triggered, not a catalog — each entry is gated because this project's own audit history shows what happens without it, not as generic advice.

- **Golden set / rubric authoring** → `writing-plans`. The rubric is versioned and published *before* labelling starts, never reverse-engineered from labelled items.
- **Any publish step touching `golden/`, `triage/`, or the private split** → `security-review`, mandatory. This repo has already leaked confidential client data once — `triage.html` published to GitHub Pages, caught in the 2026-08-29 audit — this gate exists because of that incident, not in the abstract.
- **New code in `graders/`, `runner/`, `stats/`, `calibrate/`** → `test-driven-development`. RED-GREEN-REFACTOR, no exceptions (restates the Workflow line — this is where it actually bites).
- **`stats/` changes, before merge** → `code-review` at high or max effort. This module has already produced two audit-caught arithmetic bugs (Krippendorff's alpha test misalignment, sequential-testing boundary constant) — treat it as the highest-risk directory in the repo, not just another module.
- **`judge/` design** (prompt construction, output parsing, model selection) → the `claude-api` skill. Judge harnesses are LLM-facing code with the provider often left unstated; don't answer pricing/limits/behaviour questions from memory.
- **`judge/` prompts built from invoice or pay-application text** → the prompt-injection controls in `agent-security-super-skill`. Untrusted document content flows directly into a judge prompt; treat it as adversarial input, not trusted context.
- **`matrix/` cost figures** → fetch and cite a dated source for every list price. No hardcoded or remembered numbers — rule 5 exists because a fabricated cost comparison is the exact failure this programme corrects.
- **Any chart** — leaderboard intervals, calibration curves, confusion matrix, regression-watch plots → `dataviz`, read before the first line of chart code, not after the first draft looks wrong.
- **`web/`** — component and screen work → `frontend-design`, plus the TypeScript/React reviewer skills for anything touching `.tsx`.
- **Any bug, failed test, or regression alert** → `systematic-debugging` before proposing a fix. Root cause, not the symptom the alert named.
- **Start of any session** → check auto-memory / `mem-search` before re-deriving context. This project already has a documented 46-defect audit; don't rediscover what's already logged.

## The single most important instruction

**Do not build an eval platform.** The category fails structurally: the buyer must be technical enough to want APIs but not technical enough to run their own evals — a narrow band — and the feature keeps getting absorbed into observability tooling.

Non-goals, enforced in code review: no plugin system, no generic task abstraction, no multi-tenant SaaS, no "bring your own eval", no observability product, no prompt management. **If the design starts growing a generic runner or a task abstraction, stop and say so.**

Build instead: a vertical harness (one task), a public decision artifact (benchmark + leaderboard with stated methodology), and a paid diagnostic (the triage deliverable — the commercial wedge).

## The task

**Pay-application and invoice field-extraction accuracy**, composing with Ledger Sense: the golden set already exists by week 21, the domain partner already trusts us, the labels are objective, and it closes Ledger Sense's calibration gap. Alternates if blocked: contract clause extraction; clinical note summarisation (higher stakes, PHI collides badly with free-tier inference).

One task owned completely beats five covered shallowly — and narrowness is the only thing keeping this out of the platform trap.

## Never (each has a test proving it)

1. **Private-split items never appear in published output.** Split the golden set: a public split for reproducibility, and a **private held-out split that is never published**, against which the headline numbers are computed. Publish hashes of the private items so their existence at a date is provable without revealing them. Rotate a portion periodically. State the contamination policy on the methodology page.
2. **No claim without its sample.** Every headline number carries its n and its interval. Where two models' intervals overlap, the interface says so in words: *"not distinguishable at this sample size."* That single behaviour is the entire brand.
3. **LLM-as-judge only where a deterministic grader genuinely cannot reach** — and where used, judge-versus-human agreement is measured and published with an interval, including where the judge is weak. If agreement is poor, say so and fall back to deterministic grading rather than shipping a judge we cannot defend.
4. **Judge bias controls are mandatory:** randomise presentation order and test for order effects; strip length cues; never use a model from the same family as the model under test as its sole judge; n≥3 with majority vote.
5. **The cost column uses published list prices for the paid tier, labelled as list price, never as measured spend.** On $0 the measured cost is meaningless. Latency is reported as measured-on-free-tier with a prominent caveat, or reported as a distribution with no ranking. Fabricating a cost comparison would be the exact failure this programme exists to correct.
6. **Temperature zero is not determinism.** Run n≥5 per item, report mean and variance. A single decimal from one run is provisional, not a result.
7. **Never characterise a vendor's honesty.** Measured claims only. Versioned, dated results with a changelog and no silent edits. A published right-of-reply process with a stated response window, and a correction policy we actually follow.

Inherited from `00`: no hardcoded model names (R1), no secrets in the repo including fixtures, $0 recurring cost, permissive licences only.

## What gets built

**Golden set** — 200–500 labelled items. **The rubric is the asset; the code is commodity.** It defines in writing what counts as correct per field type — exact match, numeric tolerance, normalised match, acceptable variants — authored *before* labelling, versioned, published.

**Graders** — deterministic wherever possible: exact field match, numeric tolerance, citation-exists, schema validity, arithmetic consistency. Judge only at the edges.

**Define the terms in public.** State exactly what "accurate", "resolved", "deflected", "correct" and "field" mean. Given that the incumbent benchmarks are self-defined or invented, a published definition is a genuine competitive asset.

**Model × cost × latency matrix** — answers the buyer's real question, *"do I need a frontier model for this?"*, which no vendor is incentivised to answer.

**Calibration output** — reliability curves per field type, fitted and published, exported for Ledger Sense's confidence routing. This is what makes brief 02's threshold routing legitimate rather than decorative.

**Regression watch** — scheduled re-runs alerting on drift when a provider silently updates a model behind a stable name, with statistics that keep noise from being reported as regression.

**Triage deliverable — the commercial wedge.** Ingest the client's historical task distribution, output *"automate these six intents, route these four to a human, never automate these two"*, each with the expected-value calculation. **Expected value, not accuracy:** a 92%-accurate intent with a $4 cost of error is automatable; a 97%-accurate intent with a $40,000 cost of error is not. Making the cost of error explicit is the entire value of the artifact.

## Stack & layout

Python 3.12+, `uv`, `ruff`, `mypy --strict`. Result history in DuckDB. Scheduled runs via the same orchestration as brief 03. Every model call recorded through `bok-core`'s ledger (`00` R7) — that is what makes fingerprint tracking possible at all. Next.js 15 + `bok-ui`, or a static site.

```
ground_truth/
  golden/       item schema, rubric versioning, label storage, split management
  graders/      deterministic/ (exact, numeric_tolerance, normalised, schema, arithmetic)
                judge/ (constrained output, agreement measurement, bias controls)
  runner/       pytest-style harness (or inspect-ai / promptfoo if not owning the runner)
  stats/        bootstrap CIs, Cohen's/Krippendorff's agreement, Benjamini–Hochberg,
                sequential testing, MDE calculator
  matrix/       model × cost × latency, list-price cost model
  calibrate/    reliability curves, isotonic / Platt, export for consumers
  regression/   scheduled runs, drift detection, fingerprint tracking
  triage/       task distribution ingest, expected-value model, recommendation output
  publish/      static leaderboard generator, methodology renderer
web/            Next.js 15 + bok-ui (or static)
```

This is a **published document with an interface**, not a dashboard. Design it like a well-set research report that happens to be interactive. Screens: **Leaderboard** (signature; intervals rendered as intervals, methodology link beside the title not in a footer) · Item explorer · Judge agreement (with confusion matrix) · Calibration · Regression watch (alerts state the test used and the p-value or interval, never a bare red arrow) · Triage report (print-ready, calculation shown).

## Watch for

- **Single-annotator ground truth is a known weakness** and a sceptical buyer will raise it. Rubric before labelling; blind re-labelling of a random 20% after a two-week gap with intra-rater agreement reported; adjudication rules recorded as decisions; a second labeller (the Ledger Sense design partner) on a subset with inter-rater agreement reported. **Report the disagreement rate honestly** — it is more credible than a suspiciously clean set.
- **Regression alerting is a statistics problem, not a threshold problem.** Pre-registered analysis plan, bootstrap CIs, multiple-comparison correction across models × field types, an MDE calculation so we know what the sample can and cannot see, sequential testing so repeated looks do not inflate false positives.
- **Models change silently behind stable names.** Record model id, any system fingerprint or version metadata exposed, response metadata, timestamp. On free tiers there may be no fingerprint at all — say so rather than implying we can pin a version we cannot.
- **Free-tier rate limits shape the experimental design.** 500 items × 6 models × 5 runs = 15,000 calls. Aggressive caching, batched scheduling across providers with different limits, overnight runs, a documented run schedule. Record which provider served each call — routing one model through two providers may mean measuring the serving stack.
- **Consider benchmarking models rather than vendor products.** Lower friction, more meaningful comparison, less exposure.
- **Cost of error is the client's input, not ours.** Interview for it, document the assumption in their own words, run sensitivity analysis, and present a recommendation that flips at a plausible alternative assumption *as flipping*.
- **If Ledger Sense did not produce a partner and a labelled corpus, this project's plan changes materially.** It must still stand alone on a synthetic golden set — weaker, but shippable — rather than blocking.

## Testing bar

Grader boundary cases · judge bias tests (order randomisation occurs, order-effect test runs and is reported, same-family judge rejected) · **statistics tests** (bootstrap CIs against known distributions, multiple-comparison correction against a worked example, sequential testing verified under a null simulation — *statistics code without tests is how a benchmark becomes fiction*) · contamination tests · **reproducibility test: re-run the analysis from published raw results and assert the published numbers regenerate exactly** · calibration tests on held-out data · degraded mode (deterministic graders run against stored outputs with all providers disabled and the analysis still produces a report) · E2E and axe per the shared foundation. Coverage floor 75%.

## Definition of done

Brief §12, eleven items.

## Before planning

Brief §13 has 7 open decisions; `00` §12 has 7 more. Q1 (did Ledger Sense produce a design partner and a labelled corpus?) and Q6 (is the triage deliverable sellable standalone in week 22, before the harness is finished — it is the revenue) reorder the phase. Do not assume them — ask.
