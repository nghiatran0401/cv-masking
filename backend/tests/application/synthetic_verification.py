# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Tampered copies of a redacted synthetic PDF for Stage 11. Built at test time only.

PYTEST_DONT_REWRITE
"""

import io
import unicodedata
from collections.abc import Callable
from pathlib import Path

import pymupdf
from synthetic_redaction import ALT_TEXT, AUTHOR, EMAIL, HIDDEN, NAME

OTHER_EMAIL = "tran.thu@example.invalid"
FOLDED_NAME = "Nguyen Van Mau"
STRAY_WORD = "Zulu"


def _edit(data: bytes, change: Callable[[pymupdf.Document], None]) -> bytes:
    document = pymupdf.open(stream=data, filetype="pdf")
    change(document)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _htmlbox(text: str) -> Callable[[pymupdf.Document], None]:
    def change(document: pymupdf.Document) -> None:
        document[0].insert_htmlbox(pymupdf.Rect(50, 420, 550, 450), f"<p>{text}</p>")

    return change


def _text(
    text: str, *, at: tuple[float, float] = (50, 460), render_mode: int = 0
) -> Callable[[pymupdf.Document], None]:
    def change(document: pymupdf.Document) -> None:
        document[0].insert_text(at, text, fontsize=11, render_mode=render_mode)

    return change


def _metadata(document: pymupdf.Document) -> None:
    document.set_metadata({"author": AUTHOR})


def _xmp(document: pymupdf.Document) -> None:
    document.set_xml_metadata(f"<x:xmpmeta xmlns:x='adobe:ns:meta/'>{AUTHOR}</x:xmpmeta>")


def _link(document: pymupdf.Document) -> None:
    document[0].insert_link(
        {
            "kind": pymupdf.LINK_URI,
            "from": pymupdf.Rect(50, 500, 200, 520),
            "uri": "https://example.test",
        }
    )


def _annotation(document: pymupdf.Document) -> None:
    document[0].add_text_annot(pymupdf.Point(300, 400), HIDDEN)


def _embedded_file(document: pymupdf.Document) -> None:
    document.embfile_add("synthetic-attachment.txt", HIDDEN.encode())


def _javascript(document: pymupdf.Document) -> None:
    xref = document.get_new_xref()
    document.update_object(xref, "<< /S /JavaScript /JS (app.alert(1);) >>")
    document.xref_set_key(document.pdf_catalog(), "OpenAction", f"{xref} 0 R")


def _outline(document: pymupdf.Document) -> None:
    document.set_toc([[1, "Synthetic", 1]])


def _structure(document: pymupdf.Document) -> None:
    root = document.get_new_xref()
    document.update_object(root, f"<< /Type /StructTreeRoot /Alt ({ALT_TEXT}) >>")
    document.xref_set_key(document.pdf_catalog(), "StructTreeRoot", f"{root} 0 R")


def _invisible(document: pymupdf.Document) -> None:
    document[0].insert_text((300, 700), "Synthetic", fontsize=11, render_mode=3)


def _extra_page(document: pymupdf.Document) -> None:
    document.new_page()


def _raw_value(document: pymupdf.Document) -> None:
    xref = document.get_new_xref()
    document.update_object(xref, f"<< /Private ({EMAIL}) >>")
    document.xref_set_key(document.pdf_catalog(), "SyntheticPrivate", f"{xref} 0 R")


METADATA_TAMPERS: dict[str, Callable[[pymupdf.Document], None]] = {
    "document_info": _metadata,
    "xmp": _xmp,
    "link": _link,
    "annotation": _annotation,
    "embedded_file": _embedded_file,
    "javascript": _javascript,
    "outline": _outline,
    "tagged_structure": _structure,
    "invisible_text": _invisible,
}

VALUE_TAMPERS: dict[str, Callable[[pymupdf.Document], None]] = {
    "visible_name": _htmlbox(NAME),
    "nfd_name": _htmlbox(unicodedata.normalize("NFD", NAME)),
    "diacritic_free_name": _text(FOLDED_NAME),
    "invisible_name": _text(FOLDED_NAME, render_mode=3),
    "off_page_email": _text(EMAIL, at=(50, 2000)),
    "upper_case_email": _text(EMAIL.upper()),
    "value_in_raw_object": _raw_value,
}


def tampered(data: bytes, change: Callable[[pymupdf.Document], None]) -> bytes:
    return _edit(data, change)


def with_text_at(data: bytes, text: str, point: tuple[float, float]) -> bytes:
    return _edit(data, _text(text, at=point))


def with_other_email(data: bytes) -> bytes:
    return _edit(data, _text(f"Email: {OTHER_EMAIL}"))


def with_extra_page(data: bytes) -> bytes:
    return _edit(data, _extra_page)


def incrementally_updated(data: bytes, directory: Path) -> bytes:
    path = directory / "synthetic-incremental.pdf"
    path.write_bytes(data)
    document = pymupdf.open(path)
    document[0].insert_text((50, 480), "Synthetic", fontsize=11)
    document.saveIncr()
    document.close()
    return path.read_bytes()
