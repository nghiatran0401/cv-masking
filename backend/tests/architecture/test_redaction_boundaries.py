"""Visual tricks cannot stand in for redaction.

The PDF redactor has no drawing calls. The DOCX redactor cannot add elements or
name any formatting property, so text can only be removed, never hidden.
"""

import ast
from pathlib import Path

ADAPTERS = Path(__file__).resolve().parents[2] / "src" / "cv_masking" / "adapters"
PDF = ADAPTERS / "pdf"
DOCX = ADAPTERS / "docx"
REDACTION_MODULES = ("redactor.py", "content.py")
DOCX_REDACTION_MODULES = ("redactor.py", "xmledit.py")
# Output bytes come only from splicing the original part, never from the parsed tree.
TREE_MUTATIONS = frozenset(
    {"SubElement", "makeelement", "set", "addnext", "addprevious", "tostring", "tostringlist"}
)
FORMATTING_WORDS = (
    "highlight",
    "shd",
    "color",
    "vanish",
    "webhidden",
    "strike",
    "sz",
    "effect",
)
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


def _string_constants(path: Path) -> list[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    return [
        node.value
        for node in ast.walk(tree)
        if isinstance(node, ast.Constant) and isinstance(node.value, str)
    ]


def test_docx_redaction_cannot_add_elements_or_formatting() -> None:
    for name in DOCX_REDACTION_MODULES:
        path = DOCX / name
        called = _called_attributes(path)
        assert not called & TREE_MUTATIONS, name
        literals = " ".join(_string_constants(path)).lower()
        leaked = [word for word in FORMATTING_WORDS if word in literals]
        assert not leaked, name


def test_docx_xml_editor_only_removes_or_replaces_text() -> None:
    tree = ast.parse((DOCX / "xmledit.py").read_text(encoding="utf-8"))
    editor = next(
        node for node in tree.body if isinstance(node, ast.ClassDef) and node.name == "XmlPart"
    )
    public = {
        node.name
        for node in editor.body
        if isinstance(node, ast.FunctionDef) and not node.name.startswith("_")
    }
    assert public == {"changed", "delete", "unwrap", "drop_attributes", "set_text", "serialize"}
