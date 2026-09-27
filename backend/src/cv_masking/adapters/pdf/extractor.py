# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Classify and extract text from a PDF using PyMuPDF.

Extracted text is returned to the caller only. This module never writes it to
logs, disk, or exceptions.
"""

import unicodedata
from collections import defaultdict
from typing import Final

import pymupdf

from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.findings import BoundingBox
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentAlert, HiddenContentCategory
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES, MIN_PAGE_TEXT_CHARS
from cv_masking.ports.extraction import ExtractedDocument, ExtractionResult, TextPart, TextSpan

_MAX_XREFS: Final = 50_000
_LINE_GAP: Final = 4.0
_MIN_VISIBLE_PT: Final = 2.0
_JS_MARKERS: Final = ("/JavaScript", "/JS", "/Launch", "/SubmitForm", "/ImportData")
_SKIP_ANNOT: Final = frozenset({"Link", "Widget"})
_OPEN_ERRORS: Final = (RuntimeError, ValueError, OSError)


def _silence_mupdf() -> None:
    tools = getattr(pymupdf, "TOOLS", None)
    if tools is None:
        return
    display_errors = getattr(tools, "mupdf_display_errors", None)
    display_warnings = getattr(tools, "mupdf_display_warnings", None)
    if callable(display_errors):
        display_errors(False)
    if callable(display_warnings):
        display_warnings(False)


class PyMuPDFExtractor:
    """Read-only PDF classifier/extractor. Does not modify the input bytes."""

    def extract(self, data: bytes) -> ExtractionResult:
        if not data:
            return ExtractionResult(failure=ErrorCode.PDF_MALFORMED)
        _silence_mupdf()
        try:
            document = pymupdf.open(stream=data, filetype="pdf")
        except _OPEN_ERRORS:
            return ExtractionResult(failure=ErrorCode.PDF_MALFORMED)
        try:
            return _classify(document)
        except _OPEN_ERRORS:
            return ExtractionResult(failure=ErrorCode.PDF_MALFORMED)
        finally:
            document.close()


def _classify(document: pymupdf.Document) -> ExtractionResult:
    if bool(getattr(document, "is_encrypted", False)) or bool(
        getattr(document, "needs_pass", False)
    ):
        return ExtractionResult(review=frozenset({ReviewReason.PDF_ENCRYPTED}))
    if document.xref_length() > _MAX_XREFS:
        return ExtractionResult(failure=ErrorCode.PDF_RESOURCE_LIMIT)
    pages = document.page_count
    if pages == 0:
        return ExtractionResult(failure=ErrorCode.PDF_NO_PAGES)
    if pages > HARD_MAX_PDF_PAGES:
        return ExtractionResult(review=frozenset({ReviewReason.PDF_TOO_MANY_PAGES}))
    parts: list[TextPart] = []
    blocking: set[ReviewReason] = set()
    hidden_pages: dict[HiddenContentCategory, set[int]] = defaultdict(set)
    hidden_counts: dict[HiddenContentCategory, int] = defaultdict(int)
    _collect_document_hidden(document, hidden_pages, hidden_counts)
    for index in range(pages):
        page = document.load_page(index)
        number = index + 1
        _collect_page_hidden(page, number, hidden_pages, hidden_counts)
        part, page_block = _extract_page(page, number)
        blocking.update(page_block)
        parts.append(part)
    alerts = _alerts(hidden_pages, hidden_counts)
    if blocking:
        return ExtractionResult(review=frozenset(blocking), alerts=alerts)
    if alerts:
        return ExtractionResult(review=frozenset({ReviewReason.PDF_HIDDEN_CONTENT}), alerts=alerts)
    return ExtractionResult(document=ExtractedDocument(DocumentFormat.PDF, tuple(parts), hidden=()))


def _extract_page(page: pymupdf.Page, number: int) -> tuple[TextPart, set[ReviewReason]]:
    invisible = _invisible_boxes(page)
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
        box = _box(float(x0), float(y0), float(x1), float(y1))
        if box is None or _overlaps_invisible(box, invisible):
            continue
        token = unicodedata.normalize("NFC", word)
        if last_y1 is not None and float(y0) > last_y1 + _LINE_GAP:
            pieces.append("\n")
            offset += 1
        elif offset:
            pieces.append(" ")
            offset += 1
        pieces.append(token)
        spans.append(TextSpan(offset, offset + len(token), (box,)))
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


def _invisible_boxes(page: pymupdf.Page) -> tuple[BoundingBox, ...]:
    cropbox = page.cropbox
    crop = (float(cropbox.x0), float(cropbox.y0), float(cropbox.x1), float(cropbox.y1))
    found: list[BoundingBox] = []
    for item in page.get_texttrace():
        bbox = item.get("bbox")
        if not isinstance(bbox, list | tuple) or len(bbox) != 4:
            continue
        size = float(item.get("size") or 0)
        render_mode = int(item.get("render_mode") or 0)
        if (
            render_mode == 3
            or size < _MIN_VISIBLE_PT
            or _is_white(item.get("color"))
            or _outside_crop(bbox, crop)
        ):
            box = _box(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
            if box is not None:
                found.append(box)
    return tuple(found)


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


def _collect_document_hidden(
    document: pymupdf.Document,
    pages: dict[HiddenContentCategory, set[int]],
    counts: dict[HiddenContentCategory, int],
) -> None:
    first = 1
    embedded = int(document.embfile_count())
    if _has_collection(document):
        embedded += 1
    if embedded:
        pages[HiddenContentCategory.EMBEDDED_FILES].add(first)
        counts[HiddenContentCategory.EMBEDDED_FILES] += embedded
    if bool(getattr(document, "is_form_pdf", False)):
        pages[HiddenContentCategory.FORMS].add(first)
        counts[HiddenContentCategory.FORMS] += 1
    js_hits = _javascript_hits(document)
    if js_hits:
        pages[HiddenContentCategory.JAVASCRIPT].add(first)
        counts[HiddenContentCategory.JAVASCRIPT] += js_hits
    for info in (document.get_ocgs() or {}).values():
        if isinstance(info, dict) and not bool(info.get("on", True)):
            pages[HiddenContentCategory.OPTIONAL_CONTENT].add(first)
            counts[HiddenContentCategory.OPTIONAL_CONTENT] += 1


def _collect_page_hidden(
    page: pymupdf.Page,
    number: int,
    pages: dict[HiddenContentCategory, set[int]],
    counts: dict[HiddenContentCategory, int],
) -> None:
    for annot in page.annots() or []:
        kind = annot.type[1] if isinstance(annot.type, tuple) and len(annot.type) > 1 else ""
        if kind in _SKIP_ANNOT:
            if kind == "Widget":
                pages[HiddenContentCategory.FORMS].add(number)
                counts[HiddenContentCategory.FORMS] += 1
            continue
        pages[HiddenContentCategory.ANNOTATIONS].add(number)
        counts[HiddenContentCategory.ANNOTATIONS] += 1
    if _invisible_boxes(page):
        pages[HiddenContentCategory.INVISIBLE_TEXT].add(number)
        counts[HiddenContentCategory.INVISIBLE_TEXT] += 1


def _javascript_hits(document: pymupdf.Document) -> int:
    hits = 0
    for xref in range(1, document.xref_length()):
        try:
            raw = document.xref_object(xref)
        except _OPEN_ERRORS:
            continue
        if isinstance(raw, str) and any(marker in raw for marker in _JS_MARKERS):
            hits += 1
    return hits


def _has_collection(document: pymupdf.Document) -> bool:
    try:
        catalog = document.pdf_catalog()
        kind, _value = document.xref_get_key(catalog, "Collection")
    except _OPEN_ERRORS:
        return False
    return kind not in {None, "null", ""}


def _alerts(
    pages: dict[HiddenContentCategory, set[int]],
    counts: dict[HiddenContentCategory, int],
) -> tuple[HiddenContentAlert, ...]:
    alerts: list[HiddenContentAlert] = []
    for category in HiddenContentCategory:
        found = pages.get(category)
        count = counts.get(category, 0)
        if not found or count < 1:
            continue
        alerts.append(HiddenContentAlert(category, count, tuple(sorted(found))))
    return tuple(alerts)


def _box(x0: float, y0: float, x1: float, y1: float) -> BoundingBox | None:
    left, bottom, right, top = (round(value, 3) for value in (x0, y0, x1, y1))
    if left >= right or bottom >= top:
        return None
    return BoundingBox(left, bottom, right, top)


def _overlaps_invisible(box: BoundingBox, hidden: tuple[BoundingBox, ...]) -> bool:
    return any(
        box.x0 < other.x1 and box.x1 > other.x0 and box.y0 < other.y1 and box.y1 > other.y0
        for other in hidden
    )


def _outside_crop(
    bbox: list[object] | tuple[object, ...], crop: tuple[float, float, float, float]
) -> bool:
    numbers: list[float] = []
    for value in bbox[:4]:
        if not isinstance(value, int | float) or isinstance(value, bool):
            return False
        numbers.append(float(value))
    if len(numbers) != 4:
        return False
    x0, y0, x1, y1 = numbers
    return x1 < crop[0] or x0 > crop[2] or y1 < crop[1] or y0 > crop[3]


def _is_white(color: object) -> bool:
    if isinstance(color, bool):
        return False
    if isinstance(color, int) and color == 0xFFFFFF:
        return True
    if isinstance(color, int | float):
        return float(color) >= 0.98
    if isinstance(color, list | tuple) and color:
        return all(
            isinstance(channel, int | float)
            and not isinstance(channel, bool)
            and float(channel) >= 0.98
            for channel in color
        )
    return False
