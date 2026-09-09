# tests/test_reproducibility.py
import filecmp
import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ground_truth.publish.artifacts import emit_all
from ground_truth.store.db import connect
from tests.conftest import require_or_skip

REPO = Path(__file__).resolve().parents[1]
DB = REPO / "data" / "results.duckdb"
PUBLISHED = REPO / "artifacts"
AS_OF = datetime(2026, 10, 15, tzinfo=UTC)


def _only_placeholder_published() -> bool:
    leaderboard_path = PUBLISHED / "leaderboard.json"
    if not leaderboard_path.exists():
        return False
    return json.loads(leaderboard_path.read_text(encoding="utf-8")).get("placeholder") is True


@pytest.fixture()
def con():
    require_or_skip(DB.exists() and PUBLISHED.exists(), "run the sweep and publish first")
    require_or_skip(
        not _only_placeholder_published(),
        "only placeholder/demo data is published; run the sweep and publish for real",
    )
    c = connect(DB)
    yield c
    c.close()


def test_published_numbers_regenerate(con, tmp_path):
    mismatched = []
    for path in emit_all(con, tmp_path, as_of=AS_OF, analysis_seed=1):
        published = PUBLISHED / path.name
        assert published.exists(), f"{path.name} was regenerated but is not published"
        if not filecmp.cmp(path, published, shallow=False):
            mismatched.append(path.name)
    assert mismatched == [], f"published artifacts do not regenerate: {mismatched}"


def test_regeneration_is_stable_across_two_runs(con, tmp_path):
    first = sorted(emit_all(con, tmp_path / "a", as_of=AS_OF, analysis_seed=1))
    second = sorted(emit_all(con, tmp_path / "b", as_of=AS_OF, analysis_seed=1))
    for a, b in zip(first, second, strict=True):
        assert filecmp.cmp(a, b, shallow=False), f"{a.name} is not deterministic"


def test_headline_accuracy_recomputes_from_published_verdicts_alone():
    """A stranger holding only the published verdict files must reach the published number."""
    require_or_skip(PUBLISHED.exists(), "run the sweep and publish first")
    require_or_skip(
        not _only_placeholder_published(),
        "only placeholder/demo data is published; run the sweep and publish for real",
    )
    leaderboard = json.loads((PUBLISHED / "leaderboard.json").read_text(encoding="utf-8"))
    verdicts = [
        json.loads(line)
        for line in (PUBLISHED / "verdicts_private_by_hash.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]
    for entry in leaderboard["rows"]:
        rows = [v for v in verdicts if v["slot"] == entry["slot"]]
        by_item: dict[str, list[bool]] = {}
        for v in rows:
            by_item.setdefault(v["content_hash"], []).append(v["correct"])
        recomputed = sum(sum(c) / len(c) for c in by_item.values()) / len(by_item)
        assert recomputed == pytest.approx(entry["accuracy"]["point"], abs=1e-9), (
            f"{entry['slot']}: published {entry['accuracy']['point']}, recomputed {recomputed}"
        )
