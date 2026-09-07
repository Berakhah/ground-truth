# Corrections and right of reply

This project publishes measured, dated results about named models and providers. Anyone —
a provider, a user of the leaderboard, or a member of the public — who believes a published
result is wrong can dispute it through either channel below, and the outcome is published
either way: raising a dispute never quietly removes a number, it produces a public record of
what was checked and what changed, if anything.

## How to raise a dispute

Two channels, so a provider that prefers to raise something privately first is not forced
into a public issue immediately:

1. **Open a GitHub issue** using the [`right-of-reply`](../.github/ISSUE_TEMPLATE/right-of-reply.yml)
   issue template. This is the default channel and is public from the start.
2. **Email `corrections@example.invalid`** for providers who would rather raise the concern
   privately before anything is public. We still publish the outcome once we've looked at it
   — private intake does not mean a private resolution.

## Response windows

- **Acknowledge within 5 business days** of the dispute being raised.
- **Publish a resolution within 15 business days** of the dispute being raised.

These windows cover the initial handling of a dispute already raised. They are separate from
the advance-notice rule below, which covers what we do *before* certain findings are
published in the first place.

## Advance notice before publishing

- **Routine leaderboard scores get no advance notice.** A model's accuracy, cost, and latency
  figures are published on the normal schedule.
- **Any regression or drift finding that names a provider gets 10 business days' notice**
  before it is published. A regression or drift finding reads as a claim that something got
  worse — that is a different kind of statement than a routine score, and the named provider
  gets a window to review the finding, propose a configuration correction, or prepare a
  response before it goes out.

## Outcomes

Every dispute resolves to exactly one of three outcomes, and each is published with the
reasoning behind it — not just the verdict:

- **Correction** — the published number or claim was wrong and is corrected. Per the
  changelog's release rule, the superseded value stays visible, struck through, rather than
  being silently edited away.
- **Clarification** — the published number is accurate but the methodology, scope, or wording
  around it was unclear enough to cause the dispute; we publish clearer language rather than
  changing the number.
- **No change** — the published result stands as-is, with the reasoning for that conclusion
  published alongside the original dispute.

## Standing offer: re-run under the provider's configuration

If a provider identifies a specific configuration error in how a model was called — wrong
parameters, a wrong endpoint, a stale model reference, or similar — we re-run the affected
items under the provider's stated configuration and publish both results side by side, so
the effect of the configuration change is visible rather than asserted.
