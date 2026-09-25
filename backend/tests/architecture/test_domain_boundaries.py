"""The domain package stays pure: standard library only, no I/O, no dynamic code."""

import ast
from pathlib import Path

import pytest

DOMAIN = Path(__file__).resolve().parents[2] / "src" / "cv_masking" / "domain"
ALLOWED_MODULES = {
    "__future__",
    "collections",
    "collections.abc",
    "dataclasses",
    "datetime",
    "enum",
    "functools",
    "math",
    "re",
    "types",
    "typing",
    "uuid",
}
FORBIDDEN_NAMES = {
    "open",
    "eval",
    "exec",
    "compile",
    "__import__",
    "globals",
    "locals",
    "breakpoint",
    "input",
    "print",
}
DOMAIN_FILES = sorted(DOMAIN.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _imported_modules(tree: ast.Module) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            assert node.level == 0, "use absolute imports"
            assert node.module is not None
            modules.add(node.module)
    return modules


def test_domain_package_has_modules() -> None:
    assert len(DOMAIN_FILES) >= 10


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.name)
def test_domain_imports_only_stdlib_and_itself(path: Path) -> None:
    for module in _imported_modules(_parse(path)):
        if module == "cv_masking.domain" or module.startswith("cv_masking.domain."):
            continue
        assert module in ALLOWED_MODULES, f"{path.name} imports {module}"


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.name)
def test_domain_does_not_use_io_or_dynamic_code(path: Path) -> None:
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.Name):
            assert node.id not in FORBIDDEN_NAMES, f"{path.name} uses {node.id}"
        if isinstance(node, ast.Attribute):
            assert node.attr not in {"now", "utcnow", "today"}, f"{path.name} reads the clock"


@pytest.mark.parametrize("path", DOMAIN_FILES, ids=lambda p: p.name)
def test_domain_does_not_log_or_swallow_exceptions(path: Path) -> None:
    for node in ast.walk(_parse(path)):
        if isinstance(node, ast.ExceptHandler):
            pytest.fail(f"{path.name} catches exceptions; domain code must let them propagate")


def test_checker_rejects_a_forbidden_import() -> None:
    tree = ast.parse("import os\nfrom pathlib import Path\nfrom cv_masking.api import app\n")
    assert _imported_modules(tree) - ALLOWED_MODULES == {"os", "pathlib", "cv_masking.api"}
