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

## Current audit status (2026-09-23)

Three desk-research passes are complete and consolidated in
[`providers-desk-research.md`](providers-desk-research.md). **This is not the
field audit.** `SlotSpec` (`ground_truth/providers.py`) requires a committed
`bool` for `trains_on_data` and `commercial_use` and a cited `Decimal` list
price — there is no "unverified" value the schema can hold, and `policy.py`
uses `trains_on_data`/`commercial_use` as the fail-closed gate before any
`CLIENT_CONFIDENTIAL` payload is dispatched. Writing a best-guess boolean into
`models.yaml` for a field the desk research could not close would mean
fabricating the exact safety signal that gate depends on — worse than leaving
the placeholder in place. So `models.yaml` stays a placeholder scaffold until
each candidate provider is confirmed from a real, authenticated account.

**Candidates: 8, not the original 9.** GitHub Models retired 2026-07-30
(`docs.github.com/en/github-models`) and is dropped.

| provider | reachable | trains_on_data | commercial_use (free tier) | list price (vendor-cited) | exposes_fingerprint | status |
|---|---|---|---|---|---|---|
| google-ai-studio | `[YOU]` | **true** — confirmed twice, verbatim quote in desk research | unresolved (ToU targets "professional/business" use, but trains by default — disqualifying for confidential input either way) | confirmed (Gemini 2.5/3.5/3.8 tables, `ai.google.dev/gemini-api/docs/pricing`) | documented (`modelVersion`/`responseId` fields), not yet observed on a live call | **disqualified for confidential data** — trains on free-tier input |
| groq | `[YOU]` | provisional **false** (Services Agreement clause found, not free-tier-scoped) | `[YOU]` | `[YOU]` — no vendor page renders a price table; only a 17-month-stale blog post found | `[YOU]` | rate limits confirmed (30 RPM / 8K TPM / 1K RPD, `openai/gpt-oss-20b`) |
| openrouter | `[YOU]` | **per-endpoint, not per-provider** — 10 of 18 `:free` models train; see desk research's endpoint table before routing any specific model | `[YOU]` | `[YOU]` (per routed model) | `[YOU]` | requires per-model `data_policy` lookup at slot-selection time, not a single provider-level flag |
| mistral | `[YOU]` | provisional **true** with opt-out (Privacy Policy + DPA, confirmed via two independent primary sources); tier-specific (free vs. paid) behavior still open | `[YOU]` | confirmed: `mistral-small-2603` $0.15 in / $0.60 out per 1M (`docs.mistral.ai/inference/pricing`) | `[YOU]` | opt-out mechanism exists in Admin Console; must be set before any confidential payload |
| cloudflare-workers-ai | `[YOU]` | **false** — two independent Cloudflare pages agree | unresolved specifically for the free tier | confirmed (e.g. `@cf/meta/llama-3.1-8b-instruct-fp8` $0.045 in / $0.384 out per 1M) | `[YOU]` | strongest non-training candidate; commercial-use-on-free-tier is the one open item |
| sambanova | `[YOU]` | provisional **false** (Cloud EULA Customer-Content exclusion) | unresolved — open question on SambaNova's own community forum, no official answer on record | confirmed, full table (`cloud.sambanova.ai/plans/pricing`) | confirmed — `system_fingerprint` field present (e.g. `"fastcoe"`), undocumented semantics | free-tier ceiling is ~20 RPD, too thin to carry meaningful sweep volume alone |
| cerebras | `[YOU]` | `[YOU]` | `[YOU]` | provisional (JS-rendered table only, not cross-checked against a second source; one conflicting third-party claim about a 2026-07-21 tier change, unresolved) | confirmed — `system_fingerprint` field documented, format known | pricing needs a real-browser re-check before trusting |
| nvidia-nim | `[YOU]` | not a training question — **the API-catalog Terms of Use prohibit submitting confidential/sensitive content as User Content at all** (Section 6, PDF ToU) | `[YOU]` | none published for hosted endpoints (confirmed absent, not just unfound) | `[YOU]` | **disqualified for confidential data** by contract, independent of any training-policy finding |
| cohere | not configured | — | **false** (pre-flagged) | — | — | out of scope — not a sweep candidate |

