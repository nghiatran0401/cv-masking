"""Visual overlays cannot stand in for redaction: the PDF redactor has no drawing calls."""

import ast
from pathlib import Path

PDF = Path(__file__).resolve().parents[2] / "src" / "cv_masking" / "adapters" / "pdf"
REDACTION_MODULES = ("redactor.py", "content.py")
DRAWING_CALLS = frozenset(
    {
        "add_freetext_annot",
        "add_rect_annot",
        "add_stamp_annot",
        "insert_htmlbox",
        "insert_image",
        "insert_text",
        "insert_textbox",
        "new_shape",
        "set_opacity",
        "show_pdf_page",
    }
)


def _called_attributes(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return {
        node.func.attr
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    }


def test_redactor_never_draws_on_the_page() -> None:
    for name in REDACTION_MODULES:
        called = _called_attributes(PDF / name)
        assert not called & DRAWING_CALLS, name
        assert not any(attr.startswith("draw_") for attr in called), name


def test_redactor_draws_only_through_applied_redaction_annotations() -> None:
    called = _called_attributes(PDF / "redactor.py")
    assert {"add_redact_annot", "apply_redactions"} <= called
