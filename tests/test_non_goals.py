import ast
from pathlib import Path

import pytest

from ground_truth.golden.schema import FieldType

SRC = Path(__file__).resolve().parents[1] / "ground_truth"
BANNED_NAMES = {"entry_points", "register", "load_plugin", "discover_tasks"}
BANNED_MODULES = {"importlib.metadata", "pkg_resources", "stevedore"}
GRADER_BANNED_IMPORTS = {"httpx", "requests", "urllib", "socket"}
FIELD_TYPE_COUNT = 8

TRAP = "A task registry is the platform trap arriving — stop and escalate."


def _py_files(root: Path) -> list[Path]:
    return sorted(p for p in root.rglob("*.py") if "__pycache__" not in p.parts)


def test_item_schema_is_closed():
    assert len(list(FieldType)) == FIELD_TYPE_COUNT, (
        "The item schema is closed. Adding a field type is a scope decision, not a code change."
    )


def test_no_task_registry():
    offenders: list[str] = []
    for path in _py_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            # Catch bare-name references: calls, attributes, decorators, assignments
            if isinstance(node, ast.Name) and node.id in BANNED_NAMES:
                offenders.append(f"{path}: bare reference to {node.id}")
            if isinstance(node, ast.Attribute) and node.attr in BANNED_NAMES:
                offenders.append(f"{path}: attribute .{node.attr}")
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                mod = getattr(node, "module", None) or ""
                names = [a.name for a in node.names]
                # Check exact module, imported names, and combined form (e.g. importlib.metadata)
                combined = [f"{mod}.{n}" for n in names] if mod else []
                if (
                    mod in BANNED_MODULES
                    or any(n in BANNED_MODULES for n in names)
                    or any(c in BANNED_MODULES for c in combined)
                ):
                    offenders.append(f"{path}: imports {mod or names}")
    assert offenders == [], TRAP + "\n" + "\n".join(offenders)


def test_no_module_scope_callable_registry():
    offenders: list[str] = []
    for path in _py_files(SRC):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            # Check both ast.Assign (PLUGINS = {...}) and ast.AnnAssign (PLUGINS: dict = {...})
            is_assign = isinstance(node, ast.Assign)
            is_annassign = isinstance(node, ast.AnnAssign) and node.value is not None
            if not (is_assign or is_annassign):
                continue
            dict_value = node.value if (is_assign or is_annassign) else None
            if (
                isinstance(dict_value, ast.Dict)
                and dict_value.keys
                and all(
                    isinstance(v, (ast.Name, ast.Attribute, ast.Lambda)) for v in dict_value.values
                )
            ):
                if is_assign:
                    target = getattr(node.targets[0], "id", "<expr>")
                else:  # is_annassign
                    target = getattr(node.target, "id", "<expr>")
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
                bok_shim = mod.startswith("ground_truth._bok_shim")
                runner = mod.startswith("ground_truth.runner")
                if bok_shim or runner:
                    offenders.append(f"{path}: imports phase-1 module {mod}")
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "open"
            ):
                offenders.append(f"{path}: calls open()")
    assert offenders == [], (
        "Graders are phase-2 pure functions. I/O here breaks degraded mode and reproducibility.\n"
        + "\n".join(offenders)
    )


PHASE_2_MODULES = (
    "graders",
    "stats",
    "matrix",
    "calibrate",
    "regression",
    "triage",
    "publish",
    "grade.py",
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
