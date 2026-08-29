# Ground Truth — Design and Plan Audit

**Date:** 2026-08-29 · **Scope:** `docs/superpowers/specs/2025-09-18-ground-truth-design.md` and all three phase plans
**Method:** every numeric claim in the plans was re-derived from first principles or simulated. Nothing below is asserted; each finding states the evidence that produced it. Reproduce with `docs/superpowers/reviews/verify/` (stdlib only, no dependencies).

---

## Verdict

The architecture is sound and unusually well-reasoned. The two-phase execute/analyse split, the non-goal AST guards, the pre-registration chaining, the fail-closed commercial gate and the decision to publish the judge's weakness are all correct and rare. **The defects are not architectural — they are in the arithmetic, in three payload/identifier bugs, and in what the plans forgot to build.**

Five defects would cause this project to publish a wrong number or leak client data. That matters more here than in an ordinary codebase, because "being checkable is the product" (`00` §1) and the brief's own §2 exists to condemn exactly these failures. A benchmark that ships finding **B3** would publish a fabricated statistic on its methodology page while selling a methodology page.

| Severity | Count | Meaning |
|---|---|---|
| **Blocking** | 5 | Publishes a wrong number, or leaks data. Fix before any sweep runs. |
| **High** | 14 | Guaranteed test failure, or silent data corruption. |
| **Medium** | 13 | Validity, honesty, completeness. |
| **Security gap** | 8 | Required by `00` §3/§7/§8 and absent from all three plans. |
| **Performance** | 6 | |

---

# BLOCKING

## B1 — The runner sends the SHA-256 hash where the document should be. The entire sweep measures nothing.

**Location:** Plan 1, Task 15, Step 4, `build_prompt`.

```python
text = (
    "Extract these fields from the document and return a single JSON object "
    f"whose keys are exactly: {names}. Every value must be a JSON string.\n\n"
    f"---\n{item.content_hash}\n"          # <-- this is a 64-char hex digest
)
```

`render_document(item)` exists (Task 8) and is never called by the runner. Every one of the 9,000 calls asks a model to extract fifteen fields from a hex string. Every accuracy will be near zero, every interval will overlap, and the leaderboard will report "not distinguishable at this sample size" — which the plan pre-emptively rationalises in Task 31 Step 5 as "a true result about your sample size, not a bug."

**Why nothing catches it:** `tests/test_runner.py` uses `FakeGateway`, which returns a canned `'{"contract_sum": "1.00"}'` regardless of the prompt. `tests/test_phase2_e2e.py` checks row counts, replicate counts and non-identical outputs — never prompt content. `prompt_hash` is stable, so nothing looks wrong.

**Fix:** `f"---\n{render_document(item)}\n"`, and add to `tests/test_runner.py`:

```python
def test_prompt_contains_the_document_not_its_hash():
    item = generate(count=1, seed=1, rubric_version="v1")[0]
    payload = build_prompt(item)
    assert item.content_hash not in payload.value, "the hash is not the document"
    assert "PROGRESS BILLING SUMMARY" in payload.value
    assert len(payload.value) > 200, "a prompt this short cannot contain a document"
```

**B1b — and once fixed, the task is still degenerate.** `render_document` emits `f"{field_name:<32}{expected_value}"`, and `build_prompt` asks for "keys exactly: {names}" using the *same* field names. The document is a key→value dump whose keys are the requested JSON keys. This is a string-copy task, not field extraction; every model scores ~1.0 and the leaderboard has a ceiling effect indistinguishable from B1's floor effect. See **M1** — same work, same fix.

---

## B2 — The paid client's confidential task distribution is published to the public web.

**Location:** Plan 3, Task 40 (`emit_all` writes `triage.html` into `out_dir`), Task 49 (`publish.yml` deploys `artifacts/` to GitHub Pages), Task 50 (`test_dod_8` reads `ARTIFACTS/triage.html`).

The triage intake CSV carries `intent`, `volume_per_month`, `current_cost_per_item`, `cost_of_error` and — by design (`04` B11) — `client_quote`, the client's **verbatim words** about what a wrong extraction costs their business. Under `00` §2.2 R4 that payload is `CLIENT_CONFIDENTIAL`. The plans route it into the published artifacts directory and deploy it.

No test forbids it. `tests/test_contamination.py` checks only golden-set private items; `test_dod_8` actively *requires* `triage.html` to be in `artifacts/`.

**Fix, four parts:**

1. `emit_all` must not write `triage.html`. Triage output goes to `deliverables/` (gitignored), never `artifacts/`.
2. The web `/triage` screen renders a **synthetic worked example** committed as `docs/triage-example.csv`, not a real engagement.
3. `.gitignore`: add `deliverables/`.
4. Add the missing control:

```python
# tests/test_contamination.py
def test_triage_output_is_never_a_published_artifact(emitted):
    _, paths = emitted
    assert not any(p.name == "triage.html" for p in paths), (
        "the triage deliverable is CLIENT_CONFIDENTIAL and is never published"
    )

def test_no_client_quote_appears_in_any_published_artifact(emitted):
    _, paths = emitted
    intake_dir = REPO / "deliverables"
    quotes = {r["client_quote"]
              for p in intake_dir.glob("*.csv")
              for r in csv.DictReader(p.open(encoding="utf-8"))} if intake_dir.exists() else set()
    for path in paths:
        blob = path.read_text(encoding="utf-8")
        leaked = sorted(q for q in quotes if q and q in blob)
        assert leaked == [], f"{path.name} leaks a client quote"
```

`test_dod_8` changes to read `deliverables/triage.html`.

---

## B3 — The sequential test uses the wrong O'Brien–Fleming constant, both null simulations are wrong, and the plan instructs publishing a statistic that is 2.3× the truth.

**Location:** Plan 2, Task 34.

The plan specifies `obrien_fleming_boundary(look, total, alpha) = norm.ppf(1 - alpha/2) / sqrt(t)`. The O'Brien–Fleming boundary is `C / sqrt(t)` where **C is solved so the overall type-I error equals α**. It is not `z_{α/2}`. Using 1.96 spends the full α at the final look alone, before any interim look is counted.

**Simulated, 200,000 trials of correlated Brownian monitoring (`corr(Z_j,Z_k)=√(t_j/t_k)`), 13 looks:**

