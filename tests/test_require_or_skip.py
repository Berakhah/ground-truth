# tests/test_require_or_skip.py
import pytest

from tests.conftest import require_or_skip


def test_prerequisite_met_does_nothing(monkeypatch):
    monkeypatch.setenv("GT_REQUIRE_DB", "1")
    require_or_skip(True, "unreachable")


def test_missing_prerequisite_skips_without_gt_require_db(monkeypatch):
    monkeypatch.delenv("GT_REQUIRE_DB", raising=False)
    with pytest.raises(pytest.skip.Exception):
        require_or_skip(False, "run the sweep first")


def test_missing_prerequisite_fails_under_gt_require_db(monkeypatch):
    monkeypatch.setenv("GT_REQUIRE_DB", "1")
    with pytest.raises(pytest.fail.Exception):
        require_or_skip(False, "run the sweep first")
