# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Classify and extract text from a PDF using PyMuPDF.

Extracted text is returned to the caller only. This module never writes it to
logs, disk, or exceptions.
"""

import unicodedata
from collections import defaultdict
from typing import Final

import pymupdf

from cv_masking.adapters.pdf.hidden import (
    OPEN_ERRORS,
    HiddenCounts,
    HiddenPages,
    alerts,
    box,
    collect_document_hidden,
    collect_page_hidden,
    invisible_boxes,
    overlaps_any,
    silence_mupdf,
)
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES, MIN_PAGE_TEXT_CHARS
from cv_masking.ports.extraction import ExtractedDocument, ExtractionResult, TextPart, TextSpan

MAX_XREFS: Final = 50_000
_LINE_GAP: Final = 4.0


class PyMuPDFExtractor:
    """Read-only PDF classifier/extractor. Does not modify the input bytes."""

    def extract(self, data: bytes) -> ExtractionResult:
        if not data:
            return ExtractionResult(failure=ErrorCode.PDF_MALFORMED)
        silence_mupdf()
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except OPEN_ERRORS:
            return ExtractionResult(failure=ErrorCode.PDF_MALFORMED)
        try:
            return _classify(document)
        except OPEN_ERRORS:
            return ExtractionResult(failure=ErrorCode.PDF_MALFORMED)
        finally:
            document.close()


def _classify(document: pymupdf.Document) -> ExtractionResult:
    if bool(getattr(document, "is_encrypted", False)) or bool(
        getattr(document, "needs_pass", False)
    ):
        return ExtractionResult(review=frozenset({ReviewReason.PDF_ENCRYPTED}))
    if document.xref_length() > MAX_XREFS:
        return ExtractionResult(failure=ErrorCode.PDF_RESOURCE_LIMIT)
    pages = document.page_count
    if pages == 0:
        return ExtractionResult(failure=ErrorCode.PDF_NO_PAGES)
    if pages > HARD_MAX_PDF_PAGES:
        return ExtractionResult(review=frozenset({ReviewReason.PDF_TOO_MANY_PAGES}))
    parts: list[TextPart] = []
    blocking: set[ReviewReason] = set()
    hidden_pages: HiddenPages = defaultdict(set)
    hidden_counts: HiddenCounts = defaultdict(int)
    collect_document_hidden(document, hidden_pages, hidden_counts)
    for index in range(pages):
        page = document.load_page(index)
        number = index + 1
        collect_page_hidden(page, number, hidden_pages, hidden_counts)
        part, page_block = _extract_page(page, number)
        blocking.update(page_block)
        parts.append(part)
    if blocking:
        return ExtractionResult(review=frozenset(blocking))
    found = alerts(hidden_pages, hidden_counts)
    return ExtractionResult(
        document=ExtractedDocument(DocumentFormat.PDF, tuple(parts), hidden=found)
    )


def _extract_page(page: pymupdf.Page, number: int) -> tuple[TextPart, set[ReviewReason]]:
    invisible = invisible_boxes(page)
    words = page.get_text("words", sort=True)
    pieces: list[str] = []
    spans: list[TextSpan] = []
    offset = 0
    last_y1: float | None = None
    for item in words:
        if len(item) < 5:
            continue
        x0, y0, x1, y1, word = item[0], item[1], item[2], item[3], item[4]
        if not isinstance(word, str) or word == "":
            continue
        word_box = box(float(x0), float(y0), float(x1), float(y1))
        if word_box is None or overlaps_any(word_box, invisible):
            continue
        token = unicodedata.normalize("NFC", word)
        if last_y1 is not None and float(y0) > last_y1 + _LINE_GAP:
            pieces.append("\n")
            offset += 1
        elif offset:
            pieces.append(" ")
            offset += 1
        pieces.append(token)
        spans.append(TextSpan(offset, offset + len(token), (word_box,)))
        offset += len(token)
        last_y1 = float(y1)
    text = unicodedata.normalize("NFC", "".join(pieces))
    part = TextPart(text=text, spans=tuple(spans), page_number=number)
    visible = sum(1 for char in text if not char.isspace())
    if visible >= MIN_PAGE_TEXT_CHARS:
        return part, set()
    if _has_unmapped_text(page):
        return part, {ReviewReason.PDF_TEXT_UNRELIABLE}
    return part, {ReviewReason.PDF_NO_TEXT_LAYER}


def _has_unmapped_text(page: pymupdf.Page) -> bool:
    for item in page.get_texttrace():
        raw = item.get("text")
        if not isinstance(raw, str):
            continue
        if "\ufffd" in raw:
            return True
        if raw == "" and item.get("bbox"):
            return True
    return False