| Procedure | True type-I error | Nominal |
|---|---|---|
| Plan's boundary (C = 1.960) | **0.0721** | 0.05 |
| Correctly calibrated (C = 2.1023) | 0.0500 | 0.05 |
| Naive fixed 1.96 at every look | 0.2153 | — |

**And both of the plan's own tests are constructed wrongly.** They draw **13 independent** `gauss(0,1)` values per trial. Real sequential looks accumulate on the same data and are highly correlated; independent draws are a different stochastic process entirely.

- `test_sequential_controls_type_i_under_null` asserts `rate <= 0.06`. Measured under the plan's own simulation: **0.1794** (analytic 0.1794; Monte Carlo n=20,000: 0.1797). **This test fails.** The obvious "fix" — widening the assertion — is precisely what Plan 1 Task 16 Step 5 forbids elsewhere.
- `test_fixed_threshold_inflates_alpha` yields **0.4867**, and Task 34 Step 5 says: *"Record the exact figure … it goes on the methodology page as the measured reason the naive approach was rejected."* The truthful figure is **0.2153**. The plan would publish 0.487.

That is the brief's §2 failure — a plausible-looking number with no valid derivation — arriving from inside the project built to correct it.

**Fix.** Replace the alpha-spending construction with the Lan–DeMets O'Brien–Fleming spending function, which is a correct closed form and one line:

```python
def spent_alpha(look: int, total_looks: int, *, alpha: float = 0.05) -> float:
    """Lan-DeMets O'Brien-Fleming spending function: alpha(t) = 2(1 - Phi(z_{a/2}/sqrt(t)))."""
    _check(look, total_looks)
    t = look / total_looks
    return 2.0 * (1.0 - float(norm.cdf(float(norm.ppf(1 - alpha / 2)) / math.sqrt(t))))
```

Verified cumulative spend: look 4 → 0.000410, look 7 → 0.007563, look 10 → 0.025437, look 13 → 0.050000 exactly. Monotone, totals α, no normalisation fudge. This also removes **M4**.

For the boundary, the lazy correct option that fits a six-week phase is to calibrate the constant once by simulation and commit it *with the simulation as its test*:

```python
C_OBF_13_LOOKS = 2.1023  # calibrated; see test_calibrated_constant_controls_alpha

def obrien_fleming_boundary(look: int, total_looks: int, *, alpha: float = 0.05) -> float:
    _check(look, total_looks)
    if (total_looks, alpha) != (LOOKS_PER_QUARTER, 0.05):
        raise ValueError(
            "the boundary constant is calibrated for the pre-registered calendar only; "
            "changing the calendar requires re-calibration and a new analysis-plan version"
        )
    return C_OBF_13_LOOKS / math.sqrt(look / total_looks)
```

Rewrite both null simulations to generate correlated trajectories:

```python
def _brownian_z(rng, k_total):
    """Z_k = B(t_k)/sqrt(t_k): what sequential monitoring actually produces."""
    b, out = 0.0, []
    for k in range(1, k_total + 1):
        b += rng.gauss(0, math.sqrt(1.0 / k_total))
        out.append(b / math.sqrt(k / k_total))
    return out

@pytest.mark.slow
def test_sequential_controls_type_i_under_null():
    rng, trials = random.Random(0), 20_000
    rejected = sum(
        any(evaluate_look(z, look=k, total_looks=13).reject
            for k, z in enumerate(_brownian_z(rng, 13), start=1))
        for _ in range(trials)
    )
    assert rejected / trials <= 0.055

@pytest.mark.slow
def test_fixed_threshold_inflates_alpha():
    """Publish THIS figure (~0.215). The independent-draw version reports 0.487, which is
    not a property of sequential monitoring and must never reach the methodology page."""
    rng, trials = random.Random(0), 20_000
    rate = sum(any(abs(z) > 1.96 for z in _brownian_z(rng, 13)) for _ in range(trials)) / trials
    assert 0.18 <= rate <= 0.25
```

`test_final_boundary_is_near_the_fixed_sample_critical_value` (`1.96 ± 0.15`) still passes at C = 2.1023, but change its expectation to the calibrated constant so it means something.

**This changes `docs/analysis-plan.md`, which is frozen before the first sweep. Settle it before the freeze.**

---

## B4 — The private split is derivable from committed data, and the published hash manifest is a commitment whose only strength is the seed's entropy.

**Location:** Plan 1, Task 9 Step 5; `.env.example`; Task 8 `generate`.

**B4a — the immediate hole.** `.env.example` is committed and ships `GT_PUBLIC_SEED=42`. Task 9 Step 5 says `build.py` "reads `GT_PUBLIC_SEED` and `GT_PRIVATE_SEED`, generates 300 items, calls `assign_splits(items, public_n=120, seed=int(GT_PUBLIC_SEED))`." **It never says which seed generates the 300.** If `GT_PUBLIC_SEED` does — the natural reading, since it is the only seed the step passes to a function — then `generate(300, 42, "v1")` followed by `assign_splits(..., 120, 42)` reconstructs all 180 private items **with their labels** from committed data alone.

Every contamination test still passes, because they check only that private *files*, *ids* and *labels* do not appear in artifacts. Nothing tests that the private split is not *derivable*.

**B4b — the deeper weakness.** Even with a separate private seed:

```python
content_hash = hashlib.sha256(f"{seed}:{n}:{payload}".encode()).hexdigest()
```

`generate.py` is published (spec §13.1 publishes the grader and analysis code; the repo is Apache-2.0 and public from commit one, `00` §12 Q5). The message space is therefore fully enumerable: an attacker generates candidate corpora and compares against the published `manifest_private.json`. The commitment's strength is *exactly* the seed's entropy:

| Seed choice | Entropy | Generator runs to invert |
|---|---|---|
| `42`, or `1`–`255` | 8 bits | 256 |
| a year or ticket id | ~16 bits | 65,536 |
| `random.randint(0, 2**32)` | 32 bits | 4.3 × 10⁹ — **brute-forceable** |
| `secrets.token_hex(16)` | 128 bits | infeasible |

The spec assumes seed *secrecy*; the design needs seed *entropy* plus a salted commitment. With the repo public from commit one, secrecy is the weaker assumption.

**Fix:**

