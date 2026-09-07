# Ground Truth

An eval and regression harness for one regulated task: field extraction accuracy on pay
application and invoice documents. It does not benchmark general-purpose language ability
and is not a platform for arbitrary evals — see [`docs/non-goals.md`](docs/non-goals.md).

> Before you build anything, I will tell you which of your intents are safe to automate, which must route to a human, and what it costs — with a published methodology and a number you can reproduce.

Phase 1 has no external services: DuckDB is an embedded local `.duckdb` file (no server), and the provider gateway is shimmed — no real network calls yet.

## Reproduce these numbers

Download the published `artifacts/` directory (see [Published artifacts](#published-artifacts) below), then run:

```
python scripts/reproduce.py artifacts/
```

`reproduce.py` is a standalone, stdlib-only script — it does not import `ground_truth` and needs no repository checkout. It recomputes each leaderboard row's headline accuracy directly from `verdicts_private_by_hash.jsonl` and prints published vs. recomputed side by side. Expect zero differences and exit code 0.

The private split's actual items are never published — only their content hashes (`manifest_private.json`), which prove the items existed at a given date without revealing them, and per-item verdicts keyed by that hash (`verdicts_private_by_hash.jsonl`), which are enough for anyone to independently recompute the headline numbers without ever seeing a private item.

## Quickstart

```
cp .env.example .env      # then fill in GT_PRIVATE_SEED / GT_HASH_SALT, see below
docker compose up
```

That builds the image and runs the test suite with coverage (`pytest --cov=ground_truth --cov-fail-under=75`) — the smoke test that a fresh machine's setup actually works. No other manual steps.

`GT_PUBLIC_SEED` in `.env.example` is already the real published value the shipped public corpus was built from (see `docs/methodology.md`). `GT_PRIVATE_SEED` and `GT_HASH_SALT` are placeholders you must replace with your own high-entropy values (`python -c "import secrets; print(secrets.token_hex(16))"`) — they gate the private split and are never published.

## Running the harness

The two CLI entrypoints:

```
# Build the golden corpus (120 public + 180 private items) into
# golden/corpus/ and data/results.duckdb, from GT_PUBLIC_SEED /
# GT_PRIVATE_SEED / GT_HASH_SALT in .env.
docker compose run app uv run python -m ground_truth.golden.build

# Render the print-ready triage report (expected-value automate /
# route-to-human recommendations) from an intake CSV -- see
# docs/triage-intake-template.csv for the expected columns.
docker compose run app uv run python -m ground_truth.triage.report \
  --intake path/to/intake.csv \
  --out path/to/report.html \
  --methodology-url https://example.com/methodology
```

## Published artifacts

This is a published document with an interface, not a dashboard.

- [`docs/methodology.md`](docs/methodology.md) — how the golden set, splits, and statistics are built, and why.
- [`docs/rubric.md`](docs/rubric.md) — what counts as a correct extraction, per field type, frozen before labelling.
