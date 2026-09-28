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


def test_evaluation_does_not_import_api_sqlite_or_local_storage() -> None:
    """Stage 16 harness is in-process; it must not open the job DB or data/ stores."""
    for path in _sources("evaluation"):
        for module in _imports(path):
            assert not module.startswith(
                (
                    "cv_masking.api",
                    "cv_masking.adapters.sqlite",
                    "cv_masking.adapters.local_storage",
                )
            ), (path.name, module)
            assert module != "sqlite3"


def test_only_the_sqlite_adapter_imports_sqlite() -> None:
    for path in SRC.rglob("*.py"):
        if "sqlite3" in _imports(path):
            assert path.is_relative_to(SRC / "adapters" / "sqlite"), path.name


WORKER_PROCESS = SRC / "adapters" / "worker" / "process.py"
DESKTOP = SRC / "desktop.py"
_OS_PROCESS_CALLS = {"system", "popen", "fork", "forkpty", "posix_spawn", "posix_spawnp"}


def test_no_source_module_starts_subprocesses_or_opens_sockets() -> None:
    for path in SRC.rglob("*.py"):
        imported = _imports(path)
        if path == DESKTOP:
            assert "subprocess" in imported
            assert "http.client" in imported
            assert not imported & (NETWORK_AND_PROCESS - {"subprocess", "http.client"})
            continue
        assert not imported & NETWORK_AND_PROCESS, path.name


def test_only_the_worker_adapter_starts_a_process() -> None:
    """One same-interpreter worker via multiprocessing spawn (D-33); nothing else runs programs."""
    for path in SRC.rglob("*.py"):
        if path == DESKTOP:
            continue
        uses = {m for m in _imports(path) if m.split(".")[0] in {"multiprocessing", "concurrent"}}
        if path != WORKER_PROCESS:
            assert not uses, (path.name, uses)
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
            ):
                forbidden = node.attr in _OS_PROCESS_CALLS or node.attr.startswith(
                    ("exec", "spawn")
                )
                assert not forbidden, (path.name, node.attr)
    assert "multiprocessing" in _imports(WORKER_PROCESS)


def test_the_worker_process_only_hears_json_and_bytes() -> None:
    """Replies are rebuilt from JSON; pickle-based send/recv is never used on the pipe."""
    tree = ast.parse(WORKER_PROCESS.read_text(encoding="utf-8"), filename=WORKER_PROCESS.name)
    calls = {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }
    assert {"send_bytes", "recv_bytes"} <= calls
    assert not calls & {"send", "recv"}
    assert "pickle" not in _imports(WORKER_PROCESS)