1. `build.py` calls `generate` **twice**, with two independent seeds, into two disjoint corpora. `assign_splits` is restricted to the public pool or deleted — a single pool split by a committed seed *is* the bug.
2. Salt the published commitment: `item_hash = sha256(salt || canonical_item_bytes)` with a 128-bit `GT_HASH_SALT` in `.env`, published only when an item is disclosed. A salted commitment is what makes "prove existence at a date without revealing content" true rather than aspirational.
3. `build.py` refuses a seed or salt shorter than 32 hex characters, naming the reason.
4. Add the missing control:

```python
def test_public_seed_cannot_regenerate_any_private_item():
    """The committed public seed must be useless against the private split."""
    from ground_truth.golden.generate import generate
    private = {i.content_hash for i in load_private_corpus()}
    forged = generate(count=300, seed=int(os.environ["GT_PUBLIC_SEED"]), rubric_version="v1")
    assert not ({i.content_hash for i in forged} & private), (
        "the private split is derivable from committed data"
    )

def test_seeds_and_salt_meet_the_entropy_floor():
    for key in ("GT_PRIVATE_SEED", "GT_HASH_SALT"):
        assert len(os.environ[key]) >= 32, f"{key} must carry at least 128 bits"
```

5. `docs/methodology.md` states the salt scheme and the entropy floor, replacing "the seed is withheld" with a claim that survives the repo being public.

---

## B5 — The Krippendorff's α test expects 0.743; the data given produces 0.825.

**Location:** Plan 2, Task 26, `test_krippendorff_alpha_matches_published_worked_example`.

Re-derived from the coincidence matrix for the exact ratings in the test:

```
marginals    {'1': 9, '2': 7, '3': 9, '4': 5}     n = 30
D_observed   4          D_expected  22.896552
ALPHA        0.825301                            plan asserts 0.743 ± 0.005  ->  FAIL
```

The dataset in the test (2 observers, 15 units, no missing values, disagreements at units 6 and 15) is **not** Krippendorff's canonical example. The published α = 0.743 example is the 3-observer, 12-unit set with missing data. The test therefore both fails and mislabels itself.

This is more dangerous than an ordinary wrong constant: α drives the **pre-registered judge rejection threshold** (§8.2, α ≥ 0.667). An implementer chasing 0.743 could bend the estimator until it matches, after which every published judge accept/reject decision rests on a broken statistic.

**Fix.** Two anchors, one of which exercises the missing-data path that `04` B1's partial second labeller produces:

```python
def test_krippendorff_alpha_matches_published_worked_example():
    """Krippendorff's canonical nominal example: 3 observers, 12 units, missing data.
    Chosen over a complete 2-rater table precisely because the missing-data pattern is
    the one a partial second labeller produces (04 B1). Verify 0.743 against the source
    before committing this expectation."""
    ...

def test_krippendorff_alpha_matches_hand_derivable_two_rater_table():
    """15 units, 2 raters, 13 agreements. D_o = 4, D_e = 664/29 = 22.896552,
    alpha = 1 - (4/30)/(664/870) = 0.825301. Derivation in the audit."""
    ...  # the table currently in the plan, with 0.8253 as the expectation
```

One worked example is not a validation. Keep both.

---

# HIGH

## H1 — `item_id` is the first 16 characters of the `content_hash` that gets published. The contamination test can never pass.

`generate()` sets `item_id = content_hash[:16]`. `manifest_private.json` and `verdicts_private_by_hash.jsonl` both publish the full 64-character `content_hash`. Verified: `item_id in content_hash` is `True` by construction.

Plan 3 Task 41's `test_private_item_ids_never_appear_in_published_output` scans every artifact for private item-id substrings. It will **always fail** — and the finding is real, not a test artifact: publishing the hash publishes the id.

**Fix:** separate the identifier namespace from the commitment namespace.

```python
item_id = hashlib.sha256(b"item-id:" + content_hash.encode()).hexdigest()[:16]
```

Preimage resistance now keeps them apart. Add `assert item.item_id not in item.content_hash` to `tests/golden/test_generate.py`.

## H2 — `--cov-fail-under=75` in `addopts` makes ~50 of the plans' verification steps unreachable.

`pyproject.toml` (Task 1 Step 5) puts `--cov=ground_truth --cov-report=term-missing --cov-fail-under=75` in `addopts`, so it applies to *every* invocation — including `uv run pytest tests/test_repo_hygiene.py -v` (Task 1 Step 7, "Expected: PASS, 3 passed"). One test file measured against the whole package scores far below 75, and pytest **exits non-zero after the tests pass**. Every per-task "Expected: PASS" step in all three plans is affected, starting at the very first one.

Also: `markers = ["slow: …"]` is declared but never deselected, so every full run pays the 1,000 / 1,000 / 2,000-trial simulations.

**Fix:**

```toml
[tool.pytest.ini_options]
addopts = "-m 'not slow' --strict-markers"
testpaths = ["tests"]
markers = ["slow: coverage and null simulations; run in the CI 'stats' step"]
```

and put the gate where it belongs, in `ci.yml`:

```yaml
      - run: uv run pytest -m "not slow" --cov=ground_truth --cov-report=term-missing --cov-fail-under=75
      - run: uv run pytest -m slow          # separate step, no coverage gate
```

## H3 — Judge execution lives under `graders/`, which breaks `test_phase2_imports_no_gateway`.

`PHASE_2_MODULES` includes `"graders"`, and the guard walks it recursively, flagging any import whose name contains `gateway` or ends `_bok_shim`. Plan 2 Task 24 creates `ground_truth/graders/judge/prompt.py`, which imports `ground_truth._bok_shim`. The declared degraded-mode floor — Ground Truth's strongest claim, per contract amendment A4 — fails its own test the moment the judge lands.

The architecture is right (judge *sampling* is phase 1, judge *aggregation* is phase 2); only the file location is wrong.

**Fix:** move execution out of the phase-2 tree — `ground_truth/judge_runner.py`, alongside `runner.py`. `graders/judge/` keeps `aggregate.py` and `agreement.py`, both pure. Update Task 24's paths and move `tests/graders/judge/test_prompt.py` → `tests/test_judge_runner.py`.

## H4 — `parse_judgement` inverts the verdict on any prose negation.

`if "NOT_EQUIVALENT" in t` then `if "EQUIVALENT" in t` — correct for the underscore token, wrong for everything a model actually emits. Verified:

