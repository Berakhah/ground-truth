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
