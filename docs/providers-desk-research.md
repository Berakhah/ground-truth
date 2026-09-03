# Provider desk research — worksheet for Phase 1 Task 2, Step 1

> **THIS IS NOT THE AUDIT. It is unverified desk research, and nothing here may
> be copied into `models.yaml` or `docs/providers.md` as-is.**
>
> Every figure below was read off a public vendor page on **2026-09-03** and is
> cited with the URL it came from. None of it was confirmed against an account,
> from the machine that will run the sweeps. Task 2 Step 1 requires exactly that
> confirmation, and three of the sixteen columns cannot be filled from a public
> page at all. This file exists so the human partner starts from a draft to
> falsify rather than a blank sheet.
>
> Provenance rule: a cell here is admissible only once you have re-read it on
> your own account and re-dated it. `terms_quote` must be the **verbatim
> sentence** — every quote below is verbatim from the cited page, but at least
> one comes from the wrong document (see Groq) and must be re-sourced.

## Three findings that change the plan

**1. GitHub Models is gone. Drop it from the nine.**

GitHub's own docs: *"As of July 30, 2026, GitHub Models has been fully retired."*
and *"The playground, model catalog, inference API, and bring your own key (BYOK)
are no longer available to any customer."*
— https://docs.github.com/en/github-models (retrieved 2026-09-03)

No audit row is possible. The candidate list is eight, not nine.

**2. Two providers train on free-tier input by default. That collides with the golden set.**

The golden set is confidential pay-application and invoice text. Sending it to a
free tier that trains on it is a client-data disclosure, not a rate-limit
inconvenience — and this repo has already leaked client data once.

- **Google AI Studio / Gemini free tier — trains.** Verbatim: *"When you use
  Unpaid Services, including, for example, Google AI Studio and the unpaid quota
  on Gemini API, Google uses the content you submit to the Services and any
  generated responses to provide, improve, and develop Google products and
  services and machine learning technologies."*
  — https://ai.google.dev/gemini-api/terms (retrieved 2026-09-03)
- **Mistral free "Experiment" tier — reported to train by default, with a manual
  opt-out.** Secondary sources only; the canonical page
  (`docs.mistral.ai/deployment/laplateforme/tier`) now 404s and live limits sit
  behind `admin.mistral.ai/plateforme/limits`. **Unverified — read this one on
  your account before trusting it either way.**
- **Cloudflare Workers AI — does not train.** Verbatim: *"Unless otherwise
  agreed, Cloudflare does not use any Customer Content to train generative AI
  tools."*
  — https://www.cloudflare.com/service-specific-terms-developer-platform/ (retrieved 2026-09-03)
- **OpenRouter — per-model, not per-platform.** Verbatim: *"Some Models may store
  or train on your Inputs for improving their own large language models and may
  allow you to opt-out of model training"* and *"Where possible, OpenRouter has
  opted out of model training with the Models it uses."*
  — https://openrouter.ai/terms (retrieved 2026-09-03)
  So `trains_on_data` is a property of the routed model, not of OpenRouter, and
  must be recorded per `:free` model ref.

This is a decision for you, not a cell in a table: either the sweep runs only
against non-training providers, or the golden set gets a synthetic/redacted
variant for the training ones. It changes which slots exist.

**3. The published free-tier ceilings are tighter than the 15,000-call budget assumes.**

All retrieved 2026-09-03:

| provider | free ceiling (published) | source |
|---|---|---|
| SambaNova | **20 RPM / 20 RPD / 200K TPD** — twenty requests *per day* | https://docs.sambanova.ai/docs/en/models/rate-limits |
| OpenRouter `:free` | 20 RPM / **50 RPD** (1,000 RPD after $10 lifetime credit) | https://openrouter.ai/docs/api-reference/limits |
| Cerebras | 5 RPM / 30K TPM / 1M TPH / **1M TPD** | https://inference-docs.cerebras.ai/support/rate-limits |
| Groq (`openai/gpt-oss-120b`, `qwen/qwen3.8-27b`) | 30 RPM / 1K RPD / 8K TPM / 200K TPD | https://console.groq.com/docs/rate-limits |
| Cloudflare Workers AI | 10,000 Neurons/day free allocation | https://developers.cloudflare.com/workers-ai/platform/pricing/ |
| NVIDIA NIM (build.nvidia.com) | 40 RPM free tier — **secondary sources only, unverified** | forums.developer.nvidia.com |
| Google AI Studio | **not published** — "can be viewed in Google AI Studio" | https://ai.google.dev/gemini-api/docs/rate-limits |
| Mistral | **not published** — see Admin Console → Limits | https://admin.mistral.ai/plateforme/limits |