| Judge response | Parsed | |
|---|---|---|
| `NOT_EQUIVALENT` | NOT_EQUIVALENT | ✓ |
| `not equivalent` | **EQUIVALENT** | inverted |
| `They are not equivalent.` | **EQUIVALENT** | inverted |
| `No, these are not equivalent` | **EQUIVALENT** | inverted |
| `NOT EQUIVALENT` | **EQUIVALENT** | inverted |
| `Not-equivalent` | **EQUIVALENT** | inverted |

The plan's parametrised table tests only underscore forms plus one benign prose case. A judge that obeys "reply with exactly one token" only some of the time produces a **systematically biased** verdict set — biased toward flattering the model under test — and the bias is invisible in the agreement statistic, because human labels are compared against the corrupted parse.

**Fix:** anchor the match, normalise the separator, and treat anything ambiguous as `INCONCLUSIVE`, which the design already treats as a first-class outcome.

```python
_TOKEN = re.compile(r"\bNOT[\s_\-]?EQUIVALENT\b|\bEQUIVALENT\b")

def parse_judgement(raw: str) -> JudgeVerdict:
    hits = {("NOT_EQUIVALENT" if m.startswith("NOT") else "EQUIVALENT")
            for m in _TOKEN.findall(raw.strip().upper())}
    if len(hits) != 1:
        return JudgeVerdict.INCONCLUSIVE      # absent, or both present -> not a verdict
    return JudgeVerdict(hits.pop())
```

Add every row above to the test, plus `"EQUIVALENT, but not really"` → INCONCLUSIVE.

## H5 — A perfect or zero score publishes a zero-width interval.

`_interval` returns `method="degenerate"` with `low == high == point` whenever `values.std() == 0.0`. A slot scoring 180/180 on the private split therefore publishes **`accuracy 1.000 [1.000, 1.000] n=180`**.

The correct 95% one-sided Clopper–Pearson lower bound at 180/180 is **0.9835** (rule of three: 0.9833). The published interval understates uncertainty by 1.65 percentage points at exactly the point a leaderboard makes its strongest claim — and `Interval.overlaps` then reports a degenerate row as distinguishable from everything, so the "not distinguishable at this sample size" behaviour that the brand rests on fails silently, in the direction of overclaiming.

**Fix:** replace the degenerate branch with an exact binomial interval and keep the method label honest.

```python
if float(values.std()) == 0.0:
    p, a = float(values.mean()), 1 - confidence
    lo = a ** (1 / n) if p == 1.0 else 0.0          # Clopper-Pearson, one-sided
    hi = 1 - a ** (1 / n) if p == 0.0 else 1.0
    return Interval(point=p, low=lo, high=hi, n=n, method="clopper-pearson-exact")
```

Add `test_perfect_score_still_carries_uncertainty`: `assert ci.low < 1.0 and ci.method != "degenerate"`.

## H6 — `test_flip_point_actually_flips_the_recommendation` fails at the specified grid resolution.

Re-derived with the plan's own fixture (`ACC = [0.905, 0.935]`, volume 1000, current 2.00, automation 0.10, `ceiling=1000`, `steps=200`):

```
grid step                             = 5.00
true AUTOMATE/INSUFFICIENT boundary   = 18.10
reported flips_at                     = 20.00
test probes flips_at - 1 (= 19.00) -> INSUFFICIENT_EVIDENCE
test probes flips_at + 1 (= 21.00) -> INSUFFICIENT_EVIDENCE
assert below != above                 -> FAIL
```

The ±1 probe is finer than the 5.00 grid. The reported flip point is also off by 1.90 in the client's dollars — in the one sentence the plan calls "the product."

**Fix:** bisect. Correct, exact to a stated precision, and 200 `evaluate` calls become ~17.

```python
def find_flip_point(intent, accuracy, auto_cost, *, ceiling, precision=Decimal("0.01")):
    base = _rec(Decimal(0))
    if intent.unbounded_error or _rec(ceiling) == base:
        return FlipPoint(..., flips_at=None, to_rec=None, sentence="... does not flip ...")
    lo, hi = Decimal(0), ceiling
    while hi - lo > precision:
        mid = ((lo + hi) / 2).quantize(precision)
        lo, hi = (mid, hi) if _rec(mid) == base else (lo, mid)
    return FlipPoint(..., flips_at=hi, to_rec=_rec(hi), ...)
```

Keep `sweep()` for the report's sensitivity chart; stop using it to locate the boundary.

## H7 — `runs.resolved_model_ref` and `runs.models_yaml_hash` are hardcoded placeholder strings.

```python
[run_id, datetime.now(UTC), slot, "resolved-at-runtime", handle.provider,
 context.commercial, sweep_id, code_version, "models-yaml-hash"],
```

The schema was designed so `04` B6 fingerprint tracking and `00` R7 provenance are possible. The implementation writes the literal strings `"resolved-at-runtime"` and `"models-yaml-hash"` for all 9,000 rows. No test asserts on any `runs` column.

Root cause: `Handle(slot, provider, is_fallback)` has **no field carrying the resolved model reference**, so the runner cannot record it even in principle.

`_code_version()` compounds it — it swallows both exceptions and records `"unknown"`, and never records whether the tree was dirty. A 9,000-call sweep whose recorded code version is `"unknown"` has no provenance.

**Fix:**

1. Add `model_ref: str` to `Handle` in `_bok_shim.py`, and raise it with `backoffice-kit` as a contract gap — Ground Truth is the repo whose reason to exist is knowing which model produced which output.
2. `models_yaml_hash = hashlib.sha256(models_yaml.read_bytes()).hexdigest()`.
3. `_code_version()` returns `f"{sha}{'-dirty' if porcelain else ''}"`, and `execute_sweep` **refuses** to run against the private split, or with `commercial=True`, from a dirty tree.
4. Add:

```python
def test_run_records_the_resolved_model_ref_not_a_placeholder(con):
    ref = con.execute("SELECT resolved_model_ref FROM runs").fetchone()[0]
    assert ref and "runtime" not in ref and ref != "unknown"

def test_run_records_the_models_yaml_hash(con):
    assert re.fullmatch(r"[0-9a-f]{64}",
                        con.execute("SELECT models_yaml_hash FROM runs").fetchone()[0])
```

## H8 — The judge adds 27,000 calls the plan never counts. The real sweep is 36,000, not 9,000.

Spec §15 states 9,000 calls and designs the whole free-tier schedule around it. Task 24's `sample_judgements` is called per `(output, field)` with `n ≥ 3`, and `LINE_ITEM_DESCRIPTION` is one field on every item:

