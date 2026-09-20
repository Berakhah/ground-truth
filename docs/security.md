# Security posture

This document describes the controls actually implemented in this repository. It is not a
compliance claim or a vendor-honesty statement about any third party — see
[`docs/non-goals.md`](non-goals.md) and this project's rule against characterising anyone's
honesty (`CLAUDE.md`, Never #7). For how to report a vulnerability, see
[`SECURITY.md`](../SECURITY.md).

## Threat model, in one sentence

The two things that must never happen are (a) a private-split golden item, or any model output
graded against one, reaching a published artifact, and (b) the private generator seed or hash
salt (`GT_PRIVATE_SEED`, `GT_HASH_SALT`) landing in git history. Everything below exists to make
those two failures either impossible by construction or caught before merge.

## Private-split protection

- `golden/corpus/private/` is gitignored (`.gitignore`); only a `.gitkeep` placeholder is
  tracked. The private items themselves never enter git history.
- `tests/test_contamination.py` asserts no private-split content reaches a published artifact.
  In CI (`.github/workflows/publish.yml`, job `release`), this test is re-run with
  `GT_REQUIRE_DB=1`, which turns its normal "skip if no local DB" behaviour into a hard failure —
  a release cannot ship without the gate actually running.
- Published artifacts carry only content hashes of private items
  (`manifest_private.json`) and per-hash verdicts (`verdicts_private_by_hash.jsonl`), never the
  item text itself — see the README's "Reproduce these numbers" section.
- `scripts/reproduce.py` is the one script a stranger is invited to run against published
  output. Its header states — and this document restates — that it must never use `eval`,
  `pickle`, or `yaml.load`, because it parses attacker-supplied JSON from a downloaded
  `artifacts/` directory.

## Secret handling

- `GT_PRIVATE_SEED` and `GT_HASH_SALT` (and `GT_PUBLIC_SEED`, which is not secret — it is the
  published seed the public corpus was built from) are read from `.env`, which is gitignored.
  `.env.example` ships only placeholder values.
- `.pre-commit-config.yaml` runs `gitleaks` on every commit using the default ruleset, plus a
  project-specific ruleset (`.gitleaks.toml`) that adds rules matching the `GT_.*_SEED` and
  `GT_HASH_SALT` environment-variable-style patterns specifically — the default ruleset does not
  recognise this project's own env var names as secrets. `tests/test_gitleaks_rules.py::
  test_no_seed_value_in_any_tracked_file` gives this a regression test independent of the
  pre-commit hook actually running.
- No secrets are ever placed in test fixtures (`00` R-level rule); fixtures use synthetic,
  clearly-fake values.

## Supply chain

- `pip-audit` and `npm audit` run in CI (`.github/workflows/ci.yml`) against the Python and
  `web/` dependency sets respectively, non-blocking initially so a first vulnerable transitive
  dependency does not immediately red the build without a documented triage step — see that
  workflow file for the current blocking/non-blocking setting.
- Dependabot (`.github/dependabot.yml`) keeps `pip`, `npm`, and GitHub Actions dependencies
  proposed as PRs on a weekly cadence.
- A CycloneDX SBOM is generated for the Python dependency set as part of the release workflow
  and attached to the tag (`.github/workflows/publish.yml`), so a downstream consumer can audit
  exactly what shipped in a given release without re-resolving the lockfile themselves.
- Every GitHub Action used in `.github/workflows/*.yml`, and every `rev:` in
  `.pre-commit-config.yaml`, is pinned to an immutable commit SHA (not a mutable tag like `@v4`),
  with the human-readable tag kept alongside as a comment. See this task's implementation report
  for the two pins (if any) that could not be verified against a live registry at the time they
  were pinned.

## CI/CD permissions

Every workflow in `.github/workflows/` declares an explicit least-privilege `permissions:`
block — the GitHub default of broad read/write access is never relied upon implicitly.
`regression-watch.yml` runs on `schedule` only (never `pull_request_target`, which would let a
fork-submitted PR run with repository secrets) and does not reference any model-provider secret;
it only ever uses the ambient `GITHUB_TOKEN` to open issues.

## Web hardening

`web/` self-hosts its two OFL fonts (`web/public/fonts/`) rather than loading them from the
Google Fonts CDN, per `00` SS5.2's privacy/offline-demo rule. Because the published site is
static GitHub Pages, which cannot set response headers, the root layout
(`web/app/layout.tsx`) sets a restrictive Content-Security-Policy via a `<meta http-equiv>` tag
rather than a server header.

## Regression / smoke testing against live providers

Any test that talks to a real model provider is recorded once with `vcrpy` and replayed from
its cassette on every subsequent run, so CI never depends on live network access or spends
quota. A separate nightly smoke-test workflow makes a small number of live calls against the
current model behind each configured slot and opens a GitHub issue — without failing CI — if a
provider has silently changed behaviour or a model id has disappeared (`00` B4, `04` B6). See
`.github/workflows/` for the exact schedule.

## What this document does not claim

This is a research/benchmarking tool run by its own maintainers, not a multi-tenant service.
There is no authentication layer, no user data store, and no network-facing API beyond the
static published site — those categories of control (session management, authorization,
input-boundary hardening for a live service) do not apply here and this document does not
pretend otherwise.
