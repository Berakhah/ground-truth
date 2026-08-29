# Ground Truth — Phase 1: Foundation and Triage (Weeks 21–22) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the harness spine — golden set, deterministic graders, phase-1 runner, cluster bootstrap, MDE — and land it in a sellable triage report by end of week 22.

**Architecture:** Two-phase. `runner.py` calls models and appends raw outputs to DuckDB, grading nothing. Graders are pure `(item, raw_output) -> Verdict` functions with no I/O. All analysis reads DuckDB. Degraded mode, reproducibility and cheap re-grading are consequences of this split, not features.

**Tech Stack:** Python 3.12+, `uv`, `ruff`, `mypy --strict`, `pytest`, `hypothesis`, `duckdb`, `scipy`, `pydantic` v2.

**Spec:** `docs/superpowers/specs/2025-09-18-ground-truth-design.md`

**Phase deliverable:** a triage report that can be sold. This phase stands alone (`00` B5).

## Global Constraints

Every task's requirements implicitly include this section.

- **Python 3.12+**, dependencies via `uv`, lint and format via `ruff`, `mypy --strict` on all of `ground_truth/`.
- **No model name is ever hardcoded** (`00` R1). Code asks for a lane slot; `models.yaml` resolves it. A literal model id anywhere in `ground_truth/` is a defect.
- **No secrets in the repo, including test fixtures** (`00` §3.4). `gitleaks` runs pre-commit.
- **No `[project.scripts]` entry.** Entrypoints are `python -m ground_truth.<module>`.
- **Money uses `Decimal` with an explicit context. Never `float`.** Enforced by a CI grep gate *and* a test.
- **No AIA form artifact anywhere in this repo.** Generator uses our own layout with equivalent column semantics. Non-affiliation notice ships with any published corpus.
- **`golden/corpus/private/` is gitignored.** Only `manifest_private.json` is committed. The private generator seed is never committed — it lives in `.env`.
- **Response cache is DISABLED for benchmark execution.** A cache hit would fabricate zero replicate variance.
- **Licence: Apache-2.0.** Coverage floor: 75%.
- **Every task's verification implicitly ends with the non-goal check:** *Did this task add an abstraction whose second implementation does not exist? A plugin hook, a task registry, a generic runner, a "bring your own X" seam? If yes, STOP and report — that is the platform trap arriving.*

---