```
sweep                                       300 × 6 × 5      =  9,000
judge as Task 24 writes it                  300 × 6 × 5 × 3  = 27,000
TOTAL                                                          36,000
```

A 4× underestimate against free-tier quotas, in the week (23) that already carries the full sweep. It will not complete.

**Fix:** judge the **modal output per (item, slot)**. Replicate variance is already captured by the deterministic graders and by the calibration signal; judging five near-identical strings buys nothing.

```
300 × 6 × 3 = 5,400 judge calls   (4.4× cheaper)
```

Update spec §15 to `9,000 + 5,400 = 14,400`, state it in `docs/methodology.md`'s run schedule, and add `test_judge_samples_are_one_output_per_item_slot` asserting `count(DISTINCT output_id) == n_items × n_slots`.

## H9 — The resume path is designed, tested in isolation, and wired to nothing.

`pending_work()` returns `WorkUnit`s; `plan_batches()` chunks them. `execute_sweep(con, items, slots, replicates, …)` accepts **items and slots**, not `WorkUnit`s, and unconditionally writes replicates `1..n` under a **fresh `run_id` per slot per invocation**.

Re-running after an interruption therefore does not resume — it **duplicates**, under a new `run_id` that defeats `UNIQUE (run_id, item_id, replicate_idx)`, doubling both quota spend and the recorded data. Task 23 Step 6 nonetheless instructs: *"If interrupted, re-run the identical command — `pending_work` resumes without re-spending quota."*

`test_pending_work_excludes_what_already_landed` passes because it tests `pending_work` alone. The feature does not exist.

**Fix:** `execute_sweep` takes `units: list[WorkUnit]`, reuses one `run_id` per `(sweep_id, slot)`, and Task 23's `__main__` runs `pending_work → plan_batches → execute_sweep(batch)`. Add:

```python
def test_resuming_does_not_duplicate_rows(con):
    items = generate(count=4, seed=1, rubric_version="v1")
    sid = run_sweep(con, items, ["slot-a"], 5)            # full
    run_sweep(con, items, ["slot-a"], 5, sweep_id=sid)    # resume: must be a no-op
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 4 * 5
```

## H10 — `build_leaderboard` has no parameter for the judge rejection, so a rejected judge's verdicts enter the headline number.

Task 31 Step 3 states it "**excludes verdicts from any judge whose field type was rejected in Task 27**." Its signature is `build_leaderboard(con, *, split, seed, specs)`. Nothing carries the rejection decision. Spec §8.2's guarantee — *"a vendor cannot claim they were scored by a bad judge, because they were not"* — is unimplementable as specified.

**Fix:** persist the decision so it is auditable rather than passed around, then read it.

```sql
CREATE TABLE IF NOT EXISTS judge_decisions (
    field_type TEXT PRIMARY KEY, rubric_version TEXT NOT NULL, alpha DOUBLE NOT NULL,
    alpha_low DOUBLE NOT NULL, alpha_high DOUBLE NOT NULL, n_units INTEGER NOT NULL,
    threshold DOUBLE NOT NULL, status TEXT NOT NULL CHECK (status IN ('accepted','rejected')),
    decided_at TIMESTAMPTZ NOT NULL);
```

`build_leaderboard` joins it and drops rejected field types. Add `test_rejected_field_type_is_absent_from_headline_accuracy`.

## H11 — `emit_all` carries no analysis seed, so reproducibility cannot pass — and a stranger cannot reproduce the intervals at all.

`build_leaderboard(con, *, split, seed, specs)` needs a seed for the BCa bootstrap. `emit_all(con, out_dir, *, as_of)` has none. A different seed gives different interval endpoints, so `test_published_numbers_regenerate` fails on byte comparison.

Worse, structurally: Task 43 Step 3 requires `scripts/reproduce.py` to **not import `ground_truth`** and to use the standard library only. It therefore cannot re-run a BCa bootstrap. A stranger can recompute the **point estimate** and nothing else — so the published *intervals*, which are the entire brand, are not independently reproducible. The plan does not say so.

**Fix:**

1. `emit_all(con, out_dir, *, as_of, analysis_seed)`; the seed goes into `leaderboard.json` and into `docs/analysis-plan.md`.
2. Publish a **percentile** bootstrap interval alongside BCa. Percentile bootstrap is ~20 lines of stdlib, so `reproduce.py` regenerates it exactly from the published verdicts and the published seed.
3. `README.md`'s reproduction section states plainly which numbers regenerate stdlib-only (point estimates, percentile intervals) and which need `ground_truth` installed (BCa). An honest, stated limitation beats an unverifiable claim.

## H12 — The regression watch cannot run where the plan schedules it.

`.github/workflows/regression-watch.yml` (Task 38) "runs the sweep against the private split, then `regression.detect`." The private corpus is gitignored and `data/*.duckdb` is gitignored. A GitHub Actions runner has neither the private items nor the baseline results.

Both possible resolutions carry consequences the plan never states: committing the results DB would publish private raw outputs (violating `04` B5 and spec §5.4), and running in Actions requires provider API keys on a public repo (see **S4**).

**Fix:** the watch runs on the operator's machine on the pre-registered calendar (`regression/schedule.py` already models the calendar; add a documented local cron / Task Scheduler entry). The Actions workflow keeps only what is safe there: opening the issue from a committed, redacted `artifacts/regression.json`, and the nightly provider smoke test (**S7**). `test_dod_7`'s `assert "schedule:" in workflow` currently proves the wrong thing — point it at the calendar record in `looks` instead.

## H13 — `mypy --strict` fails at Task 2, and again at Task 32.

`[tool.mypy] strict = true`, and the dev group has no `types-PyYAML`. `import yaml` under `--strict` errors immediately. `scikit-learn` (added Task 32) ships no stubs; `scipy`'s are partial; `duckdb`'s are incomplete. Task 2 Step 7 says "Expected: PASS." It will not.

**Fix:**

```toml
dev = ["pytest>=8.3", "pytest-cov>=5.0", "hypothesis>=6.112", "mypy>=1.11", "ruff>=0.6",
       "types-PyYAML>=6.0"]

[[tool.mypy.overrides]]
module = ["sklearn.*", "scipy.*", "duckdb.*"]
ignore_missing_imports = true
```

Each override is a documented, bounded exception — not `ignore_errors`.

## H14 — `test_dod_10` runs pytest inside pytest and inherits the coverage gate.

