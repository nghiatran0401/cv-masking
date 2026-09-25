"""The domain package stays pure: standard library only, no I/O, no dynamic code."""

import ast
from pathlib import Path

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
FORBIDDEN_NAMES = {"open", "eval", "exec", "compile", "__import__", "breakpoint", "input", "print"}
DOMAIN_FILES = sorted(DOMAIN.rglob("*.py"))


def _parse(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def test_domain_imports_only_stdlib_and_itself() -> None:
    assert len(DOMAIN_FILES) >= 10
    for path in DOMAIN_FILES:
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Import):
                modules = {alias.name for alias in node.names}
            elif isinstance(node, ast.ImportFrom):
                assert node.level == 0, "use absolute imports"
                modules = {node.module or ""}
            else:
                continue
            for module in modules:
                assert module in ALLOWED_MODULES or module.startswith("cv_masking.domain"), (
                    path.name,
                    module,
                )


def test_domain_has_no_io_clock_reads_or_exception_swallowing() -> None:
    for path in DOMAIN_FILES:
        for node in ast.walk(_parse(path)):
            if isinstance(node, ast.Name):
                assert node.id not in FORBIDDEN_NAMES, (path.name, node.id)
            if isinstance(node, ast.Attribute):
                assert node.attr not in {"now", "utcnow", "today"}, path.name
            assert not isinstance(node, ast.ExceptHandler), path.name
