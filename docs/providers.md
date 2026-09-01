# Provider audit

> **PLACEHOLDER SCAFFOLD — THIS IS NOT A COMPLETED PROVIDER AUDIT.**
>
> Every provider name, price, URL, rate limit, and quote in the table below
> is a fabricated stand-in, not data collected from a real provider account.
> Phase 1 Task 2's Step 1 — the real field audit against live accounts on
> Google AI Studio, Groq, OpenRouter, Mistral, Cloudflare Workers AI,
> SambaNova, Cerebras, GitHub Models, and NVIDIA NIM — **has not been
> performed.** No provider listed here was contacted; no price was looked
> up; no terms page was read.
>
> This file exists solely so that `models.yaml` has a matching entry for
> `tests/test_providers_manifest.py`'s `test_every_slot_is_documented`
> check, unblocking Task 15's dependency on `models.yaml` existing. The
> human partner must perform the real audit and replace every row in this
> table — and every value in `models.yaml` — with measured, dated, cited
> results before any of these figures are used for a cost claim, a sweep,
> or the published leaderboard.

## Table

| provider | reachable | free_model_ids | rpm | tpm | rpd | trains_on_data | commercial_use | exposes_fingerprint | vision | list_price_in_per_1m | list_price_out_per_1m | pricing_url | terms_url | terms_quote | retrieved_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| placeholder-provider-a | N/A — not contacted | PLACEHOLDER-MODEL-REF-A | N/A | N/A | N/A | false | true | false | N/A | 0.10 | 0.40 | https://example.invalid/pricing | https://example.invalid/terms | "[PLACEHOLDER — real terms quote pending field audit]" | 2026-08-31 |
| placeholder-provider-b | N/A — not contacted | PLACEHOLDER-MODEL-REF-B | N/A | N/A | N/A | false | true | false | N/A | 1.00 | 2.00 | https://example.invalid/pricing | https://example.invalid/terms | "[PLACEHOLDER — real terms quote pending field audit]" | 2026-08-31 |

`placeholder-provider-a` corresponds to `models.yaml`'s `slots.slot-a`; `placeholder-provider-b` corresponds to `judge_slots.judge-a`. Neither name refers to a real vendor.