**Two providers are disqualified for this repo's golden-set content on desk
research alone**, before any account check: Google AI Studio (trains on
free-tier input by default) and NVIDIA NIM (ToU contractually excludes
confidential/sensitive content). Both findings carry a verbatim citation in
`providers-desk-research.md`.

**What remains before any real row can enter `models.yaml`:** for each
surviving candidate (Groq, OpenRouter, Mistral, Cloudflare, SambaNova,
Cerebras) — sign up on the account that will run the sweep, confirm
`reachable`, make one real call and inspect the raw response body for
`exposes_fingerprint`, and (for the four still marked "unresolved") get an
explicit answer on free-tier commercial-use terms rather than inferring one.
See `providers-desk-research.md`'s "What only you can fill in" section for
the full list of account-gated fields.

## Lineup decisions (2026-09-29)

Decided by the human partner on 2026-09-29, from the desk research above. **Still not
the field audit:** no row enters `models.yaml` until the account-gated fields are
confirmed on a live account and every price is re-fetched and dated. As of this date
`.env` holds no provider key, so nothing below has been contacted.

**Why training providers are allowed at all.** Every golden item is synthetic (300 of
300: 180 private, 120 public; `items.source = 'synthetic'`). The Google and Mistral
disqualifications above are for *confidential* data, and `policy.assert_slot_may_see`
still enforces them: the moment a `CLIENT_CONFIDENTIAL` item is swept, a
`trains_on_data: true` slot is refused before dispatch. Nothing here relaxes that gate.

Models under test, one family each:

| slot | provider · model | family | trains_on_data (to confirm) | list price source |
|---|---|---|---|---|
| A | groq · `openai/gpt-oss-120b` | gpt-oss | false, provisional | console after signup — no citable public page |
| B | groq · `qwen/qwen3.8-27b` | qwen | false, provisional | console after signup |
| C | cloudflare-workers-ai · `@cf/meta/llama-3.1-8b-instruct-fp8` | llama | false | vendor page, cited |
| D | cloudflare-workers-ai · DeepSeek V4 Pro | deepseek | false | vendor page, cited |
| E | mistral · `mistral-small-2603` | mistral | false **only once the console opt-out is on and confirmed**; true otherwise | vendor page, cited |
| F | google-ai-studio · Gemini 2.5 Flash-Lite | google | **true** (free tier), recorded as such | vendor page, cited |

Judges (LINE_ITEM_DESCRIPTION only, the one `grader: judge` field in `docs/rubric.md`): a
pool of four from Cerebras / SambaNova, one per family: gemma (declared family `google`,
the same string as slot F, because `assert_judge_family_differs` compares strings and
Gemma is Google's lineage), llama-3.3-70b (`llama`), gpt-oss-120b (`gpt-oss`), qwen
(`qwen`). Each slot conflicts with at most one judge, so every slot keeps three eligible
judges for the n>=3 majority vote.

**Judge load: run 1 only.** The judge scores LINE_ITEM_DESCRIPTION on the first of the
five runs per item, not all five (roughly one fifth of the calls; SambaNova allows about
20 requests a day). The run-to-run variance of that field is therefore reported as not
measured, and the methodology page must say so. This is a design change still to be
implemented, test first, before the sweep.

**Still open, account-gated:** reachable, observed `exposes_fingerprint`, console-only
rate limits (Google, Mistral, Cloudflare neurons-per-call), Groq/Cerebras/SambaNova list
prices from the console, free-tier commercial-use terms (Cloudflare, SambaNova, Groq,
Cerebras), and Mistral's opt-out state.
