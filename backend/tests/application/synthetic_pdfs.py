# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Synthetic PDFs generated at test time. Never commit the bytes.

PYTEST_DONT_REWRITE
"""

import io
import unicodedata

import pymupdf

HEADER = "Header repeat"
SKILL = "Skill Python"
SCHOOL = "School Example University"
CELL = "Table cell"
EMAIL = "mau.nguyen@example.test"
VISIBLE = "Visible body text here ok"
ZERO_PAGE_PDF = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    b"2 0 obj\n<< /Type /Pages /Count 0 /Kids [] >>\nendobj\n"
    b"trailer\n<< /Root 1 0 R >>\n%%EOF\n"
)


def _box(page: pymupdf.Page, rect: tuple[float, float, float, float], text: str) -> None:
    page.insert_htmlbox(pymupdf.Rect(*rect), f"<p>{text}</p>")


def _bytes(document: pymupdf.Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def supported_layouts_pdf() -> bytes:
    """Header, Vietnamese NFD name, two columns, a table cell, and a repeated email."""
    document = pymupdf.open()
    page = document.new_page()
    given = unicodedata.normalize("NFD", "Mau")
    _box(page, (50, 20, 520, 48), HEADER)
    _box(page, (50, 55, 520, 110), f"Ho va ten: Nguyen Van {given}")
    _box(page, (50, 120, 280, 250), SKILL)
    _box(page, (310, 120, 560, 250), SCHOOL)
    _box(page, (50, 270, 200, 320), CELL)
    _box(page, (220, 270, 500, 320), EMAIL)
    second = document.new_page()
    _box(second, (50, 60, 500, 120), EMAIL)
    return _bytes(document)


def image_only_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 16, 16), 0)
    pixmap.clear_with(200)
    page.insert_image(page.rect, pixmap=pixmap)
    return _bytes(document)


def encrypted_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    _box(page, (50, 50, 500, 140), VISIBLE)
    buffer = io.BytesIO()
    document.save(buffer, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="synthetic")
    document.close()
    return buffer.getvalue()


def many_pages_pdf(count: int = 31) -> bytes:
    document = pymupdf.open()
    for index in range(count):
        page = document.new_page()
        _box(page, (50, 50, 500, 140), f"Page body text {index:02d} extra")
    return _bytes(document)


def hidden_content_pdf() -> bytes:
    document = pymupdf.open()
    page = document.new_page()
    _box(page, (50, 50, 500, 140), VISIBLE)
    page.add_text_annot(pymupdf.Point(120, 240), "synthetic note must never leak")
    document.embfile_add("CV_Nguyen_secret.txt", b"synthetic attachment")
    xref = document.get_new_xref()
    document.update_object(xref, "<< /S /JavaScript /JS (app.alert(1);) >>")
    document.xref_set_key(document.pdf_catalog(), "OpenAction", f"{xref} 0 R")
    page.insert_text((72, 500), "tiny hidden name", fontsize=1.0)
    return _bytes(document)