At 20 RPD, SambaNova contributes roughly 600 calls a month. The multi-night
schedule has to be built around the two or three providers that can actually
carry volume, not spread evenly across eight.

## OpenRouter `:free` — the training policy is per endpoint, and the API will not tell you

All of this was retrieved **2026-09-03** and carries the same `[draft]` standing as
everything above: public, dated, cited, and **not yet re-read on your own account**.
The `:free` policy table in particular is a scrape of an undocumented surface — treat
it as a draft to falsify, not as an audit row.

**The documented API cannot answer the question.** `GET https://openrouter.ai/api/v1/models`
returns 424 models over 701KB and carries no policy field at all. The union of every key
path across all 424 objects is: `alias_target, architecture, benchmarks, canonical_slug,
context_length, created, default_parameters, description, expiration_date, hugging_face_id,
id, knowledge_cutoff, links, name, per_request_limits, pricing, reasoning,
supported_parameters, supported_voices, top_provider`. Zero occurrences of `data_policy`,
`trains`, `privacy`, `retention` or `data_collection`.
`GET /api/v1/models/{author}/{slug}/endpoints` is the same story, and
`GET /api/v1/providers` (105 providers) gives only `privacy_policy_url` /
`terms_of_service_url` — links, not a machine-readable flag.

**Where the data actually lives.** OpenRouter's own docs page renders its public
data-retention table by fetching `https://openrouter.ai/api/frontend/v1/all-providers`
(public, no auth, 83 providers). Each provider carries `dataPolicy.training`,
`.trainingOpenRouter`, `.retainsPrompts`, `.retentionDays`, `.canPublish`,
`.requiresUserIDs`. The page's own renderer keys off `training` alone — "May train"
versus "Does not train" — and ignores every other field.
— https://openrouter.ai/docs/guides/privacy/provider-logging

**Caveat that has to travel with the number:** `/api/frontend/…` is not in the API
reference. It is vendor-served and vendor-referenced, but undocumented and unversioned —
a scrape target that can break, not a contract. `/api/frontend/v1/models` returns 401.

### The distinction that bites: per model x provider endpoint, not per provider

Finding 2 above says `trains_on_data` is per routed model. It is tighter than that. Each
model page embeds a per-**endpoint** `data_policy` object, and a `:free` variant can be
worse than the same provider's default:

| provider | provider-level (`all-providers`) | its `:free` endpoint |
|---|---|---|
| Poolside | `training: false` | `training: true` |
| Nvidia | `trainingOpenRouter: false` | `trainingOpenRouter: true` |
| Thinking Machines | `training: true` | same |

So the cheap one-call approach — read `all-providers` and trust it — is **over-permissive
and unsafe as the sole gate**. It clears Poolside's free tier, which trains.

`trainingOpenRouter` appears nowhere in OpenRouter's documentation (zero hits across
`provider-logging`, `provider-selection`, and `llms.txt`). The plain reading is "trains
specifically on traffic arriving via OpenRouter", but that is **unverified** — the public
table ignores the field entirely.

### The 18 `:free` models and their published policy

From `/api/v1/models` (id ends `:free`, `pricing.prompt == "0"`), joined to the
endpoint-level `data_policy` embedded in each model's own page. All 18 have exactly one
endpoint. **Trains on input — 10 of 18:**

| model | provider | `training` | `trainingOpenRouter` |
|---|---|---|---|
| `nvidia/nemotron-3.5-lightning:free` | Nvidia | true | true |
| `nvidia/nemotron-3.5-content-safety:free` | Nvidia | true | true |
| `nvidia/nemotron-3-ultra-550b-a55b:free` | Nvidia | true | true |
| `nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free` | Nvidia | true | true |
| `nvidia/nemotron-3-super-120b-a12b:free` | Nvidia | true | true |
| `thinkingmachines/inkling:free` | Thinking Machines | true | true |
| `thinkingmachines/inkling-small:free` | Thinking Machines | true | true |
| `liquid/lfm-2.5-2.6b:free` | Liquid | true | false |
| `poolside/laguna-s-2.1:free` | Poolside | true | false |
| `poolside/laguna-xs-2.1:free` | Poolside | true | false |

