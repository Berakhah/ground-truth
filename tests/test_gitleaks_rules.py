"""Regression tests for the project's custom gitleaks rules.

The default gitleaks ruleset (used by the `gitleaks` pre-commit hook, `00` SS3.4) does not
recognise this project's own environment-variable names -- `GT_PRIVATE_SEED` and
`GT_HASH_SALT` -- as secret-like, so a real value assigned to either could be committed
without tripping the hook. `.gitleaks.toml` at the repo root adds two custom rules for exactly
these env-var-name patterns.

These tests do not shell out to the `gitleaks` binary (it is a Go binary, not a Python
dependency, and may not be installed on every dev machine or CI runner that still needs to run
the test suite -- 00 SS3's `uv sync` alone must be enough). Instead they load the same rules
straight out of `.gitleaks.toml` -- both each rule's main `regex` AND its `[[rules.allowlists]]`
line-target exclusions -- so the rule and the test can never silently drift apart, and apply
them the way gitleaks itself does: per line, with a rule's own allowlist able to veto a match
on that same line. This cannot substitute for actually running the real `gitleaks` binary
(RE2, not Python's `re`), but every regex in `.gitleaks.toml` is written to avoid
lookahead/lookbehind/backreferences specifically because RE2 does not support them -- see that
file's header comment.
"""

from __future__ import annotations

import re
import subprocess
import tomllib
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GITLEAKS_CONFIG = REPO_ROOT / ".gitleaks.toml"

# Files that are allowed to contain the *name* GT_PRIVATE_SEED / GT_HASH_SALT next to a
# placeholder value -- never a real secret value. `.env.example` ships the real, already-
# published GT_PUBLIC_SEED plus obvious "change-me" placeholders for the two that must never
# be committed; that placeholder text is not itself a plausible secret value, but it is
# excluded explicitly so this test's intent (no *real* seed value anywhere) stays legible.
ALLOWED_PATHS = {".env.example"}


@dataclass(frozen=True)
class _SeedRule:
    id: str
    regex: re.Pattern[str]
    # gitleaks' own per-rule `[[rules.allowlists]]` with regexTarget = "line": a match on the
    # SAME line as the rule's own match is not reported. RE2 has no lookahead to do this
    # inline, so gitleaks does it as a separate exclusion pass -- mirrored here rather than
    # folded into `regex` itself.
    line_allowlist: list[re.Pattern[str]]

    def matches(self, text: str) -> bool:
        for line in text.splitlines():
            if self.regex.search(line) and not any(a.search(line) for a in self.line_allowlist):
                return True
        return False


def _load_seed_rules() -> list[_SeedRule]:
    config = tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))
    rules = config.get("rules", [])
    seed_rules = [r for r in rules if "gt-" in r.get("id", "")]
    assert seed_rules, ".gitleaks.toml must define at least one GT_*_SEED / GT_HASH_SALT rule"
    loaded: list[_SeedRule] = []
    for r in seed_rules:
        line_allow = [
            re.compile(pattern)
            for allowlist in r.get("allowlists", [])
            if allowlist.get("regexTarget") == "line"
            for pattern in allowlist.get("regexes", [])
        ]
        loaded.append(
            _SeedRule(id=r["id"], regex=re.compile(r["regex"]), line_allowlist=line_allow)
        )
    return loaded


def _no_lookaround_or_backreferences(pattern: str) -> bool:
    """RE2 (gitleaks' engine) supports none of these constructs at all -- a regex using one
    of them may fail to even compile under the real gitleaks binary, which this project's
    sandbox does not have installed to check directly (see .gitleaks.toml's header)."""
    forbidden = ("(?!", "(?<!", "(?=", "(?<=", r"\1", r"\2", r"\3")
    return not any(token in pattern for token in forbidden)