### Task 1: Repository initialisation, tooling, and the private-corpus boundary

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.pre-commit-config.yaml`
- Create: `LICENSE` (Apache-2.0 full text)
- Create: `.github/workflows/ci.yml`
- Create: `ground_truth/__init__.py`
- Test: `tests/test_repo_hygiene.py`

**Interfaces:**
- Consumes: nothing.
- Produces: an importable `ground_truth` package; a green CI run; `golden/corpus/private/` proven untracked.

- [ ] **Step 1: Initialise the repository and make the spec the first commit**

```bash
git init
git add docs/superpowers/specs/2025-09-18-ground-truth-design.md
git commit -m "docs: ground truth design spec"
```

This ordering matters. Spec §5.2 relies on public git history as evidence; the history starts here.

- [ ] **Step 2: Write `.gitignore`**

```gitignore
__pycache__/
*.py[cod]
.venv/
.env
.ruff_cache/
.mypy_cache/
.pytest_cache/
htmlcov/
data/*.duckdb
golden/corpus/private/
!golden/corpus/private/.gitkeep
node_modules/
web/.next/
web/out/
```

- [ ] **Step 3: Write the failing hygiene test**

```python
# tests/test_repo_hygiene.py
import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def _tracked(pathspec: str) -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", pathspec], cwd=REPO, capture_output=True, text=True, check=True
    )
    return [line for line in out.stdout.splitlines() if line.strip()]


def test_private_corpus_not_tracked_by_git():
    tracked = [p for p in _tracked("golden/corpus/private/") if not p.endswith(".gitkeep")]
    assert tracked == [], f"private corpus files are tracked: {tracked}"


def test_env_file_not_tracked():
    assert _tracked(".env") == [], "the private generator seed must never be committed"


def test_no_project_scripts_entry():
    text = (REPO / "pyproject.toml").read_text(encoding="utf-8")
    assert "[project.scripts]" not in text, "entrypoints are python -m ground_truth.<module>"
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `pytest tests/test_repo_hygiene.py -v`
Expected: FAIL — `pyproject.toml` does not exist yet (`FileNotFoundError`).

- [ ] **Step 5: Write `pyproject.toml`**

```toml
[project]
name = "ground-truth"
version = "0.1.0"
requires-python = ">=3.12"
license = { text = "Apache-2.0" }
dependencies = [
    "duckdb>=1.1",
    "pydantic>=2.9",
    "scipy>=1.14",
    "numpy>=2.1",
    "pyyaml>=6.0",
    "jinja2>=3.1",
]

[dependency-groups]
dev = ["pytest>=8.3", "pytest-cov>=5.0", "hypothesis>=6.112", "mypy>=1.11", "ruff>=0.6"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM", "PL"]

[tool.mypy]
python_version = "3.12"
strict = true
files = ["ground_truth"]

[tool.pytest.ini_options]
addopts = "--cov=ground_truth --cov-report=term-missing --cov-fail-under=75"
testpaths = ["tests"]
markers = ["slow: coverage simulations; run in CI, skippable locally with -m 'not slow'"]
```

- [ ] **Step 6: Create the package and the private corpus placeholder**

```bash
mkdir -p ground_truth golden/corpus/public golden/corpus/private data
printf '"""Ground Truth: a vertical eval harness for pay-application field extraction."""\n' > ground_truth/__init__.py
touch golden/corpus/private/.gitkeep
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv sync && uv run pytest tests/test_repo_hygiene.py -v`
Expected: PASS, 3 passed.

- [ ] **Step 8: Write `.pre-commit-config.yaml`**

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.6.9
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.21.0
    hooks:
      - id: gitleaks
  - repo: https://github.com/pre-commit/mirrors-mypy
    rev: v1.11.2
    hooks:
      - id: mypy
        args: [--strict]
        additional_dependencies: [pydantic>=2.9]
```

- [ ] **Step 9: Write `.github/workflows/ci.yml`**

```yaml
name: ci
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }
      - uses: astral-sh/setup-uv@v3
      - run: uv sync --all-extras
      - run: uv run ruff check .
      - run: uv run ruff format --check .
      - run: uv run mypy
      - name: no float in the money path
        run: |
          if grep -rn "float(" ground_truth/graders/ ground_truth/triage/ 2>/dev/null; then
            echo "float() is forbidden in the money path"; exit 1
          fi
      - run: uv run pytest -v
```

`fetch-depth: 0` is required — `test_private_corpus_not_tracked_by_git` shells out to `git ls-files`.

- [ ] **Step 10: Add the Apache-2.0 licence text**

Download the canonical text to `LICENSE` and set the copyright line. Do not paraphrase it.

- [ ] **Step 11: Verify the full gate passes**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -v`
Expected: all four pass.

- [ ] **Step 12: Commit**

```bash
git add pyproject.toml .gitignore .pre-commit-config.yaml LICENSE .github/ ground_truth/ golden/ tests/
git commit -m "chore: initialise repo, tooling, CI, and the private-corpus boundary"
```

---

### Task 2: Provider audit — `docs/providers.md` and `models.yaml`

This is the week-21 blocking task. It is field work, not code, but its output is machine-checked.

**Files:**
- Create: `docs/providers.md`
- Create: `models.yaml`
- Create: `ground_truth/store/__init__.py`
- Create: `ground_truth/providers.py`
- Test: `tests/test_providers_manifest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `load_slots(path: Path, key: str = "slots") -> dict[str, SlotSpec]`; `SlotSpec` with fields `slot: str`, `family: str`, `provider: str`, `model_ref: str`, `trains_on_data: bool`, `commercial_use: bool`, `exposes_fingerprint: bool`, `list_price_in_per_1m: Decimal`, `list_price_out_per_1m: Decimal`, `pricing_url: str`, `retrieved_at: date`.

- [ ] **Step 1: Perform the audit**

For each of Google AI Studio, Groq, OpenRouter (`:free`), Mistral, Cloudflare Workers AI, SambaNova, Cerebras, GitHub Models, NVIDIA NIM — **from the machine that will run the sweeps, on the account that will run them** — record all eight columns from the spec's provider-audit table. Cohere is pre-flagged `commercial_use: false`; record it as such and do not configure it.

For the fingerprint column, make one real call and dump the entire response body. If nothing version-like is present, record `exposes_fingerprint: false`. Do not guess.

- [ ] **Step 2: Write `docs/providers.md`**

One table, columns: `provider | reachable | free_model_ids | rpm | tpm | rpd | trains_on_data | commercial_use | exposes_fingerprint | vision | list_price_in_per_1m | list_price_out_per_1m | pricing_url | terms_url | terms_quote | retrieved_at`.

`terms_quote` holds the **verbatim sentence** from the provider's terms covering training and commercial use. A paraphrase is not admissible evidence.

- [ ] **Step 3: Write the failing manifest test**

```python
# tests/test_providers_manifest.py
from datetime import date
from decimal import Decimal
from pathlib import Path

from ground_truth.providers import load_slots

REPO = Path(__file__).resolve().parents[1]
MODELS_YAML = REPO / "models.yaml"
PROVIDERS_MD = REPO / "docs" / "providers.md"


def test_every_slot_is_documented():
    slots = load_slots(MODELS_YAML)
    doc = PROVIDERS_MD.read_text(encoding="utf-8")
    for spec in slots.values():
        assert spec.provider in doc, f"{spec.provider} is in models.yaml but not docs/providers.md"


def test_every_slot_carries_list_price_and_provenance():
    for spec in load_slots(MODELS_YAML).values():
        assert spec.list_price_in_per_1m > Decimal("0")
        assert spec.list_price_out_per_1m > Decimal("0")
        assert spec.pricing_url.startswith("https://")
        assert isinstance(spec.retrieved_at, date)


def test_no_non_commercial_provider_is_configured():
    offenders = [s.slot for s in load_slots(MODELS_YAML).values() if not s.commercial_use]
    assert offenders == [], f"non-commercial providers cannot serve billable work: {offenders}"


def test_families_are_declared_not_inferred():
    for spec in load_slots(MODELS_YAML).values():
        assert spec.family, "judge same-family rejection depends on a declared family"


def test_slot_count_is_within_design_bounds():
    slots = load_slots(MODELS_YAML)
    assert 1 <= len(slots) <= 6, "design assumes at most six leaderboard slots"


def test_judge_slots_load_from_their_own_key():
    judges = load_slots(MODELS_YAML, key="judge_slots")
    assert judges, "at least one judge slot must be configured"
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/test_providers_manifest.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.providers'`.

- [ ] **Step 5: Write `models.yaml`**

Fill from the audit. Six slots if six survive; fewer is fine and the leaderboard states the count.

```yaml
slots:
  slot-a:
    family: FAMILY_FROM_AUDIT
    provider: PROVIDER_FROM_AUDIT
    model_ref: MODEL_ID_FROM_AUDIT   # read at runtime; never imported into Python source
    trains_on_data: false
    commercial_use: true
    exposes_fingerprint: false
    list_price_in_per_1m: "0.10"
    list_price_out_per_1m: "0.40"
    pricing_url: "https://example.invalid/pricing"
    retrieved_at: "2026-08-31"
judge_slots:
  judge-a:
    family: FAMILY_FROM_AUDIT
    provider: PROVIDER_FROM_AUDIT
    model_ref: MODEL_ID_FROM_AUDIT
    trains_on_data: false
    commercial_use: true
    exposes_fingerprint: false
    list_price_in_per_1m: "0.10"
    list_price_out_per_1m: "0.40"
    pricing_url: "https://example.invalid/pricing"
    retrieved_at: "2026-08-31"
```

`model_ref` lives in YAML, never in Python source. That is what `00` R1 means.

- [ ] **Step 6: Write `ground_truth/providers.py`**

```python
from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SlotSpec(BaseModel):
    slot: str
    family: str = Field(min_length=1)
    provider: str
    model_ref: str
    trains_on_data: bool
    commercial_use: bool
    exposes_fingerprint: bool
    list_price_in_per_1m: Decimal
    list_price_out_per_1m: Decimal
    pricing_url: str
    retrieved_at: date


def load_slots(path: Path, key: str = "slots") -> dict[str, SlotSpec]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {name: SlotSpec(slot=name, **body) for name, body in (raw.get(key) or {}).items()}
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `uv run pytest tests/test_providers_manifest.py -v`
Expected: PASS, 6 passed.

- [ ] **Step 8: Commit**

```bash
git add models.yaml docs/providers.md ground_truth/providers.py ground_truth/store/__init__.py tests/test_providers_manifest.py
git commit -m "feat: provider audit manifest with list prices and licence terms"
```

---

### Task 3: DuckDB schema — `store/db.py`

**Files:**
- Create: `ground_truth/store/db.py`
- Test: `tests/store/test_db.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `connect(path: Path) -> duckdb.DuckDBPyConnection`, `migrate(con) -> None`, module constant `TABLES: tuple[str, ...]`.

- [ ] **Step 1: Write the failing test**

```python
# tests/store/test_db.py
from pathlib import Path

import pytest

from ground_truth.store.db import TABLES, connect, migrate

EXPECTED = (
    "rubric_versions", "analysis_plan", "items", "item_fields",
    "runs", "outputs", "judge_samples", "verdicts", "human_labels",
)


@pytest.fixture()
def con(tmp_path: Path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_all_tables_exist(con):
    present = {
        r[0] for r in con.execute("SELECT table_name FROM information_schema.tables").fetchall()
    }
    assert set(EXPECTED) <= present


def test_tables_constant_matches_schema(con):
    assert set(TABLES) == set(EXPECTED)


def test_migrate_is_idempotent(con):
    migrate(con)
    migrate(con)
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 0


def test_outputs_rejects_duplicate_replicate(con):
    con.execute(
        "INSERT INTO runs VALUES ('r1', now(), NULL, 'slot-a', 'ref', 'prov', false, 's1', 'sha', 'h')"
    )
    row = ("o1", "r1", "i1", 1, "{}", "call1", "prov", None, 100, "ph", "2026-09-01")
    con.execute("INSERT INTO outputs VALUES (?,?,?,?,?,?,?,?,?,?,?)", row)
    with pytest.raises(Exception):
        con.execute(
            "INSERT INTO outputs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            ("o2", "r1", "i1", 1, "{}", "call2", "prov", None, 100, "ph", "2026-09-01"),
        )


def test_split_check_constraint_rejects_a_third_split(con):
    with pytest.raises(Exception):
        con.execute(
            "INSERT INTO items VALUES ('i1', 'holdout', 'v1', 'synthetic', 'h', now())"
        )
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/store/test_db.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.store.db'`.

- [ ] **Step 3: Write `ground_truth/store/db.py`**

```python
from __future__ import annotations

from pathlib import Path

import duckdb

TABLES: tuple[str, ...] = (
    "rubric_versions", "analysis_plan", "items", "item_fields",
    "runs", "outputs", "judge_samples", "verdicts", "human_labels",
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
"""


def connect(path: Path) -> duckdb.DuckDBPyConnection:
    path.parent.mkdir(parents=True, exist_ok=True)
    return duckdb.connect(str(path))


def migrate(con: duckdb.DuckDBPyConnection) -> None:
    con.execute(_SCHEMA)
```

`outputs` has no `UPDATE` or `DELETE` path anywhere in this codebase. `UNIQUE (run_id, item_id, replicate_idx)` is what makes an accidental re-write fail loudly rather than silently overwrite a measurement.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/store/test_db.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/store/db.py tests/store/
git commit -m "feat: duckdb schema with append-only outputs"
```

---

### Task 4: The closed item schema — `golden/schema.py`

**Files:**
- Create: `ground_truth/golden/__init__.py`
- Create: `ground_truth/golden/schema.py`
- Test: `tests/golden/test_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `FieldType` (`StrEnum`, exactly eight members: `MONEY`, `PERCENT`, `DATE`, `IDENTIFIER`, `PARTY_NAME`, `ENUM_CATEGORY`, `COUNT`, `LINE_ITEM_DESCRIPTION`); `Split` (`PUBLIC`, `PRIVATE`); `Source` (`SYNTHETIC`, `PARTNER`); `ItemField(field_name: str, field_type: FieldType, expected_value: str, expected_normalised: str | None, tolerance: Decimal | None)`; `Item(item_id: str, split: Split, rubric_version: str, source: Source, content_hash: str, fields: list[ItemField], injected_error: str | None)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/golden/test_schema.py
from decimal import Decimal

import pytest

from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split

EXPECTED_FIELD_TYPES = {
    "MONEY", "PERCENT", "DATE", "IDENTIFIER",
    "PARTY_NAME", "ENUM_CATEGORY", "COUNT", "LINE_ITEM_DESCRIPTION",
}


def test_field_type_is_closed():
    assert {m.name for m in FieldType} == EXPECTED_FIELD_TYPES, (
        "The item schema is closed. Adding a field type is a scope decision, not a code change."
    )


def test_item_rejects_unknown_split():
    with pytest.raises(Exception):
        Item(item_id="i1", split="holdout", rubric_version="v1",
             source=Source.SYNTHETIC, content_hash="h", fields=[])


def test_money_field_carries_decimal_tolerance():
    f = ItemField(field_name="contract_sum", field_type=FieldType.MONEY,
                  expected_value="1000.00", expected_normalised=None, tolerance=Decimal("0.01"))
    assert isinstance(f.tolerance, Decimal)


def test_tolerance_is_never_float():
    with pytest.raises(Exception):
        ItemField(field_name="x", field_type=FieldType.MONEY, expected_value="1",
                  expected_normalised=None, tolerance=0.01)


def test_injected_error_defaults_to_none():
    item = Item(item_id="i1", split=Split.PUBLIC, rubric_version="v1",
                source=Source.SYNTHETIC, content_hash="h", fields=[])
    assert item.injected_error is None


def test_items_are_frozen():
    item = Item(item_id="i1", split=Split.PUBLIC, rubric_version="v1",
                source=Source.SYNTHETIC, content_hash="h", fields=[])
    with pytest.raises(Exception):
        item.item_id = "i2"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/golden/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.golden.schema'`.

- [ ] **Step 3: Write `ground_truth/golden/schema.py`**

```python
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, StrictStr


class FieldType(StrEnum):
    MONEY = "money"
    PERCENT = "percent"
    DATE = "date"
    IDENTIFIER = "identifier"
    PARTY_NAME = "party_name"
    ENUM_CATEGORY = "enum_category"
    COUNT = "count"
    LINE_ITEM_DESCRIPTION = "line_item_description"


class Split(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class Source(StrEnum):
    SYNTHETIC = "synthetic"
    PARTNER = "partner"


class ItemField(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    field_name: StrictStr
    field_type: FieldType
    expected_value: StrictStr
    expected_normalised: StrictStr | None = None
    tolerance: Decimal | None = None


class Item(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    item_id: StrictStr
    split: Split
    rubric_version: StrictStr
    source: Source
    content_hash: StrictStr
    fields: list[ItemField]
    injected_error: StrictStr | None = None
```

`strict=True` is what makes `test_tolerance_is_never_float` pass — a `float` is rejected rather than coerced. This is the money-path guard at the schema boundary.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/golden/test_schema.py -v`
Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/golden/ tests/golden/
git commit -m "feat: closed eight-member item schema with strict Decimal money fields"
```

---

### Task 5: The non-goal guard tests

Put the guard in place before there is anything to guard.

**Files:**
- Create: `tests/test_non_goals.py`
- Create: `docs/non-goals.md`

**Interfaces:**
- Consumes: `ground_truth.golden.schema.FieldType`.
- Produces: no importable symbol. Produces a CI gate.

- [ ] **Step 1: Write `docs/non-goals.md`**

State the six non-goals from spec §2.1 verbatim — no plugin system, no generic task abstraction, no multi-tenant SaaS, no "bring your own eval", no observability product, no prompt management — and record that they are enforced by `tests/test_non_goals.py`, not by review discipline alone.

- [ ] **Step 2: Write the guard test**

```python
# tests/test_non_goals.py
import ast
from pathlib import Path

import pytest

from ground_truth.golden.schema import FieldType

SRC = Path(__file__).resolve().parents[1] / "ground_truth"
BANNED_NAMES = {"entry_points", "register", "load_plugin", "discover_tasks"}
BANNED_MODULES = {"importlib.metadata", "pkg_resources", "stevedore"}
GRADER_BANNED_IMPORTS = {"httpx", "requests", "urllib", "socket"}

TRAP = "A task registry is the platform trap arriving — stop and escalate."


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_item_schema_is_closed():
    assert len(list(FieldType)) == 8, (
        "The item schema is closed. Adding a field type is a scope decision, not a code change."
    )


def test_no_task_registry():
    offenders: list[str] = []
    for path in _py_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id in BANNED_NAMES:
                    offenders.append(f"{path}: call to {node.func.id}()")
            if isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES:
                offenders.append(f"{path}: attribute .{node.attr}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", None) or ""
                names = [a.name for a in node.names]
                if mod in BANNED_MODULES or any(n in BANNED_MODULES for n in names):
                    offenders.append(f"{path}: imports {mod or names}")
    assert offenders == [], TRAP + "\n" + "\n".join(offenders)


def test_no_module_scope_callable_registry():
    offenders: list[str] = []
    for path in _py_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.Assign):
                continue
            if isinstance(node.value, ast.Dict) and node.value.keys:
                if all(
                    isinstance(v, (ast.Name, ast.Attribute, ast.Lambda))
                    for v in node.value.values
                ):
                    target = getattr(node.targets[0], "id", "<expr>")
                    offenders.append(f"{path}: module-scope dict[str, Callable] named {target}")
    assert offenders == [], TRAP + "\n" + "\n".join(offenders)


def test_graders_are_pure():
    graders = SRC / "graders" / "deterministic"
    if not graders.exists():
        pytest.skip("deterministic graders not yet implemented")
    offenders: list[str] = []
    for path in _py_files(graders):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", None) or ""
                names = [a.name for a in node.names]
                if mod.split(".")[0] in GRADER_BANNED_IMPORTS or any(
                    n.split(".")[0] in GRADER_BANNED_IMPORTS for n in names
                ):
                    offenders.append(f"{path}: imports {mod or names}")
                if mod.startswith("ground_truth._bok_shim") or mod.startswith("ground_truth.runner"):
                    offenders.append(f"{path}: imports phase-1 module {mod}")
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if node.func.id == "open":
                    offenders.append(f"{path}: calls open()")
    assert offenders == [], (
        "Graders are phase-2 pure functions. I/O here breaks degraded mode and reproducibility.\n"
        + "\n".join(offenders)
    )


PHASE_2_MODULES = (
    "graders", "stats", "matrix", "calibrate", "regression", "triage", "publish", "grade.py",
)


def test_phase2_imports_no_gateway():
    """Ground Truth's declared degraded-mode floor: phase 2 makes ZERO gateway calls.

    INTERFACE-CONTRACT.md section 5 withdraws 00's shared >=70% assertion and requires each
    repo to declare its own floor in its own unit. Ours is zero, and it is an AST fact
    rather than a runtime measurement -- which makes it the strongest of the four.
    """
    offenders: list[str] = []
    for name in PHASE_2_MODULES:
        target = SRC / name
        paths = _py_files(target) if target.is_dir() else ([target] if target.exists() else [])
        for path in paths:
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, (ast.Import, ast.ImportFrom)):
                    mod = getattr(node, "module", None) or ""
                    names = [a.name for a in node.names]
                    for candidate in [mod, *names]:
                        if "gateway" in candidate or candidate.endswith("_bok_shim"):
                            offenders.append(f"{path}: imports {candidate}")
    assert offenders == [], (
        "Phase 2 must make zero gateway calls. This is the published degraded-mode floor "
        "and the reason the reproducibility test can run without a provider.\n"
        + "\n".join(offenders)
    )
```

- [ ] **Step 3: Run the test to observe the current state**

Run: `uv run pytest tests/test_non_goals.py -v`
Expected: PASS — 4 passed, 1 skipped. `test_graders_are_pure` skips until Task 10 creates the directory; `test_phase2_imports_no_gateway` passes vacuously until those modules exist, then becomes load-bearing.

- [ ] **Step 4: Prove the guard actually catches something**

Temporarily add `PLUGINS = {"a": len}` at module scope in `ground_truth/providers.py`. Run `uv run pytest tests/test_non_goals.py::test_no_module_scope_callable_registry -v` and confirm it FAILS with the trap message. Then revert the edit and confirm it passes again. A guard you have never watched fail is not a guard.

- [ ] **Step 5: Commit**

```bash
git add tests/test_non_goals.py docs/non-goals.md
git commit -m "test: executable non-goal guards against the eval-platform trap"
```

---

### Task 6: The rubric, authored and frozen before any labelling

**Files:**
- Create: `docs/rubric.md`
- Create: `ground_truth/golden/rubric.py`
- Test: `tests/golden/test_rubric.py`

**Interfaces:**
- Consumes: `store.db.{connect, migrate}`, `golden.schema.FieldType`.
- Produces: `RubricRule(grader: str, tolerance: Decimal | None, normalisation: list[str], acceptable_variants: list[str], adjudication: str)`; `loaded_rubric(path: Path) -> dict[FieldType, RubricRule]`; `freeze_rubric(con, path: Path, version: str) -> str` returning the content hash.

- [ ] **Step 1: Author `docs/rubric.md` — before writing any code in this task**

One `## FIELDTYPE` section per member of `FieldType`, each with `- grader:`, `- tolerance:`, `- normalisation:` (semicolon-separated), `- acceptable_variants:` (semicolon-separated `canonical=variant` pairs), and `- adjudication:` bullets. Starting values, to be refined by domain judgement and never by what makes scores look better:

| FieldType | grader | tolerance | notes |
|---|---|---|---|
| `MONEY` | `numeric_tolerance` | `0.01` | Decimal only; parenthesised negatives normalise to `-` |
| `PERCENT` | `numeric_tolerance` | `0.001` | `12.5%` and `0.125` both normalise to `0.125` |
| `DATE` | `normalised` | — | ISO-8601 output; purely numeric `DD/MM` vs `MM/DD` is ambiguous and scores incorrect |
| `IDENTIFIER` | `normalised` | — | `strip_punctuation; strip_leading_zeros; casefold` |
| `PARTY_NAME` | `normalised` | — | `casefold; strip_accents; strip_legal_suffix` |
| `ENUM_CATEGORY` | `exact` | — | closed value list per field, stated |
| `COUNT` | `exact` | — | integer string |
| `LINE_ITEM_DESCRIPTION` | `judge` | — | judge only; barred from headline scoring below α=0.667 |

Set `rubric_version: v1` in the front matter.

- [ ] **Step 2: Timestamp the rubric's content, then commit it alone**

```bash
uv tool install opentimestamps-client
ots stamp docs/rubric.md          # writes docs/rubric.md.ots
git add docs/rubric.md docs/rubric.md.ots
git commit -m "docs: rubric v1, authored and timestamped before labelling"
```

**Why the `.ots` file and not just the commit.** A git timestamp is author-controlled — `GIT_COMMITTER_DATE` is settable and history is rewritable — so a sceptic cannot distinguish a genuine history from a fabricated one. For a project whose known weakness is single-annotator ground truth (`04` B1), *"trust me, the timestamps are real"* is the move this programme exists to reject. OpenTimestamps commits the file's **hash** to the Bitcoin blockchain: it proves the content existed at that date, which is what §5.2's claim actually needs. It is free, needs no account, and is one command.

This commit must precede every label commit. Do not batch it with anything else.

- [ ] **Step 2b (deferred a few hours — do not block on it): upgrade and verify the timestamp**

The attestation takes a few hours to reach a Bitcoin block. Continue with Step 3 now; come back and run:

```bash
ots upgrade docs/rubric.md.ots
ots verify docs/rubric.md.ots     # prints the block time the content is proven to predate
git add docs/rubric.md.ots && git commit -m "docs: upgrade rubric timestamp to a confirmed attestation"
```

Record the verified block time in `docs/methodology.md`. **Do not skip the upgrade** — an un-upgraded `.ots` proves only that a calendar server saw the hash, which is weaker than the claim you will publish. Set a reminder; this is the one step in the phase that cannot be done in a single sitting.

- [ ] **Step 3: Write the failing test**

```python
# tests/golden/test_rubric.py
from pathlib import Path

import pytest

from ground_truth.golden.rubric import freeze_rubric, loaded_rubric
from ground_truth.golden.schema import FieldType
from ground_truth.store.db import connect, migrate

REPO = Path(__file__).resolve().parents[2]
RUBRIC = REPO / "docs" / "rubric.md"


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def test_rubric_covers_every_field_type():
    rules = loaded_rubric(RUBRIC)
    assert set(rules) == set(FieldType), "every field type needs a written rule before labelling"


def test_money_rule_declares_a_decimal_tolerance():
    rule = loaded_rubric(RUBRIC)[FieldType.MONEY]
    assert rule.tolerance is not None and rule.grader == "numeric_tolerance"


def test_freeze_records_hash_and_timestamp(con):
    digest = freeze_rubric(con, RUBRIC, "v1")
    row = con.execute(
        "SELECT content_hash, frozen_at FROM rubric_versions WHERE rubric_version='v1'"
    ).fetchone()
    assert row[0] == digest and row[1] is not None


def test_freeze_is_idempotent_for_unchanged_content(con):
    assert freeze_rubric(con, RUBRIC, "v1") == freeze_rubric(con, RUBRIC, "v1")


def test_freeze_is_refused_when_content_changed(con, tmp_path):
    freeze_rubric(con, RUBRIC, "v1")
    altered = tmp_path / "rubric.md"
    altered.write_text(RUBRIC.read_text(encoding="utf-8") + "\nchanged\n", encoding="utf-8")
    with pytest.raises(ValueError, match="already frozen"):
        freeze_rubric(con, altered, "v1")
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/golden/test_rubric.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.golden.rubric'`.

- [ ] **Step 5: Write `ground_truth/golden/rubric.py`**

```python
from __future__ import annotations

import hashlib
import re
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import duckdb
from pydantic import BaseModel

from ground_truth.golden.schema import FieldType

_SECTION = re.compile(r"^##\s+(?P<name>[A-Z_]+)\s*$", re.MULTILINE)
_KEY = re.compile(
    r"^-\s+(?P<key>grader|tolerance|normalisation|acceptable_variants|adjudication):\s*(?P<val>.*)$",
    re.MULTILINE,
)


class RubricRule(BaseModel):
    grader: str
    tolerance: Decimal | None = None
    normalisation: list[str] = []
    acceptable_variants: list[str] = []
    adjudication: str = ""


def loaded_rubric(path: Path) -> dict[FieldType, RubricRule]:
    text = path.read_text(encoding="utf-8")
    sections = list(_SECTION.finditer(text))
    rules: dict[FieldType, RubricRule] = {}
    for i, match in enumerate(sections):
        end = sections[i + 1].start() if i + 1 < len(sections) else len(text)
        body = text[match.end() : end]
        kv = {m.group("key"): m.group("val").strip() for m in _KEY.finditer(body)}
        name = match.group("name")
        if name not in FieldType.__members__:
            continue
        raw_tol = kv.get("tolerance", "")
        rules[FieldType[name]] = RubricRule(
            grader=kv.get("grader", ""),
            tolerance=Decimal(raw_tol) if raw_tol and raw_tol != "-" else None,
            normalisation=[s.strip() for s in kv.get("normalisation", "").split(";") if s.strip()],
            acceptable_variants=[
                s.strip() for s in kv.get("acceptable_variants", "").split(";") if s.strip()
            ],
            adjudication=kv.get("adjudication", ""),
        )
    return rules


def freeze_rubric(con: duckdb.DuckDBPyConnection, path: Path, version: str) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    existing = con.execute(
        "SELECT content_hash FROM rubric_versions WHERE rubric_version = ?", [version]
    ).fetchone()
    if existing is not None:
        if existing[0] != digest:
            raise ValueError(f"rubric {version} is already frozen with a different hash")
        return digest
    now = datetime.now(UTC)
    con.execute("INSERT INTO rubric_versions VALUES (?, ?, ?, ?)", [version, now, digest, now])
    return digest
```

If `docs/rubric.md` does not already use `## MONEY` headings and `- grader: ...` bullets, reshape it now so the parser reads it.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/golden/test_rubric.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 7: Commit**

```bash
git add ground_truth/golden/rubric.py tests/golden/test_rubric.py
git commit -m "feat: rubric parsing and immutable freeze"
```

---

### Task 7: The pre-registered analysis plan

**Files:**
- Create: `docs/analysis-plan.md`
- Create: `ground_truth/analysis_plan.py`
- Test: `tests/test_analysis_plan.py`

**Interfaces:**
- Consumes: `store.db`.
- Produces: `freeze_plan(con, path: Path, version: str) -> str`; `assert_frozen_before_first_sweep(con) -> None` raising `AssertionError`.

- [ ] **Step 1: Author `docs/analysis-plan.md`**

It must state, before any number exists: the primary metric (per-field accuracy on the private split); the unit of analysis (**item**, with replicates clustered); the interval method (cluster BCa bootstrap, 10,000 resamples, 95%); the multiplicity procedure (Benjamini–Hochberg across model × field-type, FDR 0.05); the MDE multiplicity treatment (Bonferroni α/m, conservative and stated); **the judge rejection threshold, Krippendorff's α ≥ 0.667**; the sequential look calendar (13 weekly looks per quarter, O'Brien–Fleming spending, re-registered quarterly); and the rule that an unscheduled look costs alpha and must be declared in the changelog.

- [ ] **Step 2: Commit the plan alone, before any sweep**

```bash
git add docs/analysis-plan.md
git commit -m "docs: pre-registered analysis plan v1"
```

- [ ] **Step 3: Write the failing test**

```python
# tests/test_analysis_plan.py
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from ground_truth.analysis_plan import assert_frozen_before_first_sweep, freeze_plan
from ground_truth.store.db import connect, migrate

PLAN = Path(__file__).resolve().parents[1] / "docs" / "analysis-plan.md"


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def _insert_run(con, started_at):
    con.execute(
        "INSERT INTO runs VALUES (?,?,NULL,'slot-a','ref','prov',false,'s1','sha','h')",
        [f"r{started_at.timestamp()}", started_at],
    )


def test_plan_states_the_judge_threshold():
    assert "0.667" in PLAN.read_text(encoding="utf-8"), "the rejection threshold must be pre-registered"


def test_plan_names_the_sampling_unit():
    assert "item" in PLAN.read_text(encoding="utf-8").lower()


def test_no_runs_yet_is_not_a_violation(con):
    freeze_plan(con, PLAN, "v1")
    assert_frozen_before_first_sweep(con)


def test_passes_when_plan_frozen_first(con):
    freeze_plan(con, PLAN, "v1")
    _insert_run(con, datetime.now(UTC) + timedelta(hours=1))
    assert_frozen_before_first_sweep(con)


def test_fails_when_a_sweep_predates_the_plan(con):
    _insert_run(con, datetime.now(UTC) - timedelta(days=1))
    freeze_plan(con, PLAN, "v1")
    with pytest.raises(AssertionError, match="pre-registration"):
        assert_frozen_before_first_sweep(con)
```

- [ ] **Step 4: Run the test to verify it fails**

Run: `uv run pytest tests/test_analysis_plan.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.analysis_plan'`.

- [ ] **Step 5: Write `ground_truth/analysis_plan.py`**

```python
from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import duckdb


def freeze_plan(con: duckdb.DuckDBPyConnection, path: Path, version: str) -> str:
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    row = con.execute(
        "SELECT content_hash FROM analysis_plan WHERE plan_version = ?", [version]
    ).fetchone()
    if row is not None:
        if row[0] != digest:
            raise ValueError(f"analysis plan {version} is already frozen with a different hash")
        return digest
    con.execute("INSERT INTO analysis_plan VALUES (?, ?, ?)", [version, digest, datetime.now(UTC)])
    return digest


def assert_frozen_before_first_sweep(con: duckdb.DuckDBPyConnection) -> None:
    frozen = con.execute("SELECT min(frozen_at) FROM analysis_plan").fetchone()[0]
    first_run = con.execute("SELECT min(started_at) FROM runs").fetchone()[0]
    if first_run is None:
        return
    assert frozen is not None, "pre-registration missing: no analysis plan is frozen"
    assert frozen < first_run, (
        f"pre-registration violated: plan frozen {frozen} but a sweep started {first_run}"
    )
```

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/test_analysis_plan.py -v`
Expected: PASS, 5 passed.

- [ ] **Step 7: Commit**

```bash
git add ground_truth/analysis_plan.py tests/test_analysis_plan.py
git commit -m "feat: enforced pre-registration of the analysis plan"
```

---

### Task 8: Synthetic corpus generator

**Files:**
- Create: `ground_truth/golden/generate.py`
- Test: `tests/golden/test_generate.py`

**Interfaces:**
- Consumes: `golden.schema.{Item, ItemField, FieldType, Source, Split}`.
- Produces: `ErrorClass` (`StrEnum`: `TRANSPOSED_DIGITS`, `OFF_BY_ONE_CENT`, `MISSING_FIELD`, `RETAINAGE_MISMATCH`, `STORED_MATERIALS_DOUBLE_COUNT`, `DATE_LOCALE_AMBIGUOUS`); `generate(count: int, seed: int, rubric_version: str) -> list[Item]`; `render_document(item: Item) -> str`.

- [ ] **Step 1: Decide the source, and record the decision**

Check whether `../ledger-sense/` exists with a working synthetic pay-application generator. If it does, wrap it and record that in `docs/methodology.md`. If it does not, implement locally per the steps below. **Either way, no AIA form artifact enters this repo** — our own layout, equivalent column semantics only.

- [ ] **Step 2: Write the failing test**

```python
# tests/golden/test_generate.py
from decimal import Decimal

from ground_truth.golden.generate import ErrorClass, generate, render_document
from ground_truth.golden.schema import FieldType


def test_generation_is_deterministic_for_a_seed():
    a = generate(count=10, seed=7, rubric_version="v1")
    b = generate(count=10, seed=7, rubric_version="v1")
    assert [i.item_id for i in a] == [i.item_id for i in b]


def test_different_seeds_give_different_items():
    a = generate(count=10, seed=7, rubric_version="v1")
    b = generate(count=10, seed=8, rubric_version="v1")
    assert {i.item_id for i in a} != {i.item_id for i in b}


def test_every_field_type_appears_in_the_corpus():
    items = generate(count=60, seed=1, rubric_version="v1")
    seen = {f.field_type for item in items for f in item.fields}
    assert seen == set(FieldType)


def test_labels_are_present_in_the_rendered_document():
    item = generate(count=1, seed=3, rubric_version="v1")[0]
    doc = render_document(item)
    for field in item.fields:
        if field.field_type is not FieldType.LINE_ITEM_DESCRIPTION:
            assert field.expected_value in doc, f"{field.field_name} label absent from document"


def test_error_classes_are_injected_and_labelled():
    items = generate(count=60, seed=11, rubric_version="v1")
    injected = {i.injected_error for i in items if i.injected_error is not None}
    assert injected == {e.value for e in ErrorClass}, "every error class must be exercised"


def test_money_labels_are_clean_decimal_strings():
    for item in generate(count=20, seed=5, rubric_version="v1"):
        for f in item.fields:
            if f.field_type is FieldType.MONEY:
                Decimal(f.expected_value)  # raises if not a clean decimal string


def test_no_aia_form_strings_anywhere():
    banned = ("G702", "G703", "American Institute of Architects", "AIA Document")
    for item in generate(count=20, seed=2, rubric_version="v1"):
        doc = render_document(item)
        assert not any(b in doc for b in banned), "no AIA form artifact may appear in the corpus"


def test_non_affiliation_notice_is_present():
    doc = render_document(generate(count=1, seed=1, rubric_version="v1")[0])
    assert "not affiliated" in doc.lower()
```

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/golden/test_generate.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.golden.generate'`.

- [ ] **Step 4: Write `ground_truth/golden/generate.py`**

```python
from __future__ import annotations

import hashlib
import random
from decimal import Decimal
from enum import StrEnum

from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split

NON_AFFILIATION = (
    "This document is not developed, endorsed, approved, sponsored by or affiliated with "
    "the AIA. References describe column semantics only."
)
_LEGAL_SUFFIXES = ("Inc.", "LLC", "Ltd.", "Pty Ltd", "GmbH")
_TRADES = ("Sitework", "Concrete", "Masonry", "Structural Steel", "Roofing", "Glazing")


class ErrorClass(StrEnum):
    TRANSPOSED_DIGITS = "transposed_digits"
    OFF_BY_ONE_CENT = "off_by_one_cent"
    MISSING_FIELD = "missing_field"
    RETAINAGE_MISMATCH = "retainage_mismatch"
    STORED_MATERIALS_DOUBLE_COUNT = "stored_materials_double_count"
    DATE_LOCALE_AMBIGUOUS = "date_locale_ambiguous"


def _money(rng: random.Random, low: int, high: int) -> Decimal:
    return (Decimal(rng.randint(low * 100, high * 100)) / Decimal(100)).quantize(Decimal("0.01"))


def _build_fields(rng: random.Random, injected: ErrorClass | None) -> list[ItemField]:
    line_1 = _money(rng, 10_000, 90_000)
    line_2 = _money(rng, 5_000, 60_000)
    work_completed = line_1 + line_2
    retainage_rate = Decimal("0.10")
    retainage = (work_completed * retainage_rate).quantize(Decimal("0.01"))
    stored = _money(rng, 0, 5_000)
    if injected is ErrorClass.RETAINAGE_MISMATCH:
        retainage += Decimal("500.00")
    if injected is ErrorClass.STORED_MATERIALS_DOUBLE_COUNT:
        work_completed += stored
    earned_less_retainage = work_completed + stored - retainage
    contract_sum = work_completed + stored + _money(rng, 10_000, 50_000)
    balance = contract_sum - earned_less_retainage
    date_value = "2026-09-01" if injected is not ErrorClass.DATE_LOCALE_AMBIGUOUS else "01/09/2026"

    def f(name: str, ftype: FieldType, value: str, tol: Decimal | None = None) -> ItemField:
        return ItemField(field_name=name, field_type=ftype, expected_value=value, tolerance=tol)

    cents = Decimal("0.01")
    return [
        f("line_1", FieldType.MONEY, str(line_1), cents),
        f("line_2", FieldType.MONEY, str(line_2), cents),
        f("work_completed", FieldType.MONEY, str(work_completed), cents),
        f("stored_materials", FieldType.MONEY, str(stored), cents),
        f("retainage", FieldType.MONEY, str(retainage), cents),
        f("total_earned_less_retainage", FieldType.MONEY, str(earned_less_retainage), cents),
        f("contract_sum", FieldType.MONEY, str(contract_sum), cents),
        f("balance_to_finish", FieldType.MONEY, str(balance), cents),
        f("retainage_rate", FieldType.PERCENT, str(retainage_rate), Decimal("0.001")),
        f("period_to", FieldType.DATE, date_value),
        f("application_no", FieldType.IDENTIFIER, f"APP-{rng.randint(1, 999):06d}"),
        f("contractor", FieldType.PARTY_NAME, f"{rng.choice(_TRADES)} Partners {rng.choice(_LEGAL_SUFFIXES)}"),
        f("status", FieldType.ENUM_CATEGORY, rng.choice(("approved", "pending", "rejected"))),
        f("line_count", FieldType.COUNT, "2"),
        f("line_1_description", FieldType.LINE_ITEM_DESCRIPTION, f"{rng.choice(_TRADES)} works, phase 1"),
    ]


def generate(count: int, seed: int, rubric_version: str) -> list[Item]:
    rng = random.Random(seed)
    errors = list(ErrorClass)
    items: list[Item] = []
    for n in range(count):
        injected = errors[(n // 2) % len(errors)] if n % 2 == 0 else None
        fields = _build_fields(rng, injected)
        payload = "|".join(f"{f.field_name}={f.expected_value}" for f in fields)
        content_hash = hashlib.sha256(f"{seed}:{n}:{payload}".encode()).hexdigest()
        items.append(
            Item(
                item_id=content_hash[:16],
                split=Split.PUBLIC,  # splits.py reassigns; see Task 9
                rubric_version=rubric_version,
                source=Source.SYNTHETIC,
                content_hash=content_hash,
                fields=fields,
                injected_error=injected.value if injected else None,
            )
        )
    return items


def render_document(item: Item) -> str:
    lines = ["PROGRESS BILLING SUMMARY", "=" * 40]
    lines += [f"{f.field_name:<32}{f.expected_value}" for f in item.fields]
    lines += ["=" * 40, NON_AFFILIATION]
    return "\n".join(lines)
```

The generator's own layout, its own column names. `count` must be at least `2 * len(ErrorClass)` for `test_error_classes_are_injected_and_labelled` to hold — the test uses 60.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/golden/test_generate.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/golden/generate.py tests/golden/test_generate.py
git commit -m "feat: seeded synthetic corpus generator with labelled injected error classes"
```

---

### Task 9: Splits, manifests, and the contamination boundary

**Files:**
- Create: `ground_truth/golden/splits.py`
- Create: `ground_truth/golden/manifest.py`
- Create: `ground_truth/golden/build.py`
- Create: `.env.example`
- Test: `tests/golden/test_splits.py`

**Interfaces:**
- Consumes: `golden.generate.generate`, `golden.schema.{Item, Split}`, `store.db`.
- Produces: `assign_splits(items: list[Item], public_n: int, seed: int) -> list[Item]`; `write_manifest(items: list[Item], split: Split, path: Path) -> None`; `verify_manifest(items: list[Item], path: Path) -> None`; `python -m ground_truth.golden.build`.

- [ ] **Step 1: Write the failing test**

```python
# tests/golden/test_splits.py
import json

import pytest

from ground_truth.golden.generate import generate
from ground_truth.golden.manifest import verify_manifest, write_manifest
from ground_truth.golden.schema import Split
from ground_truth.golden.splits import assign_splits


def _items():
    return assign_splits(generate(count=300, seed=42, rubric_version="v1"), public_n=120, seed=42)


def test_split_sizes_are_120_180():
    items = _items()
    assert sum(i.split is Split.PUBLIC for i in items) == 120
    assert sum(i.split is Split.PRIVATE for i in items) == 180


def test_split_assignment_is_deterministic():
    assert {i.item_id: i.split for i in _items()} == {i.item_id: i.split for i in _items()}


def test_public_n_larger_than_corpus_raises():
    with pytest.raises(ValueError):
        assign_splits(generate(count=10, seed=1, rubric_version="v1"), public_n=20, seed=1)


def test_private_manifest_contains_hashes_only(tmp_path):
    items = _items()
    path = tmp_path / "manifest_private.json"
    write_manifest(items, Split.PRIVATE, path)
    body = json.loads(path.read_text(encoding="utf-8"))
    assert body["count"] == 180
    assert set(body) == {"split", "count", "generated_at", "item_hashes"}
    blob = path.read_text(encoding="utf-8")
    for item in items:
        if item.split is Split.PRIVATE:
            for field in item.fields:
                assert field.expected_value not in blob, "manifest leaks a private label"


def test_verify_manifest_accepts_the_manifest_it_wrote(tmp_path):
    items = _items()
    path = tmp_path / "manifest_private.json"
    write_manifest(items, Split.PRIVATE, path)
    verify_manifest(items, path)


def test_verify_manifest_detects_tampering(tmp_path):
    items = _items()
    path = tmp_path / "manifest_private.json"
    write_manifest(items, Split.PRIVATE, path)
    body = json.loads(path.read_text(encoding="utf-8"))
    body["item_hashes"][0] = "0" * 64
    path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(ValueError, match="manifest mismatch"):
        verify_manifest(items, path)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/golden/test_splits.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.golden.splits'`.

- [ ] **Step 3: Write `ground_truth/golden/splits.py`**

```python
from __future__ import annotations

import random

from ground_truth.golden.schema import Item, Split


def assign_splits(items: list[Item], public_n: int, seed: int) -> list[Item]:
    if public_n > len(items):
        raise ValueError(f"public_n {public_n} exceeds corpus size {len(items)}")
    ordered = sorted(items, key=lambda i: i.item_id)
    rng = random.Random(seed)
    indices = list(range(len(ordered)))
    rng.shuffle(indices)
    public = set(indices[:public_n])
    return [
        item.model_copy(update={"split": Split.PUBLIC if n in public else Split.PRIVATE})
        for n, item in enumerate(ordered)
    ]
```

Sorting by `item_id` before shuffling is what makes the assignment deterministic regardless of generation order.

- [ ] **Step 4: Write `ground_truth/golden/manifest.py`**

```python
from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from ground_truth.golden.schema import Item, Split


def _hashes(items: list[Item], split: Split) -> list[str]:
    return sorted(i.content_hash for i in items if i.split is split)


def write_manifest(items: list[Item], split: Split, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    hashes = _hashes(items, split)
    body = {
        "split": split.value,
        "count": len(hashes),
        "generated_at": datetime.now(UTC).isoformat(),
        "item_hashes": hashes,
    }
    path.write_text(json.dumps(body, indent=2), encoding="utf-8")


def verify_manifest(items: list[Item], path: Path) -> None:
    body = json.loads(path.read_text(encoding="utf-8"))
    expected = _hashes(items, Split(body["split"]))
    if expected != body["item_hashes"]:
        raise ValueError("manifest mismatch: published hashes do not match the corpus")
```

The manifest carries **hashes only** — no labels, no document text. That is the published proof-of-existence for `04` B5.

- [ ] **Step 5: Write `ground_truth/golden/build.py` and `.env.example`**

`build.py` reads `GT_PUBLIC_SEED` and `GT_PRIVATE_SEED` from the environment, generates 300 items, calls `assign_splits(items, public_n=120, seed=int(GT_PUBLIC_SEED))`, writes each item's `render_document` output to `golden/corpus/<split>/<item_id>.txt`, writes `golden/manifest_public.json` and `golden/manifest_private.json`, and inserts `items` and `item_fields` rows into `data/results.duckdb`. It exposes `if __name__ == "__main__":` and nothing else.

```
# .env.example
GT_PUBLIC_SEED=42
GT_PRIVATE_SEED=change-me-and-never-commit-this
```

`.env.example` carries a placeholder. The real `GT_PRIVATE_SEED` goes in `.env`, which `.gitignore` excludes and Task 1's `test_env_file_not_tracked` enforces. **Back it up outside the repository** — losing it means the private split can never be regenerated or rotated.

- [ ] **Step 6: Run the test to verify it passes**

Run: `uv run pytest tests/golden/test_splits.py -v`
Expected: PASS, 6 passed.

- [ ] **Step 7: Build the corpus and verify the boundary holds**

```bash
cp .env.example .env   # then edit GT_PRIVATE_SEED to a real secret
uv run python -m ground_truth.golden.build
git status --porcelain golden/corpus/private/
```

Expected: the last command prints nothing. If it lists files, `.gitignore` is wrong — stop and fix it before committing anything.

- [ ] **Step 8: Commit**

```bash
git add ground_truth/golden/splits.py ground_truth/golden/manifest.py ground_truth/golden/build.py .env.example golden/manifest_public.json golden/manifest_private.json golden/corpus/public/ tests/golden/test_splits.py
git commit -m "feat: 120/180 splits, hash manifests, and the private-corpus boundary"
```

---

### Task 10: Grader contract and `exact`

**Files:**
- Create: `ground_truth/graders/__init__.py`
- Create: `ground_truth/graders/base.py`
- Create: `ground_truth/graders/deterministic/__init__.py`
- Create: `ground_truth/graders/deterministic/exact.py`
- Test: `tests/graders/test_exact.py`

**Interfaces:**
- Consumes: `golden.schema.ItemField`, `golden.rubric.RubricRule`.
- Produces: `Verdict(correct: bool, reason: str, grader_id: str, grader_version: str)` (frozen); `Grader` protocol `__call__(field: ItemField, observed: str | None, rule: RubricRule) -> Verdict`; `collapse_whitespace(value: str) -> str`; `grade_exact(field, observed, rule) -> Verdict` with `grader_id="exact"`, `grader_version="1"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/graders/test_exact.py
from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.deterministic.exact import grade_exact

RULE = RubricRule(grader="exact")


def field(value: str) -> ItemField:
    return ItemField(field_name="status", field_type=FieldType.ENUM_CATEGORY, expected_value=value)


def test_identical_strings_are_correct():
    assert grade_exact(field("approved"), "approved", RULE).correct


def test_surrounding_whitespace_is_normalised():
    assert grade_exact(field("approved"), "  approved\n", RULE).correct


def test_internal_whitespace_collapses():
    assert grade_exact(field("change order"), "change   order", RULE).correct


def test_case_difference_is_incorrect_for_exact():
    assert not grade_exact(field("approved"), "Approved", RULE).correct


def test_missing_observation_is_incorrect_not_an_error():
    v = grade_exact(field("approved"), None, RULE)
    assert not v.correct and "no output" in v.reason


def test_empty_string_is_incorrect():
    assert not grade_exact(field("approved"), "", RULE).correct


def test_unicode_confusable_is_incorrect():
    assert not grade_exact(field("A-1"), "A‐1", RULE).correct  # U+2010 hyphen


def test_verdict_carries_grader_identity():
    v = grade_exact(field("approved"), "approved", RULE)
    assert v.grader_id == "exact" and v.grader_version == "1"


def test_verdict_is_frozen():
    import pytest

    v = grade_exact(field("approved"), "approved", RULE)
    with pytest.raises(Exception):
        v.correct = False
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/graders/test_exact.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.graders.base'`.

- [ ] **Step 3: Write `ground_truth/graders/base.py`**

```python
from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import ItemField

_WS = re.compile(r"\s+")


class Verdict(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    correct: bool
    reason: str
    grader_id: str
    grader_version: str


class Grader(Protocol):
    def __call__(self, field: ItemField, observed: str | None, rule: RubricRule) -> Verdict: ...


def collapse_whitespace(value: str) -> str:
    return _WS.sub(" ", value).strip()
```

`Grader` is a `Protocol`, not a registry. There is no mapping from a name to a grader anywhere — callers import the function they want. That is deliberate, and `test_no_module_scope_callable_registry` enforces it.

- [ ] **Step 4: Write `ground_truth/graders/deterministic/exact.py`**

```python
from __future__ import annotations

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import ItemField
from ground_truth.graders.base import Verdict, collapse_whitespace

GRADER_ID = "exact"
GRADER_VERSION = "1"


def grade_exact(field: ItemField, observed: str | None, rule: RubricRule) -> Verdict:
    if observed is None:
        return Verdict(correct=False, reason="no output for field",
                       grader_id=GRADER_ID, grader_version=GRADER_VERSION)
    got = collapse_whitespace(observed)
    want = collapse_whitespace(field.expected_value)
    return Verdict(
        correct=got == want,
        reason="exact match" if got == want else f"expected {want!r}, got {got!r}",
        grader_id=GRADER_ID,
        grader_version=GRADER_VERSION,
    )
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/graders/test_exact.py tests/test_non_goals.py -v`
Expected: PASS. `test_graders_are_pure` now runs for real — confirm it reports as passed, not skipped.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/graders/ tests/graders/
git commit -m "feat: grader contract and exact grader"
```

---

### Task 11: `numeric_tolerance` grader — the money path

**Files:**
- Create: `ground_truth/graders/deterministic/numeric_tolerance.py`
- Test: `tests/graders/test_numeric_tolerance.py`

**Interfaces:**
- Consumes: `graders.base.Verdict`, `golden.rubric.RubricRule`, `golden.schema.ItemField`.
- Produces: `parse_decimal(raw: str) -> Decimal` raising `ValueError`; `grade_numeric_tolerance(field, observed, rule) -> Verdict` with `grader_id="numeric_tolerance"`, `grader_version="1"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/graders/test_numeric_tolerance.py
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.deterministic.numeric_tolerance import (
    grade_numeric_tolerance,
    parse_decimal,
)

RULE = RubricRule(grader="numeric_tolerance", tolerance=Decimal("0.01"))


def money(value: str) -> ItemField:
    return ItemField(field_name="contract_sum", field_type=FieldType.MONEY,
                     expected_value=value, tolerance=Decimal("0.01"))


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234.56", Decimal("1234.56")),
        ("$1,234.56", Decimal("1234.56")),
        ("(1234.56)", Decimal("-1234.56")),
        ("-1234.56", Decimal("-1234.56")),
        ("USD 1234.56", Decimal("1234.56")),
        ("12.5%", Decimal("0.125")),
        ("-0.00", Decimal("0.00")),
    ],
)
def test_parse_decimal_handles_real_document_forms(raw, expected):
    assert parse_decimal(raw) == expected


@pytest.mark.parametrize("raw", ["", "  ", "-", ".", "not a number", "1.2.3.4.5"])
def test_parse_decimal_raises_on_junk(raw):
    with pytest.raises(ValueError):
        parse_decimal(raw)


def test_unparseable_is_incorrect_not_an_exception():
    v = grade_numeric_tolerance(money("100.00"), "not a number", RULE)
    assert not v.correct and "unparseable" in v.reason


def test_exactly_at_tolerance_is_correct():
    assert grade_numeric_tolerance(money("100.00"), "100.01", RULE).correct


def test_one_unit_inside_tolerance_is_correct():
    assert grade_numeric_tolerance(money("100.00"), "100.00", RULE).correct


def test_one_unit_outside_tolerance_is_incorrect():
    assert not grade_numeric_tolerance(money("100.00"), "100.02", RULE).correct


def test_tolerance_is_symmetric():
    assert grade_numeric_tolerance(money("100.00"), "99.99", RULE).correct
    assert not grade_numeric_tolerance(money("100.00"), "99.98", RULE).correct


def test_field_tolerance_overrides_rule_tolerance():
    field = ItemField(field_name="pct", field_type=FieldType.PERCENT,
                      expected_value="0.125", tolerance=Decimal("0.001"))
    assert not grade_numeric_tolerance(field, "0.127", RULE).correct


def test_missing_tolerance_is_incorrect_with_a_clear_reason():
    field = ItemField(field_name="x", field_type=FieldType.MONEY, expected_value="1.00")
    v = grade_numeric_tolerance(field, "1.00", RubricRule(grader="numeric_tolerance"))
    assert not v.correct and "no tolerance" in v.reason


def test_no_float_anywhere_in_the_module():
    import inspect

    from ground_truth.graders.deterministic import numeric_tolerance

    assert "float(" not in inspect.getsource(numeric_tolerance)


@given(value=st.decimals(min_value=Decimal("-1e6"), max_value=Decimal("1e6"),
                         allow_nan=False, allow_infinity=False, places=2))
def test_a_value_always_matches_itself(value):
    assert grade_numeric_tolerance(money(str(value)), str(value), RULE).correct
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/graders/test_numeric_tolerance.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/graders/deterministic/numeric_tolerance.py`**

```python
from __future__ import annotations

import re
from decimal import Decimal, DecimalException, localcontext

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import ItemField
from ground_truth.graders.base import Verdict

GRADER_ID = "numeric_tolerance"
GRADER_VERSION = "1"

_STRIP = re.compile(r"[^\d,.\-()%]")
_VALID = re.compile(r"^-?\d+(\.\d+)?$")


def parse_decimal(raw: str) -> Decimal:
    text = _STRIP.sub("", raw.strip())
    negative = text.startswith("(") and text.endswith(")")
    text = text.strip("()")
    percent = text.endswith("%")
    text = text.rstrip("%")
    if "," in text and "." in text:
        text = (
            text.replace(",", "")
            if text.rindex(".") > text.rindex(",")
            else text.replace(".", "").replace(",", ".")
        )
    elif "," in text:
        head, _, tail = text.rpartition(",")
        text = f"{head}.{tail}" if len(tail) in (1, 2) else text.replace(",", "")
    if not _VALID.match(text):
        raise ValueError(f"unparseable numeric value: {raw!r}")
    try:
        with localcontext() as ctx:
            ctx.prec = 28
            value = Decimal(text)
    except DecimalException as exc:
        raise ValueError(f"unparseable numeric value: {raw!r}") from exc
    if percent:
        value = value / Decimal(100)
    if negative:
        value = -value
    return value + Decimal(0)  # normalises -0 to 0


def grade_numeric_tolerance(field: ItemField, observed: str | None, rule: RubricRule) -> Verdict:
    def verdict(correct: bool, reason: str) -> Verdict:
        return Verdict(correct=correct, reason=reason,
                       grader_id=GRADER_ID, grader_version=GRADER_VERSION)

    if observed is None:
        return verdict(False, "no output for field")
    tolerance = field.tolerance if field.tolerance is not None else rule.tolerance
    if tolerance is None:
        return verdict(False, "no tolerance declared in rubric or field")
    try:
        got = parse_decimal(observed)
        want = parse_decimal(field.expected_value)
    except ValueError as exc:
        return verdict(False, str(exc))
    delta = abs(got - want)
    return verdict(
        delta <= tolerance,
        f"|{got} - {want}| = {delta} {'<=' if delta <= tolerance else '>'} {tolerance}",
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/graders/test_numeric_tolerance.py -v`
Expected: PASS — 7 parse cases, 6 junk cases, 8 behaviours, 1 property test.

- [ ] **Step 5: Verify the CI money gate catches a violation**

Temporarily add `x = float("1.0")` to the module, run the grep from `.github/workflows/ci.yml` locally, confirm it exits non-zero, then revert.

```bash
grep -rn "float(" ground_truth/graders/ ground_truth/triage/ ; echo "exit=$?"
```

- [ ] **Step 6: Commit**

```bash
git add ground_truth/graders/deterministic/numeric_tolerance.py tests/graders/test_numeric_tolerance.py
git commit -m "feat: numeric tolerance grader with Decimal-only money path"
```

---

### Task 12: `normalised` grader

**Files:**
- Create: `ground_truth/graders/deterministic/normalised.py`
- Test: `tests/graders/test_normalised.py`

**Interfaces:**
- Consumes: `graders.base.{Verdict, collapse_whitespace}`, `golden.rubric.RubricRule`, `golden.schema.ItemField`.
- Produces: `AMBIGUOUS: str` sentinel; `normalise(value: str, steps: list[str]) -> str` supporting steps `casefold`, `strip_accents`, `strip_punctuation`, `strip_legal_suffix`, `strip_leading_zeros`, `iso_date`; `grade_normalised(field, observed, rule) -> Verdict` with `grader_id="normalised"`, `grader_version="1"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/graders/test_normalised.py
import pytest

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import FieldType, ItemField
from ground_truth.graders.deterministic.normalised import AMBIGUOUS, grade_normalised, normalise

NAME_RULE = RubricRule(
    grader="normalised",
    normalisation=["casefold", "strip_accents", "strip_legal_suffix"],
    acceptable_variants=["Acme Construction=Acme Constr"],
)
DATE_RULE = RubricRule(grader="normalised", normalisation=["iso_date"])
ID_RULE = RubricRule(
    grader="normalised", normalisation=["strip_punctuation", "strip_leading_zeros", "casefold"]
)


def field(ftype, value):
    return ItemField(field_name="f", field_type=ftype, expected_value=value)


@pytest.mark.parametrize(
    ("steps", "raw", "expected"),
    [
        (["casefold"], "Acme", "acme"),
        (["strip_accents"], "Béton", "Beton"),
        (["strip_legal_suffix"], "Acme Construction Inc.", "Acme Construction"),
        (["strip_punctuation", "strip_leading_zeros"], "APP-000123", "APP123"),
        (["iso_date"], "1 Sep 2026", "2026-09-01"),
        (["iso_date"], "2026-09-01", "2026-09-01"),
        (["iso_date"], "Sep 1, 2026", "2026-09-01"),
    ],
)
def test_normalise_steps(steps, raw, expected):
    assert normalise(raw, steps) == expected


def test_purely_numeric_slash_date_is_ambiguous():
    assert normalise("01/09/2026", ["iso_date"]) == AMBIGUOUS


def test_unknown_step_raises_rather_than_silently_passing_through():
    with pytest.raises(ValueError, match="unknown normalisation step"):
        normalise("x", ["invent_a_step"])


def test_declared_variant_is_accepted():
    assert grade_normalised(
        field(FieldType.PARTY_NAME, "Acme Construction"), "Acme Constr", NAME_RULE
    ).correct


def test_near_variant_is_rejected():
    assert not grade_normalised(
        field(FieldType.PARTY_NAME, "Acme Construction"), "Acme Concrete", NAME_RULE
    ).correct


def test_case_and_accent_folding_matches():
    assert grade_normalised(field(FieldType.PARTY_NAME, "Béton Inc."), "beton", NAME_RULE).correct


def test_ambiguous_date_is_incorrect_with_a_stated_reason():
    v = grade_normalised(field(FieldType.DATE, "2026-09-01"), "01/09/2026", DATE_RULE)
    assert not v.correct and "ambiguous" in v.reason


def test_identifier_leading_zeros_ignored():
    assert grade_normalised(field(FieldType.IDENTIFIER, "APP-000123"), "app123", ID_RULE).correct


def test_missing_observation_is_incorrect():
    assert not grade_normalised(field(FieldType.DATE, "2026-09-01"), None, DATE_RULE).correct
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/graders/test_normalised.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/graders/deterministic/normalised.py`**

Implement `normalise` as an ordered `for step in steps:` loop with an `if step == "casefold": ... elif step == "strip_accents": ...` chain, ending in `else: raise ValueError(f"unknown normalisation step: {step!r}")`. **Not** a dict of step names to functions — `test_no_module_scope_callable_registry` forbids one, and eight branches read more clearly than an indirection.

- `strip_accents` — `unicodedata.normalize("NFKD", v)` then drop combining marks.
- `strip_punctuation` — remove everything in `string.punctuation`.
- `strip_leading_zeros` — `re.sub(r"(?<=\D)0+(?=\d)|^0+(?=\d)", "", v)`.
- `strip_legal_suffix` — remove any trailing entry from a module-level `tuple` of suffixes (a tuple of strings, not a dict of callables).
- `iso_date` — try `%Y-%m-%d`, `%d %b %Y`, `%d %B %Y`, `%b %d, %Y`, `%B %d, %Y` in order via `datetime.strptime`; a string matching `^\d{1,2}/\d{1,2}/\d{4}$` where both `%d/%m/%Y` and `%m/%d/%Y` parse to valid distinct dates returns `AMBIGUOUS`.

`grade_normalised` normalises both sides; if either is `AMBIGUOUS` the verdict is incorrect with reason containing `"ambiguous"`. `acceptable_variants` entries are `canonical=variant`; a normalised match against either side counts as correct.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/graders/test_normalised.py -v`
Expected: PASS, 16 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/graders/deterministic/normalised.py tests/graders/test_normalised.py
git commit -m "feat: normalised grader with declared variants and ambiguous-date rejection"
```

---

### Task 13: `schema` grader

**Files:**
- Create: `ground_truth/graders/deterministic/schema.py`
- Test: `tests/graders/test_schema_grader.py`

**Interfaces:**
- Consumes: `graders.base.Verdict`, `golden.schema.Item`.
- Produces: `extract_fields(raw_output: str) -> dict[str, str]` raising `ValueError`; `grade_schema(item: Item, raw_output: str) -> Verdict` with `grader_id="schema"`, `grader_version="1"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/graders/test_schema_grader.py
import json

import pytest

from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split
from ground_truth.graders.deterministic.schema import extract_fields, grade_schema


def item() -> Item:
    return Item(
        item_id="i1", split=Split.PUBLIC, rubric_version="v1", source=Source.SYNTHETIC,
        content_hash="h",
        fields=[
            ItemField(field_name="contract_sum", field_type=FieldType.MONEY, expected_value="100.00"),
            ItemField(field_name="app_no", field_type=FieldType.IDENTIFIER, expected_value="A1"),
        ],
    )


def test_valid_output_passes():
    assert grade_schema(item(), json.dumps({"contract_sum": "100.00", "app_no": "A1"})).correct


def test_fenced_json_is_tolerated():
    raw = "```json\n" + json.dumps({"contract_sum": "100.00", "app_no": "A1"}) + "\n```"
    assert grade_schema(item(), raw).correct


def test_missing_field_fails_and_names_it():
    v = grade_schema(item(), json.dumps({"contract_sum": "100.00"}))
    assert not v.correct and "app_no" in v.reason


def test_extra_field_fails_and_names_it():
    v = grade_schema(item(), json.dumps({"contract_sum": "1", "app_no": "A1", "surprise": "x"}))
    assert not v.correct and "surprise" in v.reason


def test_non_string_value_fails():
    v = grade_schema(item(), json.dumps({"contract_sum": 100.0, "app_no": "A1"}))
    assert not v.correct and "contract_sum" in v.reason


def test_truncated_json_fails_without_raising():
    v = grade_schema(item(), '{"contract_sum": "100.00", "app_no":')
    assert not v.correct and "invalid json" in v.reason


def test_json_array_is_not_an_object():
    v = grade_schema(item(), '["contract_sum", "app_no"]')
    assert not v.correct and "invalid json" in v.reason


def test_extract_fields_raises_on_prose():
    with pytest.raises(ValueError):
        extract_fields("The contract sum is one hundred dollars.")
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/graders/test_schema_grader.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/graders/deterministic/schema.py`**

`extract_fields` strips a leading and trailing markdown fence when present, calls `json.loads`, and raises `ValueError("invalid json: ...")` on a `JSONDecodeError` or when the parsed value is not a `dict`. `grade_schema` compares key sets against `{f.field_name for f in item.fields}`, naming the exact missing and extra keys in the reason, and requires every value to be a `str` — a JSON number for a `MONEY` field is a schema violation, because the float it round-trips through is precisely what the money path forbids.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/graders/test_schema_grader.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/graders/deterministic/schema.py tests/graders/test_schema_grader.py
git commit -m "feat: schema grader rejecting missing, extra, and non-string fields"
```

---

### Task 14: `arithmetic` grader

**Files:**
- Create: `ground_truth/graders/deterministic/arithmetic.py`
- Test: `tests/graders/test_arithmetic.py`

**Interfaces:**
- Consumes: `graders.base.Verdict`, `graders.deterministic.numeric_tolerance.parse_decimal`, `golden.schema.Item`.
- Produces: `grade_arithmetic(item: Item, observed: dict[str, str], tolerance: Decimal) -> Verdict` with `grader_id="arithmetic"`, `grader_version="1"`.

- [ ] **Step 1: Write the failing test**

```python
# tests/graders/test_arithmetic.py
from decimal import Decimal

from hypothesis import given
from hypothesis import strategies as st

from ground_truth.golden.generate import ErrorClass, generate
from ground_truth.golden.schema import FieldType, Item, ItemField, Source, Split
from ground_truth.graders.deterministic.arithmetic import grade_arithmetic

TOL = Decimal("0.01")

BALANCED = dict(
    line_1="100.00", line_2="50.00", work_completed="150.00",
    stored_materials="0.00", retainage="15.00", retainage_rate="0.10",
    total_earned_less_retainage="135.00", contract_sum="200.00", balance_to_finish="65.00",
)


def build(values: dict[str, str]) -> Item:
    return Item(
        item_id="i1", split=Split.PUBLIC, rubric_version="v1", source=Source.SYNTHETIC,
        content_hash="h",
        fields=[
            ItemField(
                field_name=k,
                field_type=FieldType.PERCENT if k == "retainage_rate" else FieldType.MONEY,
                expected_value=v,
            )
            for k, v in values.items()
        ],
    )


def test_balanced_document_passes():
    assert grade_arithmetic(build(BALANCED), BALANCED, TOL).correct


def test_off_by_one_cent_within_tolerance_passes():
    assert grade_arithmetic(build(BALANCED), BALANCED | {"work_completed": "150.01"}, TOL).correct


def test_off_by_two_cents_fails_and_names_the_rule():
    v = grade_arithmetic(build(BALANCED), BALANCED | {"work_completed": "150.02"}, TOL)
    assert not v.correct and "line sum" in v.reason


def test_retainage_mismatch_is_caught():
    v = grade_arithmetic(build(BALANCED), BALANCED | {"retainage": "20.00"}, TOL)
    assert not v.correct and "retainage" in v.reason


def test_balance_to_finish_mismatch_is_caught():
    v = grade_arithmetic(build(BALANCED), BALANCED | {"balance_to_finish": "60.00"}, TOL)
    assert not v.correct and "balance to finish" in v.reason


def test_multiple_broken_rules_are_all_reported():
    bad = BALANCED | {"retainage": "20.00", "balance_to_finish": "60.00"}
    v = grade_arithmetic(build(BALANCED), bad, TOL)
    assert "retainage" in v.reason and "balance to finish" in v.reason


def test_missing_field_names_the_field():
    bad = {k: v for k, v in BALANCED.items() if k != "work_completed"}
    v = grade_arithmetic(build(BALANCED), bad, TOL)
    assert not v.correct and "work_completed" in v.reason


def test_generator_injected_arithmetic_errors_are_all_caught():
    targets = {
        ErrorClass.RETAINAGE_MISMATCH.value,
        ErrorClass.STORED_MATERIALS_DOUBLE_COUNT.value,
    }
    items = [i for i in generate(count=120, seed=17, rubric_version="v1") if i.injected_error in targets]
    assert items, "generator must produce arithmetic error items at this seed"
    for item in items:
        observed = {f.field_name: f.expected_value for f in item.fields}
        assert not grade_arithmetic(item, observed, TOL).correct, f"{item.item_id} slipped through"


@given(
    line_1=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e6"),
                       allow_nan=False, allow_infinity=False, places=2),
    line_2=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e6"),
                       allow_nan=False, allow_infinity=False, places=2),
    stored=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e5"),
                       allow_nan=False, allow_infinity=False, places=2),
    extra=st.decimals(min_value=Decimal("0"), max_value=Decimal("1e6"),
                      allow_nan=False, allow_infinity=False, places=2),
)
def test_property_any_internally_consistent_document_passes(line_1, line_2, stored, extra):
    """Every document built to satisfy the four rules must pass, for any amounts."""
    work = line_1 + line_2
    retainage = (work * Decimal("0.10")).quantize(Decimal("0.01"))
    earned = work + stored - retainage
    contract = work + stored + extra
    values = {
        "line_1": str(line_1), "line_2": str(line_2), "work_completed": str(work),
        "stored_materials": str(stored), "retainage": str(retainage),
        "retainage_rate": "0.10", "total_earned_less_retainage": str(earned),
        "contract_sum": str(contract), "balance_to_finish": str(contract - earned),
    }
    verdict = grade_arithmetic(build(values), values, TOL)
    assert verdict.correct, verdict.reason


@given(
    delta=st.decimals(min_value=Decimal("0.02"), max_value=Decimal("1000"),
                      allow_nan=False, allow_infinity=False, places=2),
)
def test_property_breaking_the_line_sum_always_fails(delta):
    """Any perturbation beyond tolerance must be caught, at any magnitude."""
    bad = BALANCED | {"work_completed": str(Decimal(BALANCED["work_completed"]) + delta)}
    verdict = grade_arithmetic(build(BALANCED), bad, TOL)
    assert not verdict.correct and "line sum" in verdict.reason
```

Two tests carry the weight here. `test_generator_injected_arithmetic_errors_are_all_caught` closes the loop between Task 8's injected errors and this grader — a generator that injects errors no grader catches is a corpus that proves nothing. The two `hypothesis` properties discharge spec §16's requirement that every arithmetic rule carry a property test: one asserts that consistency always passes regardless of magnitude, the other that any beyond-tolerance perturbation always fails. Fixed examples cannot make either claim.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/graders/test_arithmetic.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/graders/deterministic/arithmetic.py`**

Check four rules, accumulating **every** failure into the reason rather than short-circuiting — a document can break more than one:

1. **line sum** — `line_1 + line_2 == work_completed`. Reason text contains `"line sum"`.
2. **retainage** — `retainage == retainage_rate * work_completed`. Reason contains `"retainage"`.
3. **stored materials** — `total_earned_less_retainage == work_completed + stored_materials - retainage`. Reason contains `"stored materials"`.
4. **balance to finish** — `balance_to_finish == contract_sum - total_earned_less_retainage`. Reason contains `"balance to finish"`.

All comparisons are `abs(a - b) <= tolerance` on `Decimal` values from `parse_decimal`. A field absent from `observed` fails the rule that needs it and names the missing field. The verdict is `correct=True` only when every rule holds.

Note that rule 3 catches `STORED_MATERIALS_DOUBLE_COUNT` from Task 8: when the generator folds `stored` into `work_completed`, `total_earned_less_retainage` no longer reconciles.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/graders/test_arithmetic.py -v`
Expected: PASS, 10 passed (8 examples plus 2 `hypothesis` properties).

- [ ] **Step 5: Run the whole suite and confirm the coverage floor**

Run: `uv run pytest -v`
Expected: all pass, coverage ≥ 75%.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/graders/deterministic/arithmetic.py tests/graders/test_arithmetic.py
git commit -m "feat: cross-field arithmetic grader catching every injected arithmetic error"
```

---

### Task 15: The `bok-core` shim and `runner.py` — phase 1

**Files:**
- Create: `ground_truth/_bok_shim.py`
- Create: `ground_truth/runner.py`
- Test: `tests/test_runner.py`

> **Contract alignment (amended 2025-09-18).** `backoffice-kit/docs/INTERFACE-CONTRACT.md` v0.1 is
> authoritative. The shim below mirrors that surface **exactly**, so that swapping `_bok_shim` for
> the real `bok_core` is an import change and nothing else. A shim that invents its own shapes is a
> second implementation you will have to port twice.
>
> **This task previously carried a measurement bug.** It disabled the cache but said nothing about
> failover, and `00` R2 makes the fallback chain default-on. On a 9,000-call sweep across free tiers
> spanning several nights, a 429 or a deleted model would have silently served slot-a's prompt from
> slot-b's provider and recorded it as slot-a's result — invisibly, with no error, straight onto the
> leaderboard. `failover=FailoverMode.DISABLED` is now as non-negotiable as the cache rule.

**Files:**
- Create: `ground_truth/_bok_shim.py`
- Create: `ground_truth/runner.py`
- Test: `tests/test_runner.py`

**Interfaces:** (mirroring `INTERFACE-CONTRACT.md` §1.1, §1.2, §3.1, §3.2)
- Consumes: `store.db`, `golden.schema.Item`.
- Produces, in `_bok_shim.py`: `Sensitivity` (`StrEnum`: `PUBLIC`, `SYNTHETIC`, `REDACTED`, `CLIENT_CONFIDENTIAL`); `Trust` (`TRUSTED`, `UNTRUSTED`); `SensitivityViolation(Exception)`; `ProvidersUnavailable(RuntimeError)`; `Labelled(value: T, sensitivity: Sensitivity, trust: Trust = TRUSTED)` (frozen, generic); `CallContext(commercial: bool = False)`; `CacheMode` / `FailoverMode` (`ENABLED`, `DISABLED`); `Handle(slot: str, provider: str, is_fallback: bool)`; `Response(text: str, ledger_call_id: str, provider_served: str, fingerprint: str | None, latency_ms: int)`; `resolve(lane: str) -> Handle`; `call(handle, payload: Labelled[str], context: CallContext, *, response_schema=None, tools_disabled=False, cache=CacheMode.ENABLED, failover=FailoverMode.ENABLED) -> Response`.
- Produces, in `runner.py`: `Caller` protocol matching `call`'s signature; `build_prompt(item: Item) -> Labelled[str]`; `execute_sweep(con, items: list[Item], slots: list[str], replicates: int, *, context: CallContext, resolve_fn, call_fn) -> str` returning `sweep_id`; module constants `BENCHMARK_CACHE = CacheMode.DISABLED` and `BENCHMARK_FAILOVER = FailoverMode.DISABLED`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_runner.py
from dataclasses import dataclass, field as dc_field

import pytest

from ground_truth._bok_shim import (
    CacheMode,
    CallContext,
    FailoverMode,
    Handle,
    Labelled,
    ProvidersUnavailable,
    Response,
    Sensitivity,
    SensitivityViolation,
)
from ground_truth.golden.generate import generate
from ground_truth.runner import execute_sweep
from ground_truth.store.db import connect, migrate


@dataclass
class FakeGateway:
    """Records exactly what the runner asked for, so the tests can assert the flags."""

    seen: list[tuple[str, CacheMode, FailoverMode, Sensitivity, bool]] = dc_field(
        default_factory=list
    )
    fallback_slots: frozenset[str] = frozenset()
    refuse_commercial: bool = False

    def resolve(self, lane: str) -> Handle:
        return Handle(slot=lane, provider="fake", is_fallback=lane in self.fallback_slots)

    def call(self, handle, payload, context, *, response_schema=None, tools_disabled=False,
             cache=CacheMode.ENABLED, failover=FailoverMode.ENABLED) -> Response:
        if self.refuse_commercial and context.commercial:
            raise SensitivityViolation(
                "provider 'fake' commercial_use is unverified; terms "
                "https://example.invalid/terms retrieved 2026-08-31"
            )
        self.seen.append(
            (handle.slot, cache, failover, payload.sensitivity, context.commercial)
        )
        return Response(
            text='{"contract_sum": "1.00"}',
            ledger_call_id=f"{handle.slot}-{len(self.seen)}",
            provider_served="fake",
            fingerprint=None,
            latency_ms=42,
        )


@pytest.fixture()
def con(tmp_path):
    c = connect(tmp_path / "t.duckdb")
    migrate(c)
    yield c
    c.close()


def sweep(con, gw, items, slots, replicates, *, commercial=False):
    return execute_sweep(con, items, slots, replicates,
                         context=CallContext(commercial=commercial),
                         resolve_fn=gw.resolve, call_fn=gw.call)


def test_sweep_writes_one_output_per_item_slot_replicate(con):
    items = generate(count=4, seed=1, rubric_version="v1")
    sweep(con, FakeGateway(), items, ["slot-a", "slot-b"], 5)
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 4 * 2 * 5


def test_sweep_never_writes_verdicts(con):
    items = generate(count=2, seed=1, rubric_version="v1")
    sweep(con, FakeGateway(), items, ["slot-a"], 3)
    assert con.execute("SELECT count(*) FROM verdicts").fetchone()[0] == 0


def test_benchmark_execution_bypasses_cache(con):
    gw = FakeGateway()
    sweep(con, gw, generate(count=2, seed=1, rubric_version="v1"), ["slot-a"], 5)
    assert gw.seen and all(cache is CacheMode.DISABLED for _, cache, _, _, _ in gw.seen), (
        "a cache hit would return identical text for replicates 2-5 and fabricate zero variance"
    )


def test_benchmark_slot_does_not_failover(con):
    """Model identity is the variable under study. A silent failover would attribute
    slot-a's output to slot-b's provider and corrupt the benchmark invisibly."""
    gw = FakeGateway()
    sweep(con, gw, generate(count=2, seed=1, rubric_version="v1"), ["slot-a"], 5)
    assert gw.seen and all(fo is FailoverMode.DISABLED for _, _, fo, _, _ in gw.seen)


def test_provider_failure_writes_no_row_rather_than_a_substituted_one(con):
    class Failing(FakeGateway):
        def call(self, *a, **k):
            raise ProvidersUnavailable("slot-a")

    items = generate(count=2, seed=1, rubric_version="v1")
    with pytest.raises(ProvidersUnavailable):
        sweep(con, Failing(), items, ["slot-a"], 5)
    assert con.execute("SELECT count(*) FROM outputs").fetchone()[0] == 0, (
        "a failed slot must leave a gap, never a row served by someone else"
    )


def test_fallback_handle_is_refused_for_benchmark_execution(con):
    """lanes.resolve returns a deterministic fallback handle when nothing is eligible.
    Recording its output as a model result would publish a non-result as a measurement."""
    gw = FakeGateway(fallback_slots=frozenset({"slot-a"}))
    with pytest.raises(ValueError, match="fallback"):
        sweep(con, gw, generate(count=1, seed=1, rubric_version="v1"), ["slot-a"], 1)


def test_payload_is_labelled_synthetic(con):
    gw = FakeGateway()
    sweep(con, gw, generate(count=1, seed=1, rubric_version="v1"), ["slot-a"], 1)
    assert all(sens is Sensitivity.SYNTHETIC for _, _, _, sens, _ in gw.seen)


def test_ledger_call_id_recorded_for_every_output(con):
    sweep(con, FakeGateway(), generate(count=2, seed=1, rubric_version="v1"), ["slot-a"], 2)
    missing = con.execute(
        "SELECT count(*) FROM outputs WHERE ledger_call_id IS NULL OR ledger_call_id = ''"
    ).fetchone()[0]
    assert missing == 0, "without a ledger id, fingerprint tracking is impossible"


def test_replicate_indices_start_at_one_and_are_contiguous(con):
    sweep(con, FakeGateway(), generate(count=1, seed=1, rubric_version="v1"), ["slot-a"], 5)
    rows = con.execute("SELECT replicate_idx FROM outputs ORDER BY replicate_idx").fetchall()
    assert [r[0] for r in rows] == [1, 2, 3, 4, 5]


def test_commercial_run_refuses_non_commercial_provider(con):
    gw = FakeGateway(refuse_commercial=True)
    items = generate(count=1, seed=1, rubric_version="v1")
    with pytest.raises(SensitivityViolation, match="commercial_use"):
        sweep(con, gw, items, ["slot-a"], 1, commercial=True)


def test_refusal_message_cites_its_evidence(con):
    gw = FakeGateway(refuse_commercial=True)
    items = generate(count=1, seed=1, rubric_version="v1")
    with pytest.raises(SensitivityViolation) as exc:
        sweep(con, gw, items, ["slot-a"], 1, commercial=True)
    assert "https://" in str(exc.value) and "retrieved" in str(exc.value), (
        "a refusal a client's counsel cannot audit is not a control"
    )


def test_no_model_id_literal_in_runner_source():
    import inspect

    from ground_truth import runner

    lowered = inspect.getsource(runner).lower()
    for banned in ("gemini", "llama", "gpt-", "claude-", "mistral", "qwen"):
        assert banned not in lowered, f"model id {banned!r} must live in models.yaml, not source"
```

`test_provider_failure_writes_no_row_rather_than_a_substituted_one` and `test_fallback_handle_is_refused_for_benchmark_execution` are the two that close the failover hole. The first proves a failed slot leaves a *gap*; the second proves the deterministic fallback handle — which `lanes.resolve` returns rather than raising, per contract §3.1 — never gets recorded as a model result.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_runner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth._bok_shim'`.

- [ ] **Step 3: Write `ground_truth/_bok_shim.py`**

```python
"""Minimum stand-in for bok-core, mirroring INTERFACE-CONTRACT.md v0.1 exactly.

ponytail: local shim, not the real substrate. Every symbol here has the same name and
signature as its bok_core counterpart, so replacing it is an import change and nothing
else -- `from bok_core.boundary.sensitivity import Labelled, Sensitivity, Trust`,
`from bok_core.boundary.policy import CallContext, SensitivityViolation`,
`from bok_core.gateway.lanes import resolve`, `from bok_core.gateway.router import
call, CacheMode, FailoverMode`. Deviating from those shapes here would mean porting
this twice. The foreign key outputs.ledger_call_id -> bok_ledger.call_id is the
load-bearing part; see contract section 3.4.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel

T = TypeVar("T")


class Sensitivity(StrEnum):
    PUBLIC = "PUBLIC"
    SYNTHETIC = "SYNTHETIC"
    REDACTED = "REDACTED"
    CLIENT_CONFIDENTIAL = "CLIENT_CONFIDENTIAL"


class Trust(StrEnum):
    TRUSTED = "TRUSTED"
    UNTRUSTED = "UNTRUSTED"


class SensitivityViolation(Exception):
    """Raised by router.call before dispatch. The message cites its evidence."""


class ProvidersUnavailable(RuntimeError):
    """No eligible provider served the call. Never substitute another slot's provider."""


@dataclass(frozen=True)
class Labelled(Generic[T]):
    value: T
    sensitivity: Sensitivity
    trust: Trust = Trust.TRUSTED


class CallContext(BaseModel):
    commercial: bool = False


class CacheMode(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


class FailoverMode(StrEnum):
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"


@dataclass(frozen=True)
class Handle:
    slot: str
    provider: str
    is_fallback: bool = False


@dataclass(frozen=True)
class Response:
    text: str
    ledger_call_id: str
    provider_served: str
    fingerprint: str | None
    latency_ms: int


class Quota(BaseModel):
    """Contract section 3.3. None means the provider does not publish that limit --
    the planner must treat it as unbounded, never as zero."""

    rpm: int | None = None
    tpm: int | None = None
    rpd: int | None = None


def remaining(provider: str) -> Quota:  # pragma: no cover - shim stub
    """Public query, not only internal enforcement. Phase 2's scheduler asks before
    dispatching each sweep batch. The shim returns an unbounded quota."""
    return Quota()
```

Note `Handle.is_fallback`. Contract §3.1 says `resolve` returns the lane's **deterministic fallback handle** when no provider is eligible, rather than raising. For most consumers that is the right behaviour; for a benchmark it is a trap, because a fallback's output is not a measurement of the model. The runner checks the flag and refuses.

- [ ] **Step 4: Write `ground_truth/runner.py`**

```python
from __future__ import annotations

import hashlib
import subprocess
import uuid
from collections.abc import Callable
from datetime import UTC, datetime

import duckdb

from ground_truth._bok_shim import (
    CacheMode,
    CallContext,
    FailoverMode,
    Handle,
    Labelled,
    Response,
    Sensitivity,
)
from ground_truth.golden.schema import Item

ResolveFn = Callable[[str], Handle]
CallFn = Callable[..., Response]

# Both are non-negotiable for benchmark execution. See contract section 3.2.
BENCHMARK_CACHE = CacheMode.DISABLED        # replicate variance IS the measurement
BENCHMARK_FAILOVER = FailoverMode.DISABLED  # model identity IS the variable under study


def _code_version() -> str:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def build_prompt(item: Item) -> Labelled[str]:
    names = ", ".join(f.field_name for f in item.fields)
    text = (
        "Extract these fields from the document and return a single JSON object "
        f"whose keys are exactly: {names}. Every value must be a JSON string.\n\n"
        f"---\n{item.content_hash}\n"
    )
    # The golden set is generated by us and contains no real party's data.
    return Labelled(value=text, sensitivity=Sensitivity.SYNTHETIC)


def execute_sweep(
    con: duckdb.DuckDBPyConnection,
    items: list[Item],
    slots: list[str],
    replicates: int,
    *,
    context: CallContext,
    resolve_fn: ResolveFn,
    call_fn: CallFn,
) -> str:
    sweep_id = uuid.uuid4().hex
    code_version = _code_version()
    for slot in slots:
        handle = resolve_fn(slot)
        if handle.is_fallback:
            raise ValueError(
                f"slot {slot!r} resolved to a deterministic fallback handle: no eligible "
                "provider. A fallback's output is not a measurement of the model and must "
                "never be recorded as one. Fix models.yaml or drop the slot from the sweep."
            )
        run_id = uuid.uuid4().hex
        con.execute(
            "INSERT INTO runs VALUES (?,?,NULL,?,?,?,?,?,?,?)",
            [run_id, datetime.now(UTC), slot, "resolved-at-runtime", handle.provider,
             context.commercial, sweep_id, code_version, "models-yaml-hash"],
        )
        for item in items:
            payload = build_prompt(item)
            prompt_hash = hashlib.sha256(payload.value.encode()).hexdigest()
            for replicate in range(1, replicates + 1):
                # A raised SensitivityViolation or ProvidersUnavailable propagates:
                # a failed slot must leave a gap, never a substituted row.
                result = call_fn(
                    handle, payload, context,
                    cache=BENCHMARK_CACHE, failover=BENCHMARK_FAILOVER,
                )
                con.execute(
                    "INSERT INTO outputs VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    [uuid.uuid4().hex, run_id, item.item_id, replicate, result.text,
                     result.ledger_call_id, result.provider_served, result.fingerprint,
                     result.latency_ms, prompt_hash, datetime.now(UTC)],
                )
        con.execute("UPDATE runs SET finished_at = ? WHERE run_id = ?", [datetime.now(UTC), run_id])
    return sweep_id
```

Three properties worth stating plainly, because each one is a test above. The runner grades nothing, computes nothing and imports no grader — that is the phase split. It never catches a provider error, so a failed slot leaves a **gap** rather than a row attributed to the wrong provider. And it refuses a fallback handle outright, because contract §3.1 hands one back silently when nothing is eligible, and silently is exactly how a non-result would reach the leaderboard.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_runner.py -v`
Expected: PASS, 11 passed.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/_bok_shim.py ground_truth/runner.py tests/test_runner.py
git commit -m "feat: phase-1 runner with cache and failover disabled, contract-shaped shim"
```

---

### Task 16: `stats/bootstrap.py` — cluster bootstrap

**Files:**
- Create: `ground_truth/stats/__init__.py`
- Create: `ground_truth/stats/bootstrap.py`
- Test: `tests/stats/test_bootstrap.py`

**Interfaces:**
- Consumes: `scipy.stats.bootstrap`, `numpy`.
- Produces: `Interval(point: float, low: float, high: float, n: int, method: str)` (frozen) with method `overlaps(other: Interval) -> bool`; `cluster_bootstrap_ci(observations: list[tuple[str, bool]], *, confidence: float = 0.95, n_resamples: int = 10_000, seed: int) -> Interval`; `naive_bootstrap_ci(...)` with the same signature.

- [ ] **Step 1: Write the failing test**

```python
# tests/stats/test_bootstrap.py
import random

import pytest

from ground_truth.stats.bootstrap import Interval, cluster_bootstrap_ci, naive_bootstrap_ci


def replicated(n_items: int, replicates: int, p: float, seed: int):
    rng = random.Random(seed)
    obs = []
    for i in range(n_items):
        easy = rng.random() < p                     # the item is easy or hard
        for _ in range(replicates):
            obs.append((f"i{i}", easy if rng.random() < 0.9 else not easy))
    return obs


def test_interval_brackets_the_point_estimate():
    ci = cluster_bootstrap_ci(replicated(60, 5, 0.9, seed=1), seed=1, n_resamples=500)
    assert ci.low <= ci.point <= ci.high


def test_n_is_the_item_count_not_the_row_count():
    ci = cluster_bootstrap_ci(replicated(60, 5, 0.9, seed=1), seed=1, n_resamples=500)
    assert ci.n == 60, "the sampling unit is the item; reporting 300 would overstate the sample"


def test_cluster_bootstrap_wider_than_naive():
    obs = replicated(60, 5, 0.9, seed=2)
    clustered = cluster_bootstrap_ci(obs, seed=2, n_resamples=2000)
    naive = naive_bootstrap_ci(obs, seed=2, n_resamples=2000)
    assert (clustered.high - clustered.low) > (naive.high - naive.low), (
        "ignoring within-item correlation understates every interval by roughly sqrt(replicates)"
    )


def test_overlapping_intervals_are_detected():
    a = Interval(point=0.90, low=0.87, high=0.93, n=180, method="cluster-BCa")
    b = Interval(point=0.92, low=0.89, high=0.95, n=180, method="cluster-BCa")
    c = Interval(point=0.99, low=0.98, high=1.00, n=180, method="cluster-BCa")
    assert a.overlaps(b) and b.overlaps(a)
    assert not a.overlaps(c)


def test_empty_input_raises_rather_than_returning_a_number():
    with pytest.raises(ValueError):
        cluster_bootstrap_ci([], seed=1)


def test_all_correct_is_degenerate_not_a_crash():
    ci = cluster_bootstrap_ci([(f"i{i}", True) for i in range(20)], seed=1, n_resamples=200)
    assert ci.point == 1.0 and ci.method == "degenerate"


@pytest.mark.slow
def test_bootstrap_ci_covers_known_parameter():
    p, covered, trials = 0.9, 0, 1000
    for t in range(trials):
        rng = random.Random(1000 + t)
        obs = [(f"i{i}", rng.random() < p) for i in range(180)]
        ci = cluster_bootstrap_ci(obs, seed=t, n_resamples=400)
        if ci.low <= p <= ci.high:
            covered += 1
    rate = covered / trials
    assert 0.93 <= rate <= 0.97, f"nominal 95% interval covered {rate:.3f} of the time"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/stats/test_bootstrap.py -v -m "not slow"`
Expected: FAIL — `ModuleNotFoundError: No module named 'ground_truth.stats.bootstrap'`.

- [ ] **Step 3: Write `ground_truth/stats/bootstrap.py`**

```python
from __future__ import annotations

from collections import defaultdict

import numpy as np
from pydantic import BaseModel, ConfigDict
from scipy.stats import bootstrap


class Interval(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    point: float
    low: float
    high: float
    n: int
    method: str

    def overlaps(self, other: "Interval") -> bool:
        return self.low <= other.high and other.low <= self.high


def _grouped(observations: list[tuple[str, bool]]) -> list[list[bool]]:
    buckets: dict[str, list[bool]] = defaultdict(list)
    for item_id, correct in observations:
        buckets[item_id].append(correct)
    return [buckets[k] for k in sorted(buckets)]


def _interval(values: np.ndarray, confidence: float, n_resamples: int, seed: int,
              n: int, method: str) -> Interval:
    point = float(values.mean())
    if float(values.std()) == 0.0:
        return Interval(point=point, low=point, high=point, n=n, method="degenerate")
    res = bootstrap(
        (values,), np.mean, confidence_level=confidence, n_resamples=n_resamples,
        method="BCa", random_state=np.random.default_rng(seed),
    )
    return Interval(
        point=point, low=float(res.confidence_interval.low),
        high=float(res.confidence_interval.high), n=n, method=method,
    )


def cluster_bootstrap_ci(
    observations: list[tuple[str, bool]], *, confidence: float = 0.95,
    n_resamples: int = 10_000, seed: int,
) -> Interval:
    if not observations:
        raise ValueError("cannot compute an interval from zero observations")
    clusters = _grouped(observations)
    means = np.array([float(np.mean(c)) for c in clusters], dtype=float)
    return _interval(means, confidence, n_resamples, seed, len(clusters), "cluster-BCa")


def naive_bootstrap_ci(
    observations: list[tuple[str, bool]], *, confidence: float = 0.95,
    n_resamples: int = 10_000, seed: int,
) -> Interval:
    """Row-level bootstrap. Present ONLY so test_cluster_bootstrap_wider_than_naive can
    demonstrate the understatement. Never call this from analysis code."""
    if not observations:
        raise ValueError("cannot compute an interval from zero observations")
    rows = np.array([float(c) for _, c in observations], dtype=float)
    return _interval(rows, confidence, n_resamples, seed, len(rows), "naive-BCa")
```

`Interval.overlaps` is what the leaderboard uses to emit *"not distinguishable at this sample size."* It lives here so that behaviour has exactly one implementation.

- [ ] **Step 4: Run the fast tests**

Run: `uv run pytest tests/stats/test_bootstrap.py -v -m "not slow"`
Expected: PASS, 6 passed, 1 deselected.

- [ ] **Step 5: Run the coverage simulation**

Run: `uv run pytest tests/stats/test_bootstrap.py::test_bootstrap_ci_covers_known_parameter -v`
Expected: PASS. This takes several minutes. **If the coverage rate falls outside [0.93, 0.97], the estimator is wrong — do not widen the assertion to make it pass.** Fix the estimator.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/stats/ tests/stats/
git commit -m "feat: cluster bootstrap CI validated against known coverage"
```

---

### Task 17: `stats/mde.py` — minimum detectable effect

**Files:**
- Create: `ground_truth/stats/mde.py`
- Test: `tests/stats/test_mde.py`

**Interfaces:**
- Consumes: `scipy.stats.norm`.
- Produces: `mde_paired_binary(n_items: int, discordance_rate: float, *, alpha: float = 0.05, power: float = 0.8, n_comparisons: int = 1) -> float`; `describe_mde(...) -> str` with the same signature.

- [ ] **Step 1: Write the failing test**

```python
# tests/stats/test_mde.py
import pytest

from ground_truth.stats.mde import describe_mde, mde_paired_binary


def test_matches_closed_form_for_a_single_comparison():
    # McNemar normal approximation: delta = (z_{alpha/2} + z_{power}) * sqrt(disc / n)
    # n=180, disc=0.10 -> (1.959964 + 0.841621) * sqrt(0.10/180)
    assert mde_paired_binary(180, 0.10) == pytest.approx(0.066033, abs=5e-5)


def test_mde_falls_as_n_rises():
    assert mde_paired_binary(300, 0.10) < mde_paired_binary(180, 0.10)


def test_mde_rises_with_more_comparisons():
    assert mde_paired_binary(180, 0.10, n_comparisons=48) > mde_paired_binary(180, 0.10)


def test_mde_rises_with_discordance():
    assert mde_paired_binary(180, 0.30) > mde_paired_binary(180, 0.10)


def test_zero_items_raises():
    with pytest.raises(ValueError):
        mde_paired_binary(0, 0.10)


def test_discordance_out_of_range_raises():
    with pytest.raises(ValueError):
        mde_paired_binary(180, 0.0)
    with pytest.raises(ValueError):
        mde_paired_binary(180, 1.5)


def test_description_states_n_the_correction_and_the_null_caveat():
    text = describe_mde(180, 0.10, n_comparisons=48)
    assert "180" in text and "Bonferroni" in text and "48" in text
    assert "not that none exists" in text
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/stats/test_mde.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/stats/mde.py`**

```python
from __future__ import annotations

import math

from scipy.stats import norm


def mde_paired_binary(
    n_items: int, discordance_rate: float, *,
    alpha: float = 0.05, power: float = 0.8, n_comparisons: int = 1,
) -> float:
    if n_items <= 0:
        raise ValueError("n_items must be positive")
    if not 0.0 < discordance_rate <= 1.0:
        raise ValueError("discordance_rate must be in (0, 1]")
    if n_comparisons < 1:
        raise ValueError("n_comparisons must be at least 1")
    adjusted_alpha = alpha / n_comparisons  # Bonferroni: conservative and knowable in advance
    z_alpha = float(norm.ppf(1 - adjusted_alpha / 2))
    z_beta = float(norm.ppf(power))
    return (z_alpha + z_beta) * math.sqrt(discordance_rate / n_items)


def describe_mde(
    n_items: int, discordance_rate: float, *,
    alpha: float = 0.05, power: float = 0.8, n_comparisons: int = 1,
) -> str:
    delta = mde_paired_binary(
        n_items, discordance_rate, alpha=alpha, power=power, n_comparisons=n_comparisons
    )
    return (
        f"At n={n_items} items with a {discordance_rate:.0%} discordance rate, this comparison "
        f"can detect a difference of {delta * 100:.1f} percentage points or larger "
        f"({power:.0%} power, alpha={alpha}, Bonferroni-corrected across {n_comparisons} "
        f"comparisons). A null result means no difference larger than that was detectable — "
        f"not that none exists."
    )
```

The final sentence of `describe_mde` is published verbatim beside every null result. It is the difference between honest reporting and implying absence of effect.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/stats/test_mde.py -v`
Expected: PASS, 7 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/stats/mde.py tests/stats/test_mde.py
git commit -m "feat: MDE calculator with conservative Bonferroni multiplicity"
```

---

### Task 18: `triage/ingest.py`

**Files:**
- Create: `ground_truth/triage/__init__.py`
- Create: `ground_truth/triage/ingest.py`
- Create: `docs/triage-intake-template.csv`
- Test: `tests/triage/test_ingest.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `COLUMNS: tuple[str, ...]`; `Intent(intent: str, volume_per_month: int, current_cost_per_item: Decimal, cost_of_error: Decimal | None, client_quote: str, unbounded_error: bool)` (frozen); `load_intents(path: Path) -> list[Intent]` raising `ValueError`.

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_ingest.py
from decimal import Decimal

import pytest

from ground_truth.triage.ingest import load_intents

HEADER = "intent,volume_per_month,current_cost_per_item,cost_of_error,client_quote\n"


def write(tmp_path, body: str):
    p = tmp_path / "intake.csv"
    p.write_text(HEADER + body, encoding="utf-8")
    return p


def test_parses_a_well_formed_row(tmp_path):
    path = write(tmp_path, 'invoice_total,4000,2.50,40.00,"About forty dollars of rework"\n')
    intent = load_intents(path)[0]
    assert intent.volume_per_month == 4000
    assert intent.current_cost_per_item == Decimal("2.50")
    assert intent.cost_of_error == Decimal("40.00")


def test_costs_are_decimal_not_float(tmp_path):
    path = write(tmp_path, 'a,10,0.10,0.30,"x"\n')
    assert isinstance(load_intents(path)[0].cost_of_error, Decimal)


def test_unbounded_marker_is_recognised(tmp_path):
    path = write(tmp_path, 'bank_detail_change,20,1.00,unbounded,"Could lose a whole payment"\n')
    intent = load_intents(path)[0]
    assert intent.unbounded_error and intent.cost_of_error is None


def test_missing_client_quote_is_rejected(tmp_path):
    path = write(tmp_path, "a,10,0.10,0.30,\n")
    with pytest.raises(ValueError, match="client_quote"):
        load_intents(path)


def test_missing_cost_of_error_is_rejected(tmp_path):
    path = write(tmp_path, 'a,10,0.10,,"x"\n')
    with pytest.raises(ValueError, match="cost_of_error"):
        load_intents(path)


def test_wrong_header_is_rejected(tmp_path):
    p = tmp_path / "bad.csv"
    p.write_text("intent,volume\na,1\n", encoding="utf-8")
    with pytest.raises(ValueError, match="columns"):
        load_intents(p)


def test_error_names_the_offending_line(tmp_path):
    path = write(tmp_path, 'a,10,0.10,0.30,"ok"\nb,10,0.10,0.30,\n')
    with pytest.raises(ValueError, match="line 3"):
        load_intents(path)


def test_template_file_loads(tmp_path):
    from pathlib import Path

    template = Path(__file__).resolve().parents[2] / "docs" / "triage-intake-template.csv"
    assert load_intents(template), "the shipped template must be a valid, loadable example"
```

`test_missing_client_quote_is_rejected` is what enforces `04` B11 — a cost-of-error number with no client sentence behind it is our estimate wearing their clothes, and the file refuses to load.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/triage/test_ingest.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/triage/ingest.py`**

```python
from __future__ import annotations

import csv
from decimal import Decimal, InvalidOperation
from pathlib import Path

from pydantic import BaseModel, ConfigDict

COLUMNS: tuple[str, ...] = (
    "intent", "volume_per_month", "current_cost_per_item", "cost_of_error", "client_quote",
)
UNBOUNDED = {"unbounded", "unbounded_error", "infinite"}


class Intent(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    intent: str
    volume_per_month: int
    current_cost_per_item: Decimal
    cost_of_error: Decimal | None
    client_quote: str
    unbounded_error: bool = False


def load_intents(path: Path) -> list[Intent]:
    with path.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        if tuple(reader.fieldnames or ()) != COLUMNS:
            raise ValueError(f"expected columns {COLUMNS}, got {reader.fieldnames}")
        intents: list[Intent] = []
        for line, row in enumerate(reader, start=2):
            quote = (row["client_quote"] or "").strip()
            if not quote:
                raise ValueError(
                    f"line {line}: client_quote is required — cost_of_error must be the "
                    "client's number in the client's words, not our estimate"
                )
            raw_cost = (row["cost_of_error"] or "").strip()
            if not raw_cost:
                raise ValueError(f"line {line}: cost_of_error is required")
            unbounded = raw_cost.lower() in UNBOUNDED
            try:
                intents.append(
                    Intent(
                        intent=row["intent"].strip(),
                        volume_per_month=int(row["volume_per_month"]),
                        current_cost_per_item=Decimal(row["current_cost_per_item"]),
                        cost_of_error=None if unbounded else Decimal(raw_cost),
                        client_quote=quote,
                        unbounded_error=unbounded,
                    )
                )
            except (InvalidOperation, ValueError) as exc:
                raise ValueError(f"line {line}: {exc}") from exc
    return intents
```

- [ ] **Step 4: Write `docs/triage-intake-template.csv`**

```csv
intent,volume_per_month,current_cost_per_item,cost_of_error,client_quote
invoice_total,4000,2.50,40.00,"About forty dollars of rework each time we get it wrong"
bank_detail_change,20,1.00,unbounded,"If we pay the wrong account we may never recover it"
```

This is what you send the client before the cost-of-error interview.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/triage/test_ingest.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/triage/ docs/triage-intake-template.csv tests/triage/
git commit -m "feat: triage intake requiring the client's own cost-of-error quote"
```

---

### Task 19: `triage/expected_value.py`

**Files:**
- Create: `ground_truth/triage/expected_value.py`
- Test: `tests/triage/test_expected_value.py`

**Interfaces:**
- Consumes: `triage.ingest.Intent`, `stats.bootstrap.Interval`.
- Produces: `Recommendation` (`StrEnum`: `AUTOMATE`, `ROUTE_TO_HUMAN`, `NEVER_AUTOMATE`, `INSUFFICIENT_EVIDENCE`); `EVResult(intent: str, ev_low: Decimal, ev_point: Decimal, ev_high: Decimal, recommendation: Recommendation, n: int, rationale: str)` (frozen); `evaluate(intent: Intent, accuracy: Interval, automation_cost_per_item: Decimal) -> EVResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_expected_value.py
from decimal import Decimal

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import Recommendation, evaluate
from ground_truth.triage.ingest import Intent


def intent(**over) -> Intent:
    base = dict(intent="invoice_total", volume_per_month=1000,
                current_cost_per_item=Decimal("2.00"), cost_of_error=Decimal("4.00"),
                client_quote="four dollars of rework", unbounded_error=False)
    return Intent(**(base | over))


def acc(point, low, high, n=180) -> Interval:
    return Interval(point=point, low=low, high=high, n=n, method="cluster-BCa")


def test_ev_is_an_interval_derived_from_the_accuracy_interval():
    r = evaluate(intent(), acc(0.92, 0.89, 0.95), Decimal("0.10"))
    assert r.ev_low < r.ev_point < r.ev_high


def test_high_accuracy_low_cost_of_error_automates():
    r = evaluate(intent(), acc(0.92, 0.90, 0.94), Decimal("0.10"))
    assert r.recommendation is Recommendation.AUTOMATE


def test_high_accuracy_high_cost_of_error_routes_to_human():
    r = evaluate(intent(cost_of_error=Decimal("40000")), acc(0.97, 0.95, 0.99), Decimal("0.10"))
    assert r.recommendation is Recommendation.ROUTE_TO_HUMAN


def test_unbounded_error_never_automates_regardless_of_ev():
    r = evaluate(intent(cost_of_error=None, unbounded_error=True),
                 acc(0.999, 0.998, 1.0), Decimal("0.01"))
    assert r.recommendation is Recommendation.NEVER_AUTOMATE


def test_ev_interval_spanning_zero_is_insufficient_evidence():
    r = evaluate(intent(cost_of_error=Decimal("25")), acc(0.90, 0.75, 0.99, n=40), Decimal("0.10"))
    assert r.recommendation is Recommendation.INSUFFICIENT_EVIDENCE
    assert "n=40" in r.rationale


def test_rationale_always_states_n():
    assert "n=180" in evaluate(intent(), acc(0.92, 0.90, 0.94), Decimal("0.10")).rationale


def test_unbounded_rationale_quotes_the_client():
    r = evaluate(intent(cost_of_error=None, unbounded_error=True,
                        client_quote="we may never recover it"),
                 acc(0.99, 0.98, 1.0), Decimal("0.01"))
    assert "we may never recover it" in r.rationale


def test_no_float_in_the_money_path():
    import inspect

    from ground_truth.triage import expected_value

    assert "float(" not in inspect.getsource(expected_value)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/triage/test_expected_value.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/triage/expected_value.py`**

```python
from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.ingest import Intent


class Recommendation(StrEnum):
    AUTOMATE = "automate"
    ROUTE_TO_HUMAN = "route_to_human"
    NEVER_AUTOMATE = "never_automate"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class EVResult(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    intent: str
    ev_low: Decimal
    ev_point: Decimal
    ev_high: Decimal
    recommendation: Recommendation
    n: int
    rationale: str


def _ev(intent: Intent, accuracy: Decimal, automation_cost_per_item: Decimal) -> Decimal:
    saving = intent.current_cost_per_item - automation_cost_per_item
    cost_of_error = intent.cost_of_error or Decimal(0)
    per_item = accuracy * saving - (Decimal(1) - accuracy) * cost_of_error
    return (Decimal(intent.volume_per_month) * per_item).quantize(Decimal("0.01"))


def evaluate(intent: Intent, accuracy: Interval, automation_cost_per_item: Decimal) -> EVResult:
    ev_low = _ev(intent, Decimal(str(accuracy.low)), automation_cost_per_item)
    ev_point = _ev(intent, Decimal(str(accuracy.point)), automation_cost_per_item)
    ev_high = _ev(intent, Decimal(str(accuracy.high)), automation_cost_per_item)

    if intent.unbounded_error:
        recommendation = Recommendation.NEVER_AUTOMATE
        rationale = (
            f"Cost of error is unbounded in the client's own words: {intent.client_quote!r}. "
            f"No accuracy justifies automation when the downside has no ceiling (n={accuracy.n})."
        )
    elif ev_low > 0:
        recommendation = Recommendation.AUTOMATE
        rationale = (
            f"Expected value is positive across the whole accuracy interval "
            f"[{accuracy.low:.3f}, {accuracy.high:.3f}] at n={accuracy.n}."
        )
    elif ev_high < 0:
        recommendation = Recommendation.ROUTE_TO_HUMAN
        rationale = (
            f"Expected value is negative across the whole accuracy interval "
            f"[{accuracy.low:.3f}, {accuracy.high:.3f}] at n={accuracy.n}."
        )
    else:
        recommendation = Recommendation.INSUFFICIENT_EVIDENCE
        rationale = (
            f"Expected value spans zero: [{ev_low}, {ev_high}] per month at n={accuracy.n}. "
            f"This does not yet support a decision. A larger sample would narrow it."
        )
    return EVResult(
        intent=intent.intent, ev_low=ev_low, ev_point=ev_point, ev_high=ev_high,
        recommendation=recommendation, n=accuracy.n, rationale=rationale,
    )
```

`INSUFFICIENT_EVIDENCE` is a first-class outcome, not an error state. A triage report that returns it for three of ten intents is doing its job.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/triage/test_expected_value.py -v`
Expected: PASS, 8 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/triage/expected_value.py tests/triage/test_expected_value.py
git commit -m "feat: interval-valued expected value with insufficient-evidence outcome"
```

---

### Task 20: `triage/sensitivity.py` — the flip point

**Files:**
- Create: `ground_truth/triage/sensitivity.py`
- Test: `tests/triage/test_sensitivity.py`

**Interfaces:**
- Consumes: `triage.expected_value.{evaluate, Recommendation}`, `triage.ingest.Intent`, `stats.bootstrap.Interval`.
- Produces: `FlipPoint(intent: str, flips_at: Decimal | None, from_rec: Recommendation, to_rec: Recommendation | None, sentence: str)` (frozen); `sweep(intent, accuracy, automation_cost_per_item, *, ceiling: Decimal, steps: int = 200) -> list[tuple[Decimal, Recommendation]]`; `find_flip_point(intent, accuracy, automation_cost_per_item, *, ceiling: Decimal, steps: int = 200) -> FlipPoint`.

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_sensitivity.py
from decimal import Decimal

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import Recommendation, evaluate
from ground_truth.triage.ingest import Intent
from ground_truth.triage.sensitivity import find_flip_point, sweep

ACC = Interval(point=0.92, low=0.905, high=0.935, n=180, method="cluster-BCa")
AUTO_COST = Decimal("0.10")


def intent(cost: str) -> Intent:
    return Intent(intent="invoice_total", volume_per_month=1000,
                  current_cost_per_item=Decimal("2.00"), cost_of_error=Decimal(cost),
                  client_quote="the client's own words", unbounded_error=False)


def test_flip_point_actually_flips_the_recommendation():
    fp = find_flip_point(intent("4.00"), ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert fp.flips_at is not None
    below = evaluate(intent(str(fp.flips_at - Decimal("1.00"))), ACC, AUTO_COST).recommendation
    above = evaluate(intent(str(fp.flips_at + Decimal("1.00"))), ACC, AUTO_COST).recommendation
    assert below != above, "the reported flip point must be a real boundary"


def test_sentence_is_in_the_clients_units():
    fp = find_flip_point(intent("4.00"), ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert "$" in fp.sentence and str(fp.flips_at) in fp.sentence


def test_sentence_quotes_the_client():
    fp = find_flip_point(intent("4.00"), ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert "the client's own words" in fp.sentence


def test_no_flip_within_ceiling_is_reported_as_none():
    fp = find_flip_point(intent("0.01"), ACC, AUTO_COST, ceiling=Decimal("0.02"), steps=4)
    assert fp.flips_at is None and "does not flip" in fp.sentence


def test_sweep_is_monotone_towards_route_to_human():
    rows = sweep(intent("4.00"), ACC, AUTO_COST, ceiling=Decimal("500"), steps=50)
    ranks = {Recommendation.AUTOMATE: 0, Recommendation.INSUFFICIENT_EVIDENCE: 1,
             Recommendation.ROUTE_TO_HUMAN: 2}
    values = [ranks[r] for _, r in rows]
    assert values == sorted(values), "raising cost of error can never make automation more attractive"


def test_unbounded_intent_never_flips():
    unbounded = Intent(intent="bank", volume_per_month=10, current_cost_per_item=Decimal("1"),
                       cost_of_error=None, client_quote="q", unbounded_error=True)
    fp = find_flip_point(unbounded, ACC, AUTO_COST, ceiling=Decimal("1000"))
    assert fp.flips_at is None and fp.from_rec is Recommendation.NEVER_AUTOMATE
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/triage/test_sensitivity.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write `ground_truth/triage/sensitivity.py`**

`sweep` walks `cost_of_error` from `Decimal("0")` to `ceiling` in `steps` equal increments (each quantised to `Decimal("0.01")`), rebuilding the `Intent` with `model_copy(update={"cost_of_error": value})` and calling `evaluate` at each point. For an `unbounded_error` intent it returns a single row at the stated cost with `NEVER_AUTOMATE`.

`find_flip_point` takes the recommendation at cost zero as `from_rec` and returns the **first** cost whose recommendation differs, as `flips_at` and `to_rec`, composing:

```
f"This becomes {to_rec.value.replace('_', ' ')} if a wrong extraction costs more than "
f"${flips_at}. The client's stated cost of error is ${intent.cost_of_error}, in their "
f"words: {intent.client_quote!r}."
```

When no flip occurs inside `ceiling`, or the intent is `unbounded_error`, `flips_at` and `to_rec` are `None` and the sentence contains `"does not flip"` plus the range examined.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/triage/test_sensitivity.py -v`
Expected: PASS, 6 passed.

- [ ] **Step 5: Commit**

```bash
git add ground_truth/triage/sensitivity.py tests/triage/test_sensitivity.py
git commit -m "feat: cost-of-error sensitivity sweep with verified flip point"
```

---

### Task 21: `triage/report.py` — the print-ready deliverable

**Files:**
- Create: `ground_truth/triage/report.py`
- Create: `ground_truth/triage/templates/report.html.j2`
- Create: `ground_truth/triage/templates/report.css`
- Test: `tests/triage/test_report.py`

**Interfaces:**
- Consumes: `triage.expected_value.EVResult`, `triage.sensitivity.FlipPoint`, `triage.ingest.Intent`, `stats.bootstrap.Interval`, `stats.mde.describe_mde`.
- Produces: `ReportRow(intent: Intent, ev: EVResult, flip: FlipPoint, accuracy: Interval)` (frozen); `render_report(rows: list[ReportRow], *, generated_at: datetime, methodology_url: str) -> str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/triage/test_report.py
from datetime import UTC, datetime
from decimal import Decimal

from ground_truth.stats.bootstrap import Interval
from ground_truth.triage.expected_value import evaluate
from ground_truth.triage.ingest import Intent
from ground_truth.triage.report import ReportRow, render_report
from ground_truth.triage.sensitivity import find_flip_point

ACC = Interval(point=0.92, low=0.905, high=0.935, n=40, method="cluster-BCa")
AUTO = Decimal("0.10")


def row() -> ReportRow:
    intent = Intent(intent="invoice_total", volume_per_month=1000,
                    current_cost_per_item=Decimal("2.00"), cost_of_error=Decimal("4.00"),
                    client_quote="about four dollars of rework each time", unbounded_error=False)
    return ReportRow(intent=intent, ev=evaluate(intent, ACC, AUTO),
                     flip=find_flip_point(intent, ACC, AUTO, ceiling=Decimal("1000")), accuracy=ACC)


def html() -> str:
    return render_report([row()], generated_at=datetime(2026, 9, 15, tzinfo=UTC),
                         methodology_url="https://example.invalid/methodology")


def test_every_number_carries_its_sample_size():
    assert "n=40" in html()


def test_interval_is_rendered_as_an_interval():
    body = html()
    assert "0.905" in body and "0.935" in body


def test_client_quote_appears_verbatim():
    assert "about four dollars of rework each time" in html()


def test_flip_point_sentence_is_present():
    assert "if a wrong extraction costs more than" in html()


def test_mde_caveat_is_present():
    assert "not that none exists" in html()


def test_methodology_link_is_present():
    assert "https://example.invalid/methodology" in html()


def test_print_stylesheet_is_inlined():
    body = html()
    assert "@media print" in body and "<link" not in body


def test_report_states_the_generation_date():
    assert "2026-09-15" in html()


def test_empty_rows_render_an_empty_state_not_a_crash():
    body = render_report([], generated_at=datetime(2026, 9, 15, tzinfo=UTC),
                         methodology_url="https://example.invalid/methodology")
    assert "no intents" in body.lower()
```

`test_print_stylesheet_is_inlined` matters because this document gets emailed and printed. An external stylesheet reference produces an unstyled page in a client's inbox.

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/triage/test_report.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the template, the stylesheet, and `report.py`**

`report.html.j2` renders, in order: a title block with the generation date and a methodology link **beside the title, not in a footer**; a summary table with columns `intent | volume/month | accuracy [low, high] n | EV [low, high] | recommendation`; then one section per intent showing the EV formula with the actual numbers substituted, the client's quote as a pull-quote, the flip-point sentence, and the `describe_mde` caveat. When `rows` is empty it renders an empty state reading *"No intents supplied — nothing has been measured yet."*

`report.css` uses `font-variant-numeric: tabular-nums` on every numeric cell and includes an `@media print` block that forces a page break between intent sections and removes link chrome. `report.py` reads `report.css` at render time and injects it into a `<style>` block — never a `<link>`. It also exposes `if __name__ == "__main__":` accepting `--intake`, `--out`, and `--methodology-url`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/triage/test_report.py -v`
Expected: PASS, 9 passed.

- [ ] **Step 5: Render a real report and read it as the client would**

```bash
uv run python -m ground_truth.triage.report \
  --intake docs/triage-intake-template.csv \
  --out /tmp/triage.html \
  --methodology-url https://example.invalid/methodology
```

Open it in a browser, print to PDF, and read the PDF. If any number appears without its `n`, or any recommendation appears without its flip point, fix it now — this is the artifact you are selling.

- [ ] **Step 6: Commit**

```bash
git add ground_truth/triage/report.py ground_truth/triage/templates/ tests/triage/test_report.py
git commit -m "feat: print-ready triage report with intervals, quotes, and flip points"
```

---

### Task 22: Phase-2 grading pass, degraded mode, and the phase-1 gate

**Files:**
- Create: `ground_truth/grade.py`
- Test: `tests/test_degraded_mode.py`
- Test: `tests/test_phase1_e2e.py`

**Interfaces:**
- Consumes: every deterministic grader, `store.db`, `golden.schema.Item`, `golden.rubric.RubricRule`.
- Produces: `grade_stored_outputs(con, items: list[Item], rubric: dict[FieldType, RubricRule]) -> int` returning the number of verdict rows written.

- [ ] **Step 1: Write the failing degraded-mode test**

```python
# tests/test_degraded_mode.py
from pathlib import Path

import pytest

from ground_truth._bok_shim import CallContext, assert_blackout_complete, blackout
from ground_truth.golden.generate import generate
from ground_truth.golden.rubric import loaded_rubric
from ground_truth.grade import grade_stored_outputs
from ground_truth.runner import execute_sweep
from ground_truth.store.db import connect, migrate
from tests.test_runner import FakeGateway

RUBRIC = Path(__file__).resolve().parents[1] / "docs" / "rubric.md"


@pytest.fixture()
def populated(tmp_path):
    con = connect(tmp_path / "t.duckdb")
    migrate(con)
    items = generate(count=10, seed=1, rubric_version="v1")
    gw = FakeGateway()
    execute_sweep(con, items, ["slot-a"], replicates=5, context=CallContext(),
                  resolve_fn=gw.resolve, call_fn=gw.call)
    yield con, items
    con.close()


def test_degraded_mode_still_produces_findings(populated):
    """Ground Truth's declared floor is ZERO gateway calls in phase 2, not a percentage.

    blackout() makes every lane raise, and defeats the response cache, the probe TTL cache
    and the fallback chain -- so a code path that quietly reached a provider cannot hide.
    assert_blackout_complete() then confirms none did.
    """
    con, items = populated
    with blackout():
        written = grade_stored_outputs(con, items, loaded_rubric(RUBRIC))
        assert_blackout_complete()
    assert written > 0, "phase 2 must produce verdicts with every provider disabled"


def test_grading_never_appends_to_outputs(populated):
    con, items = populated
    before = con.execute("SELECT count(*) FROM outputs").fetchone()[0]
    grade_stored_outputs(con, items, loaded_rubric(RUBRIC))
    after = con.execute("SELECT count(*) FROM outputs").fetchone()[0]
    assert before == after, "phase 2 must never append to the immutable outputs table"


def test_regrading_at_the_same_version_is_idempotent(populated):
    con, items = populated
    rubric = loaded_rubric(RUBRIC)
    grade_stored_outputs(con, items, rubric)
    first = con.execute("SELECT count(*) FROM verdicts").fetchone()[0]
    grade_stored_outputs(con, items, rubric)
    assert con.execute("SELECT count(*) FROM verdicts").fetchone()[0] == first


def test_grade_module_imports_no_provider_code():
    import inspect

    from ground_truth import grade

    source = inspect.getsource(grade)
    assert "_bok_shim" not in source and "from ground_truth.runner" not in source
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_degraded_mode.py -v`
Expected: FAIL — `ImportError: cannot import name 'blackout' from 'ground_truth._bok_shim'`.

- [ ] **Step 2b: Extend `_bok_shim.py` with the degraded-mode helpers**

Mirroring `INTERFACE-CONTRACT.md` §5, so the import swaps to `bok_core.testing.degraded` unchanged:

```python
_BLACKOUT = ContextVar("bok_blackout", default=False)
_BREACHES: list[str] = []


@contextmanager
def blackout() -> Iterator[None]:
    """Every lane raises ProvidersUnavailable. Defeats the response cache, the probe
    TTL cache, the fallback chain, and any local-fallback that is not deterministic."""
    token = _BLACKOUT.set(True)
    _BREACHES.clear()
    try:
        yield
    finally:
        _BLACKOUT.reset(token)


def assert_blackout_complete() -> None:
    """Asserts no code path reached a provider under blackout. THE shared test."""
    assert _BREACHES == [], f"code reached a provider under blackout: {_BREACHES}"
```

Then have the shim's `call()` record into `_BREACHES` and raise `ProvidersUnavailable` when `_BLACKOUT.get()` is true. A blackout that only makes calls *fail* proves nothing — it must record that a call was *attempted*, or a caught-and-swallowed exception would pass the test.

- [ ] **Step 3: Write `ground_truth/grade.py`**

For every row in `outputs`: call `grade_schema(item, raw_output)` and write that verdict. If the schema verdict is correct, call `extract_fields(raw_output)` and, for each `ItemField`, dispatch on `rubric[field.field_type].grader` with an explicit chain:

```python
if grader_name == "exact":
    verdict = grade_exact(field, observed.get(field.field_name), rule)
elif grader_name == "numeric_tolerance":
    verdict = grade_numeric_tolerance(field, observed.get(field.field_name), rule)
elif grader_name == "normalised":
    verdict = grade_normalised(field, observed.get(field.field_name), rule)
elif grader_name == "judge":
    continue          # phase 2 of the judge lands in Plan 2, Task 25
else:
    raise ValueError(f"rubric declares unknown grader {grader_name!r}")
```

Not a lookup table — `test_no_module_scope_callable_registry` forbids one, and four branches read more clearly than an indirection. Then call `grade_arithmetic(item, observed, tolerance)` once per output and write it under `field_name="__arithmetic__"`.

Insert with `INSERT OR IGNORE`, so the `UNIQUE (output_id, field_name, grader_id, grader_version, rubric_version)` constraint makes re-grading idempotent. Import nothing from `runner.py` and nothing from `_bok_shim.py`.

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_degraded_mode.py -v`
Expected: PASS, 4 passed.

- [ ] **Step 5: Write the phase-1 end-to-end test**

```python
# tests/test_phase1_e2e.py
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from ground_truth.stats.bootstrap import cluster_bootstrap_ci
from ground_truth.stats.mde import describe_mde
from ground_truth.triage.expected_value import evaluate
from ground_truth.triage.ingest import load_intents
from ground_truth.triage.report import ReportRow, render_report
from ground_truth.triage.sensitivity import find_flip_point

INTAKE = Path(__file__).resolve().parents[1] / "docs" / "triage-intake-template.csv"


def test_intake_to_report_produces_a_sellable_artifact(tmp_path):
    intents = load_intents(INTAKE)
    assert intents, "the intake template must contain at least one example row"
    accuracy = cluster_bootstrap_ci(
        [(f"i{i}", i % 10 != 0) for i in range(40)], seed=1, n_resamples=500
    )
    rows = [
        ReportRow(
            intent=intent,
            ev=evaluate(intent, accuracy, Decimal("0.10")),
            flip=find_flip_point(intent, accuracy, Decimal("0.10"), ceiling=Decimal("10000")),
            accuracy=accuracy,
        )
        for intent in intents
    ]
    html = render_report(rows, generated_at=datetime(2026, 9, 15, tzinfo=UTC),
                         methodology_url="https://example.invalid/methodology")
    assert f"n={accuracy.n}" in html
    assert describe_mde(accuracy.n, 0.10, n_comparisons=1) is not None
    assert "never automate" in html.lower(), "the unbounded-error row must be visible as such"
    (tmp_path / "triage.html").write_text(html, encoding="utf-8")
```

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -v`
Expected: all pass, coverage ≥ 75%.

- [ ] **Step 7: Run the complete gate**

Run: `uv run ruff check . && uv run ruff format --check . && uv run mypy && uv run pytest -v`
Expected: all four pass.

- [ ] **Step 8: Commit and tag the phase**

```bash
git add ground_truth/grade.py tests/test_degraded_mode.py tests/test_phase1_e2e.py
git commit -m "feat: phase-2 grading pass, degraded mode, and phase-1 end-to-end"
git tag -a phase-1-triage -m "Phase 1: harness spine and sellable triage report"
```

---

## Phase 1 exit criteria

All of these must hold before starting Phase 2:

- [ ] `uv run pytest -v` passes with coverage ≥ 75%.
- [ ] `uv run mypy` passes under `--strict`.
- [ ] `git log --format='%H %ad %s' --date=iso -- docs/rubric.md` shows a commit **earlier** than any commit touching `golden/manifest_public.json`. This is the evidence spec §5.2 depends on — verify it, do not assume it.
- [ ] `git status --porcelain golden/corpus/private/` prints nothing.
- [ ] `git ls-files .env` prints nothing.
- [ ] `docs/providers.md` records all audit columns for every configured slot, each with a verbatim terms quote and a retrieval date.
- [ ] A rendered triage report has been printed to PDF and read end to end.
- [ ] `tests/test_non_goals.py` has been observed **failing** at least once against a deliberately planted registry, then passing after reverting.

**Definition-of-done items satisfied by this phase:** `04` §12 items **1**, **2** (splits and code enforcement; publication lands in Phase 3), **3**, and **8**.

Items 4–7 and 9–11 belong to Phases 2 and 3.