**Does not train — 8 of 18**, but most still retain:

| model | provider | `retainsPrompts` | `retentionDays` |
|---|---|---|---|
| `z-ai/glm-5.2:free` | Decart | false | — (zero retention) |
| `inclusionai/ling-3.0-flash-fin:free` | Novita | false | — (zero retention) |
| `google/gemma-4-31b-it:free` | Google AI Studio | true | 55 |
| `google/gemma-4-26b-a4b-it:free` | Google AI Studio | true | 55 |
| `cohere/north-mini-code:free` | Cohere | true | 30 |
| `minimax/minimax-m3:free` | GMICloud | true | unspecified |
| `minimax/minimax-m2.7:free` | GMICloud | true | unspecified |
| `dots-studio/dots-3-note-preview:free` | AtlasCloud | true | unspecified |

Only two `:free` endpoints are both non-training **and** zero-retention:
`z-ai/glm-5.2:free` (Decart) and `inclusionai/ling-3.0-flash-fin:free` (Novita).

Three free-tier providers set `requiresUserIDs: true` (Nvidia, Thinking Machines, Liquid)
— they require a user identifier be forwarded, which matters for any pay-application or
invoice content routed there.

Worth noting against finding 2: `google/gemma-4-31b-it:free` **routed via OpenRouter**
reports `training: false` with 55-day retention — the opposite of Google AI Studio direct,
which trains. Same model family, different data terms depending on how you reach it.

### There is a never-route-to-a-training-provider control, and it is off by default

Verbatim, https://openrouter.ai/docs/guides/routing/provider-selection:

> You can restrict requests only to providers that comply with your data policies using
> the `data_collection` field. […] `allow`: (default) allow providers which store user
> data non-transiently and may train on it. `deny`: use only providers which do not
> collect user data.

> Some model providers may log prompts, so we display them with a Data Policy tag on model
> pages. **This is not a definitive source of third party data policies, but represents our
> best knowledge.**

Request shape: `{"provider": {"data_collection": "deny"}}`. The same page notes it is also
an account-wide privacy setting. Verbatim,
https://openrouter.ai/docs/guides/privacy/provider-logging:

> On your account settings page, you can set whether you would like to allow routing to
> providers that may train on your data (according to their own policies). **There are
> separate settings for paid and free models.** […] If you opt out of training in your
> account settings, OpenRouter will not route to providers that train.

Two caveats for the methodology page: OpenRouter itself calls its Data Policy tag "not a
definitive source", and `data_collection: "deny"` is defined as excluding providers that
"store user data non-transiently **and** may train on it" — a storage filter that subsumes
training, not a training-only filter. A separate adjacent flag, `zdr` (boolean), restricts
routing to zero-data-retention endpoints; retention and collection are different controls.

### What this changes for us

- `SlotSpec.trains_on_data` is already per slot, and a slot is a model x provider pairing,
  so the schema models this at the right granularity. **No schema change needed** — but the
  value recorded for an OpenRouter slot must come from that slot's own endpoint block, not
  from `all-providers` and not from the provider's public reputation.
- `ground_truth/policy.py` now refuses to dispatch a `CLIENT_CONFIDENTIAL` payload to any
  slot whose manifest row says `trains_on_data: true` (or `commercial_use: false`), and
  fails closed on a slot that is not declared at all. It reads `models.yaml`, so it is only
  as good as the audit behind it — the last line, not the only one.
- **The request-level flag is an operator prerequisite, not code in this repo.** `call_fn`
  is bok-core's router and its signature is contract-fixed; provider request options belong
  to lane configuration. Before any OpenRouter slot carries real client text: set the
  account-level opt-out for **free** models (it is separate from the paid one), and ensure
  the lane sends `{"provider": {"data_collection": "deny"}}`.

### What could not be determined without your account

- Whether `data_collection: "deny"` actually excludes those 10 training `:free` endpoints
  in practice. Docs semantics only, untested — verifying needs a real request with a key
  and an inspection of which endpoint served it.