def _tracked_files() -> list[Path]:
    out = subprocess.run(
        ["git", "ls-files"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [REPO_ROOT / line for line in out.splitlines() if line.strip()]


def test_every_regex_avoids_re2_unsupported_syntax() -> None:
    """gitleaks is a Go binary using RE2, which has no lookahead, lookbehind, or
    backreference support at all -- unlike this rule under test earlier in Task 52's review,
    which used `(?!...)` and passed here only because Python's `re` (unlike RE2) accepts it."""
    config = tomllib.loads(GITLEAKS_CONFIG.read_text(encoding="utf-8"))
    checked = 0
    for rule in config.get("rules", []):
        if "gt-" not in rule.get("id", ""):
            continue
        assert _no_lookaround_or_backreferences(rule["regex"]), (
            f"{rule['id']}: regex uses RE2-unsupported syntax: {rule['regex']!r}"
        )
        checked += 1
        for allowlist in rule.get("allowlists", []):
            for pattern in allowlist.get("regexes", []):
                assert _no_lookaround_or_backreferences(pattern), (
                    f"{rule['id']}: allowlist regex uses RE2-unsupported syntax: {pattern!r}"
                )
    expected_rule_count = 2  # gt-seed, gt-hash-salt
    assert checked >= expected_rule_count, "expected both GT_*_SEED rules to be checked"


def test_custom_rules_flag_a_synthetic_seed_value() -> None:
    """Positive case: each rule must actually fire on a plausible leaked value."""
    rules = _load_seed_rules()
    synthetic_leaks = [
        'GT_PRIVATE_SEED="9f8a1c2d3e4b5a6978869504a1b2c3d4"',
        "GT_HASH_SALT=9f8a1c2d3e4b5a6978869504a1b2c3d4",
        "export GT_PRIVATE_SEED=abcdef0123456789abcdef0123456789",
    ]
    for leak in synthetic_leaks:
        assert any(rule.matches(leak) for rule in rules), (
            f"no gitleaks rule in .gitleaks.toml matched the synthetic leak: {leak!r}"
        )


def test_gt_public_seed_is_allowlisted_even_with_a_real_looking_value() -> None:
    """GT_PUBLIC_SEED is intentionally published (docs/methodology.md, .env.example) and must
    never be flagged, however real-looking its value is -- this is the gt-seed rule's
    `[[rules.allowlists]]` line-target exclusion doing its job."""
    rules = _load_seed_rules()
    line = "GT_PUBLIC_SEED=32611816645452341011091101610726"
    assert not any(rule.matches(line) for rule in rules), (
        f"a rule flagged the intentionally-public GT_PUBLIC_SEED value: {line!r}"
    )


def test_custom_rules_do_not_flag_the_committed_placeholder() -> None:
    """The placeholder in .env.example ('change-me-and-never-commit-this') must not itself
    look like a real secret value -- otherwise every fresh checkout would fail its own gate."""
    rules = _load_seed_rules()
    placeholder_lines = [
        "GT_PRIVATE_SEED=change-me-and-never-commit-this",
        "GT_HASH_SALT=change-me-and-never-commit-this",
    ]
    for line in placeholder_lines:
        assert not any(rule.matches(line) for rule in rules), (
            f"a rule matched the checked-in placeholder, would fail a fresh clone: {line!r}"
        )


def test_no_seed_value_in_any_tracked_file() -> None:
    """No file actually committed to this repository may contain a real GT_PRIVATE_SEED or
    GT_HASH_SALT value -- the regression test behind `.gitleaks.toml`'s custom rules,
    independent of whether the pre-commit hook itself ran."""
    rules = _load_seed_rules()
    offending: list[str] = []
    for path in _tracked_files():
        rel = path.relative_to(REPO_ROOT).as_posix()
        if rel in ALLOWED_PATHS or rel == GITLEAKS_CONFIG.name or rel.startswith("tests/"):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # binary or unreadable file -- not a plausible place for a pasted env line
        for rule in rules:
            if rule.matches(text):
                offending.append(f"{rel}: matched rule {rule.id!r}")
    assert not offending, "possible committed secret value(s):\n" + "\n".join(offending)