```python
result = subprocess.run(["uv","run","pytest","tests/test_reproducibility.py","-v","--no-header"], ...)
assert result.returncode == 0
```

The nested run inherits `addopts`, measures coverage from three tests, scores far under 75, and exits non-zero. Independent of **H2**'s fix, a nested run should never carry the parent's gate.

**Fix:** append `"-p", "no:cacheprovider", "-o", "addopts="`.

---

# MEDIUM — validity and honesty

## M1 — The corpus is a key→value dump, and no artifact is required to say so.

`render_document` emits `f"{field_name:<32}{expected_value}"` using the exact key names the prompt requests. Nothing about layout, multi-column tables, OCR noise, header chrome, values that must be computed rather than copied, or fields absent from the document. The leaderboard's external validity — *"does this predict performance on my invoices?"* — is unmeasured and unmentioned.

Given `04` §12's requirement that the methodology define every published term, the missing definition is the **population**. "No claim without its sample" needs its twin: *no claim without its population.*

**Fix, in order of value:**

1. `render_document` produces a realistic layout: a bordered continuation-sheet table, a summary block whose wording differs from the JSON keys (`"CONTRACT SUM TO DATE"` → `contract_sum`), header/footer chrome, at least one distractor number, and 3–8 line items rather than a fixed 2.
2. `test_document_does_not_use_the_json_key_names`: assert no `field_name` appears verbatim in `render_document(item)`.
3. `docs/methodology.md` opens its Scope section with the population statement; `test_methodology_states_the_population` asserts the words *synthetic*, *not real pay applications*, and *external validity* appear.
4. A **construct-validity check** worth its cost: 20 hand-built hard items, ranked; publish the rank correlation with the synthetic ranking, with its interval. Even n=20 supports a directional statement, and stating it is the differentiator.

## M2 — Three of six declared error classes are never injected.

`_build_fields` branches only on `RETAINAGE_MISMATCH`, `STORED_MATERIALS_DOUBLE_COUNT` and `DATE_LOCALE_AMBIGUOUS`. Items labelled `TRANSPOSED_DIGITS`, `OFF_BY_ONE_CENT` and `MISSING_FIELD` carry the label and **no corruption**. `test_error_classes_are_injected_and_labelled` checks only that the labels exist.

Separately, the plan's note on Task 14 claims rule 3 catches `STORED_MATERIALS_DOUBLE_COUNT`. It does not — `total_earned_less_retainage` is computed from the mutated `work_completed`, so rule 3 reconciles. Rules 1 and 2 catch it. The item is caught; the stated reason is wrong, and reason strings are asserted in tests.

**Fix:** implement all six, correct the note, and prove the corruption:

```python
def test_every_injected_error_class_actually_corrupts_the_item():
    clean = {i.item_id: i for i in generate(60, seed=11, rubric_version="v1", inject=False)}
    for item in generate(60, seed=11, rubric_version="v1"):
        if item.injected_error is None:
            continue
        assert item.fields != clean[item.item_id].fields, (
            f"{item.injected_error} is labelled but injects nothing"
        )
```

## M3 — The BH null test measures the per-comparison error rate, not the false discovery rate.

```python
rate = false_discoveries / (trials * per_trial)
assert rate <= 0.05
```

FDR is `E[V / max(R,1)]`. Dividing total false discoveries by total *hypotheses* gives the per-comparison rate, which under the complete null with BH is far below 0.05 — the test passes trivially and validates nothing. Under the complete null FDR = FWER, so the meaningful assertion is on the proportion of trials with **any** rejection.

**Fix:**

```python
@pytest.mark.slow
def test_bh_controls_fdr_under_complete_null():
    rng, trials, m = random.Random(0), 2000, 48
    any_rejection = sum(
        any(c.significant for c in benjamini_hochberg(
            [Comparison(f"h{i}", rng.random()) for i in range(m)], fdr=0.05))
        for _ in range(trials))
    assert any_rejection / trials <= 0.06, "under the complete null, FDR = FWER <= alpha"

@pytest.mark.slow
def test_bh_controls_fdr_with_true_effects_present():
    """The case that distinguishes BH from Bonferroni: mean of V/max(R,1) over trials."""
    ...  # 12 of 48 hypotheses non-null; assert mean(V / max(R,1)) <= 0.05
```

## M4 — `spent_alpha` is normalised to hit α, making its test tautological.

Resolved by **B3**'s Lan–DeMets replacement, which reaches α exactly without normalisation. `test_alpha_spent_is_monotone_and_totals_alpha` then tests the function rather than the rescaling.

## M5 — Order and length effects are published as bare numbers, breaking the project's own publication rule.

`OrderEffect(order_0_rate, order_1_rate, difference, n)` and `LengthEffect(quintile_rates, n)` carry no interval, and `n` counts **samples**, not outputs — three samples per output are clustered exactly as `stats/bootstrap.py` exists to handle. Spec §13.2: *"Every headline number carries its `n` and its interval."* These are headline numbers on the Judge screen.

**Fix:** cluster over `output_id`, attach an `Interval` to `difference` and to each quintile rate via `cluster_bootstrap_ci`. Add `test_order_effect_carries_an_interval` and `test_order_effect_n_is_outputs_not_samples`.

## M6 — `parse_decimal` silently strips currency and prose.

Verified against inputs the plan never tests:

| Input | Parsed | |
|---|---|---|
| `'1234.56 EUR'` | `1234.56` | grades **equal** to an expected USD 1234.56 |
| `'approximately 1234.56'` | `1234.56` | prose accepted |
| `'about 40'` | `40` | prose accepted |
| `'1e5'` | `15` | scientific notation becomes a different number |
| `'USD 1,234.56 (revised)'` | `1234.56` | |

`_STRIP = re.compile(r"[^\d,.\-()%]")` deletes every letter. On a pay application, currency is not decoration. `docs/rubric.md` says nothing about prose or currency, so the grader is **more lenient than the published rubric** — an undeclared leniency in the money path.

**Fix:** decide it in the rubric first, then implement the rubric. Recommended: reject any residual alphabetic character except a declared currency code that must match the item's currency; reject `e`/`E` between digits explicitly. Add each row above to `test_parse_decimal_raises_on_junk`.

## M7 — The spec's expected-value formula double-counts the automation cost.

Spec §11.2:

