"""Regression tests for the project's custom gitleaks rules.

The default gitleaks ruleset (used by the `gitleaks` pre-commit hook, `00` SS3.4) does not
recognise this project's own environment-variable names -- `GT_PRIVATE_SEED` and
`GT_HASH_SALT` -- as secret-like, so a real value assigned to either could be committed
without tripping the hook. `.gitleaks.toml` at the repo root adds a custom rule for exactly
these two env-var-name patterns.

These tests do not shell out to the `gitleaks` binary (it is a Go binary, not a Python
dependency, and may not be installed on every dev machine or CI runner that still needs to run
the test suite -- 00 SS3's `uv sync` alone must be enough). Instead they load the same regex
straight out of `.gitleaks.toml` -- so the rule and the test can never silently drift apart --
and apply it directly, first proving the rule fires on a synthetic value (TDD's positive case)
and then proving no *real* tracked file in this repository ever matches it.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"

# Files that are allowed to contain the *name* GT_PRIVATE_SEED / GT_HASH_SALT next to a
# placeholder value -- never a real secret value. `.env.example` ships the real, already-
# published GT_PUBLIC_SEED plus obvious "change-me" placeholders for the two that must never
# be committed; that placeholder text is not itself a plausible secret value, but it is
# excluded explicitly so this test's intent (no *real* seed value anywhere) stays legible.
ALLOWED_PATHS = {".env.example"}


def _load_seed_rules() -> list[re.Pattern[str]]:
    config = tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))
    rules = config.get("rules", [])
    seed_rules = [r for r in rules if "gt-" in r.get("id", "")]
    assert seed_rules, ".gitleaks.toml must define at least one GT_*_SEED / GT_HASH_SALT rule"
    return [re.compile(r["regex"]) for r in seed_rules]


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / line for line in out.splitlines() if line.strip()]


def test_custom_rule_flags_a_synthetic_seed_value() -> None:
    """Positive case: the rule must actually fire on a plausible leaked value."""
    patterns = _load_seed_rules()
    synthetic_leaks = [
        'GT_PRIVATE_SEED="9f8a1c2d3e4b5a6978869504a1b2c3d4"',
        "GT_HASH_SALT=9f8a1c2d3e4b5a6978869504a1b2c3d4",
        "export GT_PRIVATE_SEED=abcdef0123456789abcdef0123456789",
    ]
    for leak in synthetic_leaks:
        assert any(p.search(leak) for p in patterns), (
            f"no gitleaks rule in .gitleaks.toml matched the synthetic leak: {leak!r}"
        )


def test_custom_rule_does_not_flag_the_committed_placeholder() -> None:
    """The placeholder in .env.example ('change-me-and-never-commit-this') must not itself
    look like a real secret value -- otherwise every fresh checkout would fail its own gate."""
    patterns = _load_seed_rules()
    placeholder_lines = [
        "GT_PRIVATE_SEED=change-me-and-never-commit-this",
        "GT_HASH_SALT=change-me-and-never-commit-this",
    ]
    for line in placeholder_lines:
        assert not any(p.search(line) for p in patterns), (
            f"a rule matched the checked-in placeholder, would fail a fresh clone: {line!r}"
        )


def test_no_seed_value_in_any_tracked_file() -> None:
    """No file actually committed to this repository may contain a real GT_PRIVATE_SEED or
    GT_HASH_SALT value -- the regression test behind `.gitleaks.toml`'s custom rule,
    independent of whether the pre-commit hook itself ran."""
    patterns = _load_seed_rules()
    offending: list[str] = []
    for path in _tracked_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED_PATHS or rel == GITLEAKS_CONFIG.name or rel.startswith("tests/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable file -- not a plausible place for a pasted env line
        for pattern in patterns:
            if pattern.search(text):
                offending.append(f"{rel}: matched {pattern.pattern!r}")
    assert not offending, "possible committed secret value(s):\n" + "\n".join(offending)
