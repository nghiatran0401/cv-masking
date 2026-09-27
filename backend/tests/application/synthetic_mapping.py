# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Synthetic PDFs and hand-built pages for Stage 9 mapping. Never commit PDF bytes.

PYTEST_DONT_REWRITE
"""

import io
import unicodedata

import pymupdf

from cv_masking.domain.findings import BoundingBox
from cv_masking.domain.formats import DocumentFormat
from cv_masking.ports.extraction import ExtractedDocument, TextPart, TextSpan

NAME = "Nguyễn Văn Mẫu"
EMAIL = "mau.nguyen@example.test"
PHONE = "0900000000"
COMPANY = "Example Bank Ltd"
REFEREE = "John Sample"
REF_EMAIL = "john.sample@example.invalid"


def _html(page: pymupdf.Page, rect: tuple[float, float, float, float], html: str) -> None:
    page.insert_htmlbox(pymupdf.Rect(*rect), html)


def _bytes(document: pymupdf.Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def layout_pdf() -> bytes:
    """Large-font NFD name, glued contact line, a table row, a wrapped cell, a references
    section, and a second page repeating the email."""
    document = pymupdf.open()
    page = document.new_page()
    nfd_name = unicodedata.normalize("NFD", NAME)
    _html(page, (50, 30, 550, 70), f'<p style="font-size:22px">{nfd_name}</p>')
    _html(page, (50, 80, 550, 100), f"<p>Email:{EMAIL} | {PHONE}</p>")
    _html(page, (50, 120, 550, 140), "<p>Kinh nghiệm làm việc</p>")
    _html(page, (50, 145, 200, 165), "<p>Công ty</p>")
    _html(page, (205, 145, 400, 165), f"<p>{COMPANY}</p>")
    _html(page, (405, 145, 550, 165), "<p>2019 - 2023</p>")
    _html(page, (50, 180, 550, 200), "<p>Người tham chiếu</p>")
    _html(page, (50, 205, 125, 260), f"<p>{REFEREE} Director</p>")
    _html(page, (205, 205, 550, 225), f"<p>Email: {REF_EMAIL}</p>")
    _html(page, (50, 280, 550, 300), "<p>Kỹ năng</p>")
    _html(page, (50, 305, 550, 325), "<p>Python and SQL for reporting work</p>")
    second = document.new_page()
    _html(second, (50, 60, 550, 80), f"<p>Contact: {EMAIL} today</p>")
    _html(second, (50, 90, 550, 110), "<p>Additional synthetic body text here</p>")
    return _bytes(document)


def page(*rows: tuple[tuple[str, float, float, float, float], ...]) -> ExtractedDocument:
    """A page from rows of ``(word, x0, y0, x1, y1)``; rows join with "\\n", words with " "."""
    pieces: list[str] = []
    spans: list[TextSpan] = []
    offset = 0
    for row_index, row in enumerate(rows):
        if row_index:
            pieces.append("\n")
            offset += 1
        for word_index, (word, x0, y0, x1, y1) in enumerate(row):
            if word_index:
                pieces.append(" ")
                offset += 1
            spans.append(TextSpan(offset, offset + len(word), (BoundingBox(x0, y0, x1, y1),)))
            pieces.append(word)
            offset += len(word)
    text = "".join(pieces)
    return ExtractedDocument(DocumentFormat.PDF, (TextPart(text, tuple(spans), page_number=1),))


def glued(*fragments: tuple[str, float, float, float, float]) -> ExtractedDocument:
    """One token drawn as several fragments with no separator (split token)."""
    text = "".join(fragment[0] for fragment in fragments)
    spans: list[TextSpan] = []
    offset = 0
    for word, x0, y0, x1, y1 in fragments:
        spans.append(TextSpan(offset, offset + len(word), (BoundingBox(x0, y0, x1, y1),)))
        offset += len(word)
    return ExtractedDocument(DocumentFormat.PDF, (TextPart(text, tuple(spans), page_number=1),))