```
EV = volume * [ accuracy * saving_per_item - (1-accuracy)*cost_of_error - automation_cost_per_item ]
     where saving_per_item = current_cost_per_item - automation_cost_per_item
```

`automation_cost_per_item` is subtracted twice. Plan 1 Task 19's implementation omits the second subtraction and is correct; **the spec is wrong**. The formula is rendered into the client-facing report ("the EV formula with the actual numbers substituted"), so the spec's version would be published in a paid deliverable.

**Fix:** spec §11.2 becomes

```
EV = volume × [ accuracy × (current_cost_per_item − automation_cost_per_item)
                − (1 − accuracy) × cost_of_error ]
```

and add `test_report_formula_matches_the_implementation`, asserting the rendered formula string is generated from the same expression the code evaluates rather than typed into the template.

## M8 — The Phase 1 triage report presents synthetic accuracy as the client's accuracy.

`test_phase1_e2e` fabricates accuracy from `[(f"i{i}", i % 10 != 0) for i in range(40)]` and feeds it straight into the EV calculation for the client's intents. In production, the accuracy comes from a 600-call sweep over **our synthetic pay applications**, then multiplies the client's real volumes and real cost-of-error to produce a dollar recommendation.

This is the paid deliverable and the phase's revenue. The caveat is mandatory, and no test requires it.

**Fix:** `render_report` refuses to render without a `measured_on` provenance string, and:

```python
def test_report_states_what_the_accuracy_was_measured_on():
    body = html().lower()
    assert "synthetic" in body
    assert "not measured on this client's documents" in body
```

## M9 — `DATE_LOCALE_AMBIGUOUS` items are unanswerable by construction.

The generator writes `"01/09/2026"` as the **expected value**; `grade_normalised` normalises the expected side to `AMBIGUOUS`, so the verdict is incorrect for every model, including a perfect one. Defensible (the rubric does say ambiguous dates score incorrect), but it puts a hard, undocumented ceiling on DATE accuracy that differs from every other field type and makes the DATE column uninterpretable.

**Fix:** either exclude ambiguous-date items from DATE headline scoring and report them as a separate "unanswerable by rubric" count, or put the ambiguity in the *rendered document* while the label stays ISO. State whichever in `docs/rubric.md` and surface the count on the leaderboard.

## M10 — The contamination label scan will fire on innocent values, and the natural fix disables the control.

`test_private_labels_never_appear_in_published_output` filters `len(value) > 6` and asserts no private `expected_value` appears in any artifact. Private labels include `"2026-09-01"` (10 chars — appears in every artifact carrying a date), `"approved"` (8 chars), and `PARTY_NAME` strings shared with public items. Spurious failures are certain, and the obvious response is to raise the length threshold until it passes.

**Fix:** scan only high-entropy field types (`MONEY`, `PERCENT`, `IDENTIFIER`), and add the structural assertion that actually holds:

```python
def test_private_emitter_never_reads_the_columns_it_must_not_publish():
    src = inspect.getsource(artifacts.emit_private_verdicts_by_hash)
    for column in ("expected_value", "raw_output", "item_id"):
        assert column not in src, f"the safest way not to publish {column} is not to read it"
```

## M11 — `example.invalid` placeholders satisfy the provenance test.

`test_every_slot_carries_list_price_and_provenance` asserts `pricing_url.startswith("https://")`, which `https://example.invalid/pricing` — the value the plan's own `models.yaml` template ships — satisfies. A test a placeholder passes is not a control.

**Fix:** `assert "example.invalid" not in spec.pricing_url` and `assert "FROM_AUDIT" not in spec.model_ref`. Add an archival requirement too: `terms_url` alone is unverifiable once a provider edits its terms, so record a `terms_archive_url` (web.archive.org) captured on the retrieval date. A quoted sentence with a date is not evidence once the page is gone.

## M12 — Timestamps are stored naive, including the pre-registration proof.

The schema uses `TIMESTAMP`; the code writes `datetime.now(UTC)`. `assert_frozen_before_first_sweep` compares two values read back naive. Sweeps run overnight across days, possibly across a DST boundary, possibly from more than one machine — and this comparison is the load-bearing evidence for §7.6.

**Fix:** `TIMESTAMPTZ` for `rubric_versions.frozen_at`, `analysis_plan.frozen_at`, `runs.started_at/finished_at`, `outputs.observed_at`, `human_labels.labelled_at`, `looks.run_at`. Add `test_timestamps_are_timezone_aware`.

## M13 — Requiring `list_price > 0` forces inventing a price.

Some models are offered only on a free tier and have no published paid list price. `test_every_slot_carries_list_price_and_provenance` requires `> 0`, so the only way to configure such a slot is to make a number up — the exact failure `04` B4 exists to prevent.

**Fix:** allow `None`; require `None` **or** (`> 0` with a URL and a date). Render "no published list price" on the leaderboard and exclude the slot from cost comparison with a stated reason.

---

# SECURITY GAPS — required by `00`, absent from all three plans

| # | Requirement | Source | Status |
|---|---|---|---|
| **S1** | "Everything runs from `docker compose up` on a fresh machine" | `00` §3.5, **hard constraint** | No `Dockerfile`, no `docker-compose.yml` in any plan |
| **S2** | `pip-audit`, `npm audit`, Dependabot, CycloneDX SBOM per release | `00` §8 | Absent |
| **S3** | `SECURITY.md` + `docs/security.md` (disclosure policy + threat model) | `00` §6, spec §4 | Task 44 *modifies* `SECURITY.md`; nothing creates it. Same for `README.md`. |
| **S4** | Provider keys in Actions on a **public** repo | — | `regression-watch.yml` runs the sweep with provider secrets. No `permissions:` block, no environment protection, no statement that it must be `schedule`-only and never `pull_request_target`. See **H12** — the right fix is not to run it in Actions at all. |
| **S5** | Pin the supply chain | `00` §8 | `actions/checkout@v4`, `astral-sh/setup-uv@v3` and every pre-commit `rev:` are mutable tags. Pin to commit SHAs. |
| **S6** | No Google Fonts CDN; CSP | `00` §5.2 | The web plan never self-hosts fonts and never sets a CSP. GitHub Pages cannot set headers, so use `<meta http-equiv="Content-Security-Policy">` with `default-src 'self'`. |
| **S7** | `vcrpy` cassettes + nightly live smoke test that opens an issue | `00` §7 | Absent. This is the stated mitigation for `00` B4 (models deleted without notice) and `04` B6. A weekly full sweep is not a smoke test, and it will not run when quota is spent. |
| **S8** | `gitleaks` will not catch `GT_PRIVATE_SEED=…` | `00` §3.4 | Add a custom gitleaks rule for `GT_.*_SEED` and `GT_HASH_SALT`, plus `test_no_seed_value_in_any_tracked_file`. |

