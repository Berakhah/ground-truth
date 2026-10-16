"""Test-fixture web routes stay guarded (open item JP-7).

`publish.yml` and `ci.yml` grep `web/out` for the `data-gt-fixture` marker after the build, so a
fixture route that is unguarded *and* unmarked would slip past both. This pins the convention the
scans rely on: every `web/app/**/*-example/page.tsx` calls `requireFixtureRoute()` and renders the
marker, and `requireFixtureRoute()` is called nowhere else.
"""

from __future__ import annotations

import re
from pathlib import Path

WEB_APP = Path(__file__).resolve().parents[1] / "web" / "app"
MARKER = "data-gt-fixture"
GUARD_CALL = re.compile(r"^\s*requireFixtureRoute\(\);", re.MULTILINE)


def _pages() -> list[Path]:
    return sorted(WEB_APP.rglob("page.tsx"))


def _fixture_pages() -> list[Path]:
    return [p for p in _pages() if p.parent.name.endswith("-example")]


def test_there_are_fixture_routes_to_check() -> None:
    # A rename of the convention must fail here, not turn the checks below vacuous.
    assert _fixture_pages(), "no web/app/**/*-example/page.tsx found"


def test_every_example_route_calls_the_guard_and_carries_the_marker() -> None:
    problems = []
    for page in _fixture_pages():
        text = page.read_text(encoding="utf-8")
        if not GUARD_CALL.search(text):
            problems.append(f"{page.relative_to(WEB_APP)}: no requireFixtureRoute() call")
        if MARKER not in text:
            problems.append(f"{page.relative_to(WEB_APP)}: no {MARKER} marker")
    assert not problems, "\n".join(problems)


def test_the_guard_is_only_called_from_example_routes() -> None:
    # The scans and this test key on the `-example` directory name; a guarded page elsewhere
    # would be invisible to the first two checks.
    stray = [
        str(p.relative_to(WEB_APP))
        for p in _pages()
        if p not in _fixture_pages() and GUARD_CALL.search(p.read_text(encoding="utf-8"))
    ]
    assert not stray, f"requireFixtureRoute() outside a *-example route: {stray}"
