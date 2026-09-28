"""The verifier is independent: it shares no code or state with the redactors."""

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "cv_masking"
VERIFIER_MODULES = (
    SRC / "adapters" / "pdf" / "verifier.py",
    SRC / "adapters" / "docx" / "verifier.py",
    SRC / "application" / "verification.py",
    SRC / "ports" / "verification.py",
)
REDACTION_MODULES = frozenset(
    {
        "cv_masking.adapters.pdf.redactor",
        "cv_masking.adapters.pdf.content",
        "cv_masking.adapters.docx.redactor",
        "cv_masking.adapters.docx.xmledit",
        "cv_masking.application.redaction",
        "cv_masking.ports.redaction",
    }
)
TEST_DOUBLE_WORDS = ("mock", "fake", "stub", "dummy")


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
            found.update(f"{node.module}.{alias.name}" for alias in node.names)
    return found


def test_verifier_never_imports_redaction_code() -> None:
    for path in VERIFIER_MODULES:
        assert not _imports(path) & REDACTION_MODULES, path.name


def test_production_verification_has_no_test_doubles() -> None:
    for path in VERIFIER_MODULES:
        source = path.read_text(encoding="utf-8").lower()
        assert not any(word in source for word in TEST_DOUBLE_WORDS), path.name
