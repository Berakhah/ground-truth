from __future__ import annotations

from pathlib import Path

import duckdb

TABLES: tuple[str, ...] = (
    "rubric_versions",
    "analysis_plan",
    "items",
    "item_fields",
    "runs",
    "outputs",
    "judge_samples",
    "verdicts",
    "human_labels",
    "judge_decisions",
    "looks",
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS rubric_versions (
    rubric_version TEXT PRIMARY KEY, authored_at TIMESTAMP NOT NULL,
    content_hash TEXT NOT NULL, frozen_at TIMESTAMP NOT NULL);

CREATE TABLE IF NOT EXISTS analysis_plan (
    plan_version TEXT PRIMARY KEY, content_hash TEXT NOT NULL, frozen_at TIMESTAMP NOT NULL);

CREATE TABLE IF NOT EXISTS items (
    item_id TEXT PRIMARY KEY, split TEXT NOT NULL CHECK (split IN ('public','private')),
    rubric_version TEXT NOT NULL, source TEXT NOT NULL CHECK (source IN ('synthetic','partner')),
    content_hash TEXT NOT NULL, created_at TIMESTAMP NOT NULL);

CREATE TABLE IF NOT EXISTS item_fields (
    item_id TEXT NOT NULL, field_name TEXT NOT NULL, field_type TEXT NOT NULL,
    expected_value TEXT NOT NULL, expected_normalised TEXT, tolerance TEXT,
    PRIMARY KEY (item_id, field_name));

CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY, started_at TIMESTAMP NOT NULL, finished_at TIMESTAMP,
    model_slot TEXT NOT NULL, resolved_model_ref TEXT NOT NULL, provider TEXT NOT NULL,
    commercial_context BOOLEAN NOT NULL, sweep_id TEXT NOT NULL,
    code_version TEXT NOT NULL, models_yaml_hash TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS outputs (
    output_id TEXT PRIMARY KEY, run_id TEXT NOT NULL, item_id TEXT NOT NULL,
    replicate_idx INTEGER NOT NULL CHECK (replicate_idx >= 1), raw_output TEXT NOT NULL,
    ledger_call_id TEXT NOT NULL, provider_served TEXT NOT NULL, fingerprint TEXT,
    latency_ms INTEGER NOT NULL, prompt_hash TEXT NOT NULL, observed_at TIMESTAMP NOT NULL,
    UNIQUE (run_id, item_id, replicate_idx));

CREATE TABLE IF NOT EXISTS judge_samples (
    sample_id TEXT PRIMARY KEY, output_id TEXT NOT NULL, field_name TEXT NOT NULL,
    judge_slot TEXT NOT NULL, presentation_order INTEGER NOT NULL,
    raw_judgement TEXT NOT NULL, ledger_call_id TEXT NOT NULL, observed_at TIMESTAMP NOT NULL);

CREATE TABLE IF NOT EXISTS verdicts (
    verdict_id TEXT PRIMARY KEY, output_id TEXT NOT NULL, field_name TEXT NOT NULL,
    grader_id TEXT NOT NULL, grader_version TEXT NOT NULL, rubric_version TEXT NOT NULL,
    correct BOOLEAN NOT NULL, reason TEXT NOT NULL, computed_at TIMESTAMP NOT NULL,
    UNIQUE (output_id, field_name, grader_id, grader_version, rubric_version));

CREATE TABLE IF NOT EXISTS human_labels (
    label_id TEXT PRIMARY KEY, item_id TEXT NOT NULL, field_name TEXT NOT NULL,
    output_id TEXT, labeller_id TEXT NOT NULL, round INTEGER NOT NULL CHECK (round IN (1,2)),
    value TEXT NOT NULL, labelled_at TIMESTAMP NOT NULL);

CREATE TABLE IF NOT EXISTS judge_decisions (
    field_type TEXT PRIMARY KEY, rubric_version TEXT NOT NULL, alpha DOUBLE NOT NULL,
    alpha_low DOUBLE NOT NULL, alpha_high DOUBLE NOT NULL, n_units INTEGER NOT NULL,
    threshold DOUBLE NOT NULL, status TEXT NOT NULL CHECK (status IN ('accepted','rejected')),
    decided_at TIMESTAMPTZ NOT NULL);

CREATE TABLE IF NOT EXISTS looks (
    quarter TEXT NOT NULL, look INTEGER NOT NULL, total_looks INTEGER NOT NULL,
    run_at TIMESTAMP NOT NULL, PRIMARY KEY (quarter, look));
"""


def connect(path: Path) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def migrate(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_SCHEMA)
