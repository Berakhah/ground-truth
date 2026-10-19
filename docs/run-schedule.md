# Run schedule for the real sweep (DRAFT)

> **Status: draft, 2026-10-19. Not executable yet.** Every limit below comes from
> `providers-desk-research.md` (retrieved 2026-09), not from a live account. `.env` holds no
> provider keys, so nothing has been probed. Items marked **[PROBE]** are measured in Phase 0 and
> replace the desk-research figure before any dispatch. Nothing here is a cost figure; list prices
> are fetched separately (rule 5).
>
> This is the pre-run plan. The observed schedule and wall-clock go in `methodology.md` after the sweep.

## 1. What has to run

| stage | calls | arithmetic |
|---|---|---|
| Generation | 9,000 | 300 items x 6 slots x 5 replicates (rule 6) = 1,500 per slot |
| Judge | 5,400 | 300 items x 6 slots x n=3 majority vote, on the modal output (`select_judge_targets`) = 900 per slot |
| Probe | ~10 | one synthetic call per provider, never a golden item |

Judge calls only exist for `LINE_ITEM_DESCRIPTION`, the one `grader: judge` field. They cannot start
for a slot until that slot's five replicates for the item are done (the modal output needs all five).

## 2. Binding constraint per provider

Published ceilings (desk research, **to be re-verified**):

| provider | slots | ceiling | what binds |
|---|---|---|---|
| Groq | A gpt-oss-120b, B qwen3.8-27b | 30 RPM, 1K RPD, 8K TPM, 200K TPD | **Tokens, not requests.** 1,500 calls fit in 1K RPD only over 2 days, but 200K TPD allows only ~133 calls/day at 1,500 tokens each. **[PROBE]** real tokens per call. |
| Cloudflare | C llama-3.1-8b, D DeepSeek V4 Pro | 10,000 neurons/day, one shared pool | Neurons per call, per model. **[PROBE]** The pool is shared by both slots, and DeepSeek is likely to cost far more neurons per call. |
| Mistral | E small-2603 | hidden in console | **[PROBE]** read limits from the admin console. Opt-out must be on first. |
| Google | F Gemini 2.5 Flash-Lite | hidden in console | **[PROBE]** read limits from AI Studio. |
| Cerebras | judges | 5 RPM, 30K TPM, 1M TPD | 5 RPM: 5,400 calls take at least 18 h if Cerebras carries all of them. |
| SambaNova | judges | 20 RPM, **20 RPD**, 200K TPD | ~600 calls/month. Cannot carry meaningful judge volume. |

Per-provider days, to fill after the probe:

```
days = max( calls / RPD,
            calls x tokens_per_call / TPD,
            calls / (RPM x usable_minutes_per_day) )
```

Illustration with the Groq numbers above, not a measurement: if a call costs 1,500 tokens, then
1,500 calls / (200,000 / 1,500 = 133 per day) is about 11 days per slot. If slots A and B share
the TPD pool, about 22 days. The probe decides this. Do not plan from the illustration.

**Open finding:** SambaNova cannot be a judge-pool carrier at 20 RPD. The "4-judge pool on
Cerebras / SambaNova" decision needs revisiting if the probe confirms that, since judges would
then all share Cerebras' 5 RPM. The lineup is your decision, so I am flagging it rather than
changing it.

## 3. Phases

**Phase 0: probe (one sitting, ~1 h).** One synthetic prompt per provider. Record: reachable,
raw-response fingerprint fields (or "none exposed"), actual limits and reset time, tokens per
call, neurons per call. Confirm Mistral opt-out is on. Update `models.yaml` and `docs/providers.md`
with real values, and re-fetch and date every price.

**Phase 1: pilot (~30 min).** 10 items x 1 replicate x 6 slots. Checks the prompt, parsing, ledger
rows (provider recorded per call), and gives a token-per-call number from real invoices rather
than a probe string. Re-run the formula in section 2.

**Phase 2: generation, parallel lanes.** One lane per provider so a slow provider never idles the
others. Each lane drains at its own binding limit and sleeps at its daily ceiling.
- **Order: replicate-major** (all items at replicate 1, then replicate 2, ...). Partial results are
  usable early, and an interruption leaves complete replicate layers rather than a few items at n=5.
  Tradeoff: replicates then span days, so a silent model update mid-sweep shows up as variance.
  The recorded timestamp and fingerprint let the analysis check this. Say so in the methodology.
- Cached responses are replayed, never re-spent. Resume with the same `--sweep-id`
  (`pending_work` skips what is recorded).
- Start the long lanes first (Groq, Cloudflare), the short ones fit around them.

**Phase 3: judge.** Starts per slot as that slot finishes. Runs on Cerebras overnight, one block of
about 18 h if Cerebras carries it all. Order effects are tested per the bias controls.

**Phase 4: grade, publish.** Deterministic grading was about 4 min for a full simulated run, so it
is not on the critical path. Then `security-review` before any publish step (CLAUDE.md gate), and
a reproducibility re-run from raw results.

## 4. Operating rules

- Overnight windows: free-tier daily resets are provider-specific and **[PROBE]**. Do not assume
  midnight local time. Schedule each lane to start just after its own reset.
- On a 429, back off and resume. Never fall back to a different provider for the same slot: it would
  measure a different serving stack. A call that was served elsewhere is recorded and excluded.
- Fingerprint: record what the response exposes, and say "none exposed" for providers without one.
- Latency from free tiers is reported as a distribution with the caveat, not ranked.
- Log per day: calls done per slot, calls remaining, 429 count, provider that served each call.

## 5. Code gaps that block a live run

1. ~~`plan_batches` chunked by RPD only and per slot.~~ **Fixed 2026-10-19.** It now packs days per
   provider pool, bounded by RPD and an optional daily token budget. It is not yet passed real
   values: `main()` still needs the probe's tokens-per-call and daily budgets. RPM/TPM pacing is
   a dispatch-time concern and is still unhandled.
2. ~~`_load_items` built items with `fields=[]`.~~ **Fixed 2026-10-19.** It reads `item_fields` and
   the corpus `.txt` verbatim, and raises if a file is missing. A live sweep needs `golden/corpus`
   (including the gitignored private split) on the sweep machine.
3. `bok_core` is not installed here, and `_bok_shim.remaining()` returns an unbounded quota. A plan
   built against the shim will look fine and then 429.
4. Judge orchestration is unwired: nothing calls `select_judge_targets` or `sample_judgements` yet.
5. `models.yaml` is still the placeholder scaffold and must not be run.

Items 3 to 5 remain. Any code for them is `runner/` or `judge/` work, so TDD applies.