Two more worth stating:

- **`docs/providers.md` quotes provider terms verbatim** into an Apache-2.0 public repo. Short quotation for evidentiary purposes is defensible, but pair it with the archival URL (**M11**) so the evidence survives, and keep quotes to the single operative sentence.
- **`scripts/reproduce.py` parses attacker-supplied JSON.** `json.loads` is safe; state explicitly that it must never use `eval`, `pickle`, or `yaml.load`, because it is the one script strangers are invited to run.

---

# PERFORMANCE

| # | Finding | Fix |
|---|---|---|
| **P1** | **The sweep is fully serial.** 14,400 calls in nested `for` loops, one at a time. At 3 s/call that is 12 hours of wall clock with every provider idle but one. `04` B8 requires "batched scheduling across providers with different limits"; the design states it and does not implement it. | One worker **per provider** (`ThreadPoolExecutor(max_workers=len(providers))`), preserving per-provider serialisation so rate-limit semantics are unchanged. With six providers, roughly a 6× reduction. DuckDB connections are not thread-safe — give each worker `con.cursor()` and funnel writes through one queue, or write per-worker Parquet and load once. |
| **P2** | **~144,000 single-row `INSERT`s in `grade.py`** (9,000 outputs × ~16 verdicts). DuckDB is columnar; single-row inserts are its worst case. The plan promises re-grading is "an afternoon"; it should be seconds. | Accumulate verdicts and insert per batch with `executemany`. Note `test_no_task_registry` bans `.register(` — DuckDB's DataFrame registration API — so use `executemany`, or add an explicit documented exemption. Also index items by id (`{i.item_id: i for i in items}`), not a linear scan per output. |
| **P3** | Slow simulations run on every invocation (**H2**). | `-m "not slow"` in `addopts`; a separate CI step for `-m slow`. |
| **P4** | **The item explorer static-imports ~57,600 verdict rows** (120 public items × 6 slots × 5 replicates × ~16 fields). Next inlines a static JSON import into the JS chunk: multi-MB bundle, main-thread parse. The plan's justification is factually wrong — *"a static import, no fetch, because both the static export and the eventual CSP forbid runtime data loading."* `output: 'export'` fully supports `fetch()` of a same-origin asset, and `connect-src 'self'` permits it. | Put `verdicts_public.jsonl` in `public/`, `fetch()` it, and paginate or virtualise the table. Spec §5.4 specifies `FindingsTable` as virtualised; the plan's explorer is not. Ship a small per-item index for the first render. |
| **P5** | `find_flip_point` scans 200 grid points per intent. | Bisection (**H6**) — correct *and* ~12× fewer evaluations. |
| **P6** | `test_every_deterministic_field_type_has_verdicts` joins `verdicts` to `item_fields` on `field_name` **with no `item_id`**, a cartesian product of ~144,000 × ~4,500 rows for a `DISTINCT`. | Join through `outputs` so `item_id` participates. |

---

# COMPLETENESS — required by the brief, missing from the plans

Beyond the security gaps above:

1. **No second labeller, and no requirement to say so.** `00` §12 Q1 answers "Ledger Sense partner not assumed", so inter-rater agreement will not exist — only intra-rater (Task 39). `krippendorff_alpha`'s partial-rater support is built and unused. `04` B1 requires the disagreement rate be reported honestly; the methodology must state plainly that there is **one annotator**, that the annotator also authored the rubric, and that judge-vs-human agreement is therefore agreement with the rubric's author. Add `test_methodology_states_the_single_annotator_limitation`.
2. **`docs/methodology.md` has two conflicting sources.** Task 35 Step 3 says write the numbers in by hand; Task 42 Step 6 says a hand-typed methodology drifts and must be generated. Pick generation, and make `assert_methodology_defines_every_term` read the generated output.
3. **`corrections@<domain>` requires a domain**, which has a cost, against `00` §3.1's $0 constraint. Either use a GitHub-only channel or record the domain as an accepted cost in the risk table.
4. **`test_no_characterisation_of_vendor_honesty` will block legitimate prose.** It substring-scans whole files for `fabricated`, `misleading` and similar — words the methodology needs when describing *the market* (`04` §2 is built on exactly that language). Scope the scan to paragraphs naming a configured provider.
5. **`test_dod_1` compares the *latest* rubric commit** (`log -1`) against the *first* label commit, so a legitimate rubric v2 after labelling fails it. Compare the **first** rubric commit for "authored before", and separately assert no post-labelling rubric edit without a version bump.
6. **Long-baseline drift dies after five rotations.** `rotate_private_split` retires the oldest items, so release 1 and release 6 share nothing and `cohort_intersection` returns ∅. Either hold a permanent non-rotating anchor subset (say 60 items, never rotated, accepting and *reporting* their higher contamination risk), or state that comparisons beyond four releases are unavailable.
7. **Skipped tests are used as release gates.** `publish.yml` (Task 49) makes `test_reproducibility.py` and `test_contamination.py` "blocking", but both `pytest.skip` when `data/results.duckdb` is absent — which it always is in a fresh checkout, since `data/*.duckdb` is gitignored. A skipped test is a green tick with nothing behind it. Add a `GT_REQUIRE_DB=1` guard that turns those skips into failures, and set it in the release workflow.

---

# Recommended order of work

**Before any provider call is made** — these change what gets measured or leaked:
**B1 · B2 · B4 · H1 · H7 · H8 · M1 · M2**

**Before any number is published** — these change what the numbers mean:
**B3 · B5 · H4 · H5 · H10 · M3 · M5 · M6 · M7 · M8**

**Before Task 1 Step 7**, or nothing runs at all:
**H2 · H13**

**Then:** H3 · H6 · H9 · H11 · H12 · H14, security gaps S1–S8, and the performance items.

One sequencing constraint worth naming: `docs/analysis-plan.md` is frozen before the first sweep, and **B3 and B5 change it**. Settle both *before* the freeze, or the first published release carries an amended plan plus a changelog entry explaining why. Fixing them after the freeze is survivable and honest. Discovering them after publication is not.
