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
