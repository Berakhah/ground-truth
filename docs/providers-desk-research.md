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

### Addendum sources (2026-09-04)

- [Mistral Privacy Policy](https://legal.mistral.ai/terms/privacy-policy)
- [Mistral Data Processing Addendum](https://legal.mistral.ai/terms/data-processing-addendum)
- [NVIDIA Technology Access Terms of Use (API-catalog / build.nvidia.com)](https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA_Technology_Access_TOU.pdf)
- [build.nvidia.com](https://build.nvidia.com)
- [SambaNova Cloud pricing](https://cloud.sambanova.ai/plans/pricing)
- [SambaNova Cloud Developer Tier announcement](https://sambanova.ai/blog/sambanova-cloud-developer-tier-is-live)
- [Cerebras pricing](https://www.cerebras.ai/pricing)
- [Groq — Llama 3 launch blog post (2024-04-20, dated pricing)](https://groq.com/blog/12-hours-later-groq-is-running-llama-3-instruct-8-70b-by-meta-ai-on-its-lpu-inference-enginge)

## Addendum — 2026-09-04

Second desk-research pass, chasing the four open threads only. Everything below is
new — nothing here restates a finding already in the sections above. Same standing
as everything else in this file: public, dated, cited, **not yet re-read on an
account**, so every `[draft]` here still needs your confirmation before it can move
into `models.yaml`.

**Retrieval-method caveat that applies to most of this addendum.** `legal.mistral.ai`,
`docs.mistral.ai`, `build.nvidia.com` and `cerebras.ai/pricing` are JS-rendered
single-page apps. A plain HTTP fetch of these URLs frequently returns only the
navigation shell, a 404, or a truncated document — which is very likely *why* the
first pass came up empty on several of these (its own log shows the same 404s and
empty pricing tables I got on a first attempt). Where a full page only rendered
through a JS-executing text-reader proxy (`r.jina.ai`), that is noted explicitly.
Treat those specific findings as needing a real-browser re-check on your account
before they're trusted, on top of the account-confirmation every `[draft]` already
needs — a headless proxy render is not a guaranteed-faithful mirror of the live page.

### 1. Mistral training policy — primary legal text located, tier-specific claim still open

The first pass could only find the training-on-free-tier claim on secondary
(aggregator) sites, because the canonical page it tried 404s. Mistral's actual
Privacy Policy and DPA are reachable — at different URLs, both under `legal.mistral.ai`,
both JS-rendered (see caveat above) — and do state a general (not tier-scoped)
training default with an opt-out right. Retrieved 2026-09-04 via `r.jina.ai` text-render
of the live pages:

**Privacy Policy**, https://legal.mistral.ai/terms/privacy-policy:
> To train our artificial intelligence models (large language models) to answer
> questions, generate text, translate, summarize and correct text, classify text,
> analyze feelings, etc.

Legal basis given for that processing: "Our legitimate interest in developing and
providing state-of-the-art large language models as part of the Mistral AI Products."
Retention for the stateless APIs: "we keep your Input and Output for the period
necessary to generate the Output and then for thirty (30) rolling days to monitor
abuse" (matches the 30-day figure the first pass already had from a different source —
now confirmed against the Privacy Policy itself, not just a secondary summary).
Opt-out mechanism, verbatim: "We've introduced a user control which allows you to
object to the use of your input and output data for model training directly from
your account."

**Data Processing Addendum**, https://legal.mistral.ai/terms/data-processing-addendum
(Section 2.3, Mistral acting as Controller):
> [Processing for] training its artificial intelligence models in accordance with
> its Privacy Policy, unless Customer is or has opted-out of training.

and, on in-app feedback specifically:
> if Customer provides feedback to Mistral AI by using the in-app "thumbs up" or
> "thumbs down" features (the "Feedback"), Mistral will use such Feedback as well
> as the associated Input and Output, as Controller, to train its artificial
> intelligence models, conduct research or improve the Mistral AI Products.

**What this does and doesn't resolve.** `[draft]`. Neither document names the
"Experiment" tier, "La Plateforme," or any other plan — the training-by-default-with-
opt-out language in both is written at the product level, not the tier level. The
tier-specific claim the first pass flagged ("free Experiment tier trains by default,
paid API/Enterprise doesn't, toggle lives in Admin Console → Privacy") still traces
only to Mistral's own support/docs content (`docs.mistral.ai/admin/security-access/privacy`,
`help.mistral.ai/en/articles/156194-...` and `.../455207-...`) — all four of those
URLs 404'd on direct fetch this pass, and per this task's own instructions a
support/docs page isn't the target document anyway. So: promoted from "reported on
aggregators, unverified" to "the general training-with-opt-out policy is confirmed
against Mistral's own Privacy Policy and DPA text" — but the specific free-vs-paid
mechanism is still `[YOU]`, unchanged. Note also a direct discrepancy worth flagging:
one fetch of the DPA reported an effective date of "July 27, 2026" and a second,
independent fetch of the same URL found no effective date anywhere in the document —
don't trust either date without eyes-on confirmation.

### 2. NVIDIA NIM (build.nvidia.com) — first genuinely new material for this row

**NVIDIA's own API-catalog Terms of Use, found and read in full.** Linked directly
from build.nvidia.com's footer: https://assets.ngc.nvidia.com/products/api-catalog/legal/NVIDIA_Technology_Access_TOU.pdf
("NVIDIA Technology Access Terms of Use," retrieved and read as a PDF 2026-09-04,
copyright line at the foot reads "© 2024 NVIDIA Corporation" — no separate
"last updated" banner was present in the document itself, so treat 2024 as a lower
bound on currency, not a confirmed effective date). This is the terms document that
actually governs build.nvidia.com API access, distinct from the general
`nvidia.com/en-us/about-nvidia/terms-of-service/` the first pass found (which governs
NVIDIA's corporate site generally, not this API surface specifically).

Section 6 ("User Content"), the training-adjacent grant, verbatim:
> When you provide, make available or create User Content, other than Feedback, to
> or through your use of Technology, you grant NVIDIA, its affiliates and their
> service providers a worldwide license to User Content to use, host, store,
> reproduce, modify, create derivative works [...] solely to (a) provide you with
> the Technology, including NVIDIA Services, (b) provide you support, or for
> security reasons, and (c) modify and improve NVIDIA products or services or the
> technology underlying the Technology.

That (c) clause is a broad "improve the technology" grant over submitted content —
not an explicit "train AI models on your prompts" statement, but close enough that
it should be read as functionally equivalent for the audit's purposes pending your
own reading.

**More load-bearing for this repo's Never-rule 1**, same section, "Limitations on
User Content" — the ToU affirmatively prohibits submitting confidential or sensitive
data as User Content in the first place:
> Unless expressly permitted via a Product Agreement, you agree that your actions
> and transmission of User Content: (a) does not include any confidential
> information; (b) does not include any controlled or sensitive data, including
> (but not limited to) protected health information, personal data, payment card
> industry information or sensitive human subject research[.]

That's a contractual prohibition on sending confidential material at all, not just a
training-opt-out question — pay-application / invoice text is exactly the kind of
material this clause is written to exclude. Worth a note next to the
`policy.py` fail-closed behavior described earlier in this file: even before
`trains_on_data` is known, NVIDIA's own ToU already says don't send it confidential
content, full stop.

Also in the ToU, Section 7 ("Trial and Other Promotional Offerings"), confirming the
free tier's legal framing: "NVIDIA may offer free or discounted pricing programs for
the Technology for trial, evaluation or academic use [...] Standard charges will
apply after a promotional offering ends or if you exceed the promotional offering
use terms."

**Rate limit.** `[draft]`, not `[YOU]`-closing. Both `https://build.nvidia.com` and
`https://build.nvidia.com/settings/api-keys` rendered (via the JS-proxy caveat above)
the same FAQ text: "All models on build.nvidia.com are free to prototype with [...]
The free tier runs on rate limits - up to 40 requests per minute (RPM) for most
models, with no per-token billing." This matches the number the first pass already
had from developer-forum posts, but this is the first time it's been traced to
NVIDIA's own site rather than a forum thread — still needs a real-browser check
because of the proxy-rendering caveat, and it's an FAQ answer ("most models"), not a
per-model published limit.

**Pricing — still nothing.** No per-token price list exists on build.nvidia.com for
the hosted endpoints; confirmed again this pass. The free tier is rate-limited
access with no billing, and production use requires a separate NVIDIA AI Enterprise
license whose price is not published on a page we could cite (every figure found for
it this pass was aggregator-sourced, so per rule 5 it is omitted here, not guessed).

### 3. Groq / SambaNova / Cerebras — one real find, one partial, one still closed

**SambaNova — new, and this one clears the "no vendor citation" gap.**
https://cloud.sambanova.ai/plans/pricing is public and required no login — confirmed
by fetching it directly with a plain HTTP request, not just the JS-proxy (unlike
every other finding in this addendum, this one does not carry the proxy-reliability
caveat). Retrieved 2026-09-04, full table:

| model | cached input /1M | input /1M | output /1M |
|---|---|---|---|
| MiniMax-M2.7 | $0.06 | $0.60 | $2.40 |
| DeepSeek-V3.1 | N/A | $3.00 | $4.50 |
| DeepSeek-V3.2 | N/A | $3.00 | $4.50 |
| gemma-4-31B-it | N/A | $0.38 | $1.15 |
| gpt-oss-120b | N/A | $0.22 | $0.59 |
| Meta-Llama-3.3-70B-Instruct | N/A | $0.60 | $1.20 |
| MiniMax-M3 | N/A | $0.60 | $2.40 |

`[draft]` — headers said "Input (per 1M tokens)" / "Output (per 1M tokens)," page
titled "Pricing." This directly answers the first pass's "Rule 5 says cite the
vendor or don't cite... read them from your console" note for SambaNova: here is the
vendor citation.

One dating wrinkle worth flagging, not resolving: a SambaNova blog post,
https://sambanova.ai/blog/sambanova-cloud-developer-tier-is-live (published
2025-02-08 per its own byline), describes a different free-tier shape — "$5 of free
credit... expires in 3 months," "over 30 million free tokens on Llama 8B" — that
doesn't obviously reconcile with the first pass's 20 RPM/20 RPD/200K TPD figure from
`docs.sambanova.ai/docs/en/models/rate-limits` (dated 2026-09-03). Both are
first-party SambaNova pages; they may describe two different programs (a legacy
credit grant vs. the current rate-limited free tier), or the blog post may simply be
stale. Not resolved here — flag it for the account check.

**Cerebras — partial: the pricing table exists on the vendor page, but only behind
JS rendering.** `https://www.cerebras.ai/pricing` fetched with a plain HTTP GET shows
only the three-tier selector shell (Free Trial / Developer / Enterprise) and the
"Preview models are intended for evaluation purposes only" disclaimer — matching what
the first pass reported. The same URL through the JS-proxy renders an actual
"Developer Tier Pricing" table underneath that shell:

| model | speed | input /1M | output /1M | status |
|---|---|---|---|---|
| GPT OSS 120B | ~3000 tok/s | $0.35 | $0.75 | production |
| Qwen 3.8 27B | ~1,500 tok/s | $0.99 | $1.49 | preview |

Retrieved 2026-09-04. This explains *why* the first pass's direct fetch came up
empty — it's not that the vendor doesn't publish the numbers, it's that they only
render client-side. Still `[draft]`, and this one specifically needs a real-browser
re-check (open the page, confirm the table renders, screenshot or copy it) before
it's trustworthy — a proxy render inventing a plausible-looking table is exactly the
failure mode this file's provenance rule exists to catch, and this table cannot be
cross-checked against a second independent source the way the SambaNova one can.

**Groq — still closed, confirmed rather than opened.** `console.groq.com/docs/pricing`
404s (same as the first pass found) and `groq.com/pricing` carries no pricing content
at all, marketing copy only (same, both checked again this pass, including through
the JS-proxy — no hidden table here the way Cerebras had one). One first-party
artifact did turn up: a dated Groq blog post,
https://groq.com/blog/12-hours-later-groq-is-running-llama-3-instruct-8-70b-by-meta-ai-on-its-lpu-inference-enginge
(published 2024-04-20), states "Llama 3 70B at a price of $0.59 (input) and $0.79
(output) per 1M tokens." That is a genuine vendor citation with a date — but it is
17 months stale, names a model ("Llama 3 70B") that isn't the current
"Llama 3.3 70B" / `openai/gpt-oss-120b` lineup the rest of this file uses, and
pricing this old should not be trusted as current. Recorded here as evidence a
historical vendor price point exists, not as a usable list-price figure. Groq's
current per-token pricing remains `[YOU]` — unchanged from the first pass.

### 4. Nothing else new

No other public-source material turned up this pass that bears on the 16-column
worksheet beyond the three threads above. In particular: no new OpenRouter,
Cloudflare, Google, or GitHub Models findings — the first pass's coverage of those
stands as-is.
