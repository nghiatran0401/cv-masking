"""Dependency direction: API -> services -> domain/ports; adapters implement ports."""

import ast
import sys
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "cv_masking"
WEB_FRAMEWORKS = {"fastapi", "starlette", "uvicorn", "pydantic"}
NETWORK_AND_PROCESS = {"subprocess", "socket", "urllib.request", "http.client", "ftplib", "smtplib"}


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def _sources(layer: str) -> list[Path]:
    paths = sorted((SRC / layer).rglob("*.py"))
    assert paths, layer
    return paths


def _is_stdlib(module: str) -> bool:
    return module.split(".")[0] in sys.stdlib_module_names


def test_ports_and_application_depend_only_on_stdlib_domain_and_ports() -> None:
    for layer in ("ports", "application"):
        inner = ("cv_masking.domain", "cv_masking.ports", f"cv_masking.{layer}")
        for path in _sources(layer):
            for module in _imports(path):
                allowed = _is_stdlib(module) and module != "sqlite3"
                assert allowed or module.startswith(inner), (path.name, module)


def test_adapters_do_not_depend_on_the_api_or_application_layers() -> None:
    for path in _sources("adapters"):
        for module in _imports(path):
            assert module.split(".")[0] not in WEB_FRAMEWORKS, (path.name, module)
            assert not module.startswith(("cv_masking.api", "cv_masking.application")), module


def test_detection_adapter_does_not_import_format_adapters() -> None:
    paths = sorted((SRC / "adapters" / "detection").rglob("*.py"))
    assert paths
    for path in paths:
        for module in _imports(path):
            assert not module.startswith(("cv_masking.adapters.pdf", "cv_masking.adapters.docx")), (
                path.name,
                module,
            )


def test_only_the_sqlite_adapter_imports_sqlite() -> None:
    for path in SRC.rglob("*.py"):
        if "sqlite3" in _imports(path):
            assert path.is_relative_to(SRC / "adapters" / "sqlite"), path.name


def test_no_source_module_starts_subprocesses_or_opens_sockets() -> None:
    for path in SRC.rglob("*.py"):
        assert not _imports(path) & NETWORK_AND_PROCESS, path.name