- `GET /api/v1/models/user` — the model list filtered by the account's own privacy
  settings, and the canonical way to enumerate "models I am permitted to route to". Returns
  401 unauthenticated. **This is the endpoint the harness should use once it has a key**,
  in place of scraping model pages.
- `/api/frontend/v1/models` — 401. Likely the authenticated source pairing each variant
  with its endpoint `data_policy` in one call. Unconfirmed.
- `https://openrouter.ai/settings/privacy` — redirects to sign-in, so the exact labels and
  granularity of the paid-vs-free training toggles could not be read.
- The semantics of `trainingOpenRouter`, and whether request-level `data_collection`
  combines with the account setting as OR or AND (the docs state the OR rule only for `zdr`).

## What only you can fill in

Three columns are unreachable from a public page, by design:

- **`reachable`** — whether signup succeeds from your machine and region.
- **`exposes_fingerprint`** — Task 2 Step 1 requires one real call per provider
  with the entire response body dumped. Do not infer it. If nothing version-like
  is in the body, record `false`.
- **`rpm` / `tpm` / `rpd` for Google and Mistral** — both now hide free-tier
  limits behind the authenticated console.

And two cells are deliberately left empty rather than filled from a bad source:

- **Groq `terms_quote`.** The public website terms say *"we grant you a limited,
  non-exclusive, non-transferable, license to access and use the Websites for
  your personal, non-commercial use only"*
  — https://groq.com/terms-and-conditions (retrieved 2026-09-03).
  That governs the **website**, not the API, and it points at a separate Groq
  Services Agreement. Quoting it as the API's commercial-use term would be
  wrong. Pull the verbatim sentence from the Services Agreement you accept at
  signup. The same page says nothing about training on customer data.
- **Groq / SambaNova / Cerebras / Mistral / NVIDIA list prices.** Every figure
  found was on a third-party aggregator; `console.groq.com/docs/pricing` 404s
  unauthenticated and `cerebras.ai/pricing` shows only "$5 in free credits" and
  a Developer tier "at just $10" with no per-token table. Rule 5 says cite the
  vendor or don't cite. Read them from your console.

## List prices captured (paid tier — the cost column, labelled as list price)

Verbatim, https://ai.google.dev/gemini-api/docs/pricing, retrieved 2026-09-03:

| model | in /1M | out /1M |
|---|---|---|
| Gemini 2.5 Flash-Lite | $0.10 (text/image/video), $0.30 (audio) | $0.40 |
| Gemini 2.5 Flash | $0.30 (text/image/video), $1.00 (audio) | $2.50 |
| Gemini 2.5 Pro | $1.25 (≤200k prompt) / $2.50 (>200k) | $10.00 / $15.00 |
| Gemini 3.5 Flash-Lite | $0.30 | $2.50 |
| Gemini 3.5 Flash | $1.50 | $9.00 |
| Gemini 3.8 Flash | $0.75 through 2026-12-31, $1.50 from 2027-01-01 | $3.75 through 2026-12-31, $7.50 from 2027-01-01 |

Verbatim, https://developers.cloudflare.com/workers-ai/platform/pricing/, retrieved 2026-09-03:

| model | in /1M | out /1M |
|---|---|---|
| Llama 3.2 1B | $0.027 | $0.201 |
| Llama 3.1 70B | $0.293 | $2.253 |
| DeepSeek V4 Pro | $1.320 | $3.960 |

The Gemini 3.8 Flash row carries a scheduled price change. Whatever you record,
`retrieved_at` has to make clear which side of 2026-12-31 the figure sits on,
and the leaderboard's cost column needs re-dating in January.

## Family diversity (Never-rule 4)

`family` is a property of the **model**, not the provider — several providers
serve several families, so one provider can supply both a slot and a
disqualified judge. Observed on public model lists, 2026-09-03:

- Groq serves `openai/gpt-oss-*` and `qwen/qwen3.x` — two families, one provider.
- SambaNova serves DeepSeek, Llama, gpt-oss and Gemma — four families.
- Cerebras serves `gpt-oss-120b` and `gemma-4-31b` — Gemma is Google's family,
  so a Gemma judge against a Gemini slot is a same-family conflict even though
  the providers differ.

