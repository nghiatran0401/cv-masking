"""Dependency direction: API -> services -> domain/ports; adapters implement ports."""

import ast
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "cv_masking"
PORTS = sorted((SRC / "ports").rglob("*.py"))
ADAPTERS = sorted((SRC / "adapters").rglob("*.py"))
ALL_SOURCES = sorted(SRC.rglob("*.py"))


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def test_layers_exist() -> None:
    assert PORTS
    assert ADAPTERS


@pytest.mark.parametrize("path", PORTS, ids=lambda p: p.name)
def test_ports_depend_only_on_stdlib_and_domain(path: Path) -> None:
    for module in _imports(path):
        assert _is_stdlib(module) or module.startswith("cv_masking.domain"), module


@pytest.mark.parametrize("path", ADAPTERS, ids=lambda p: str(p.relative_to(SRC)))
def test_adapters_do_not_depend_on_the_api_layer(path: Path) -> None:
    for module in _imports(path):
        root = module.split(".")[0]
        assert root not in {"fastapi", "starlette", "uvicorn", "pydantic"}, module
        assert not module.startswith("cv_masking.api"), module


@pytest.mark.parametrize("path", ALL_SOURCES, ids=lambda p: str(p.relative_to(SRC)))
def test_no_source_module_starts_subprocesses_or_opens_sockets(path: Path) -> None:
    banned = {"subprocess", "socket", "urllib.request", "http.client", "ftplib", "smtplib"}
    assert not _imports(path) & banned