Family diversity is not the binding constraint; finding 2 is. Declare `family`
from the model card, and make sure the judge's declared family differs from every
slot it scores — `assert_judge_family_differs` only checks the string you wrote.

## Worksheet

Fill this in from your accounts, then it becomes `docs/providers.md`.
`[YOU]` = must come from your account or a live call. `[draft]` = pre-filled from
a public page above, still needs your confirmation and a fresh date.

| provider | reachable | free_model_ids | rpm | tpm | rpd | trains_on_data | commercial_use | exposes_fingerprint | vision | list_price_in_per_1m | list_price_out_per_1m | pricing_url | terms_url | terms_quote | retrieved_at |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| google-ai-studio | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [draft] true | [YOU] | [YOU] | [YOU] | [draft] | [draft] | https://ai.google.dev/gemini-api/docs/pricing | https://ai.google.dev/gemini-api/terms | [draft — verbatim above] | [YOU] |
| groq | [YOU] | [draft] | [draft] 30 | [draft] 8K | [draft] 1K | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU — website ToS is the wrong doc] | [YOU] |
| openrouter | [YOU] | [draft] 18 `:free` variants | [draft] 20 | [YOU] | [draft] 50 | [draft] per model x provider **endpoint** -- 10 of 18 `:free` train; see the OpenRouter section | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | https://openrouter.ai/terms | [draft — verbatim above] | [YOU] |
| mistral | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU — reported true] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] |
| cloudflare-workers-ai | [YOU] | [YOU] | [YOU] | [YOU] | [draft] 10K neurons/day | [draft] false | [YOU] | [YOU] | [YOU] | [draft] | [draft] | https://developers.cloudflare.com/workers-ai/platform/pricing/ | https://www.cloudflare.com/service-specific-terms-developer-platform/ | [draft — verbatim above] | [YOU] |
| sambanova | [YOU] | [draft] | [draft] 20 | [YOU] | [draft] 20 | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] |
| cerebras | [YOU] | [draft] | [draft] 5 | [draft] 30K | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] |
| nvidia-nim | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] | [YOU] |
| github-models | **RETIRED 2026-07-30 — do not audit** | — | — | — | — | — | — | — | — | — | — | — | https://docs.github.com/en/github-models | "As of July 30, 2026, GitHub Models has been fully retired." | 2026-09-03 |
| cohere | not configured | — | — | — | — | — | **false** (pre-flagged) | — | — | — | — | — | [YOU] | [YOU] | [YOU] |

## Sources

- [Gemini API rate limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- [Gemini API pricing](https://ai.google.dev/gemini-api/docs/pricing)
- [Gemini API additional terms of service](https://ai.google.dev/gemini-api/terms)
- [Groq rate limits](https://console.groq.com/docs/rate-limits)
- [Groq terms and conditions](https://groq.com/terms-and-conditions)
- [OpenRouter API rate limits](https://openrouter.ai/docs/api-reference/limits)
- [OpenRouter terms of service](https://openrouter.ai/terms)
- [OpenRouter provider logging and data policies](https://openrouter.ai/docs/guides/privacy/provider-logging)
- [OpenRouter provider selection -- `data_collection`, `zdr`](https://openrouter.ai/docs/guides/routing/provider-selection)
- [OpenRouter models endpoint](https://openrouter.ai/api/v1/models), [providers endpoint](https://openrouter.ai/api/v1/providers)
- [OpenRouter all-providers data policies -- undocumented, vendor-served](https://openrouter.ai/api/frontend/v1/all-providers)
- [Cloudflare Workers AI pricing](https://developers.cloudflare.com/workers-ai/platform/pricing/)
- [Cloudflare developer platform service-specific terms](https://www.cloudflare.com/service-specific-terms-developer-platform/)
- [SambaNova rate limits policy](https://docs.sambanova.ai/docs/en/models/rate-limits)
- [Cerebras inference rate limits](https://inference-docs.cerebras.ai/support/rate-limits)
- [Cerebras pricing](https://www.cerebras.ai/pricing)
- [GitHub Models (retirement notice)](https://docs.github.com/en/github-models)
- [Mistral rate limits and usage tiers (admin console)](https://admin.mistral.ai/plateforme/limits)
