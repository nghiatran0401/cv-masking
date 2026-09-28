# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Independent re-inspection of a redacted PDF with a fresh PyMuPDF handle.

Shares no code or state with the redactor. It uses the Stage 6 hidden-content
definition (``hidden.py``) and adds its own checks: every page renders, the
page count matches the source, there is one revision, and no object carries a
key that masking-policy.md §6 always removes. Text is extracted with no clip
and no visibility filter, so invisible or off-page text is still searched.
"""

import re
import unicodedata
from typing import Final

import pymupdf

from cv_masking.adapters.pdf.extractor import MAX_XREFS
from cv_masking.adapters.pdf.hidden import OPEN_ERRORS, box, scan_hidden, silence_mupdf
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES
from cv_masking.ports.extraction import ExtractedDocument, TextPart, TextSpan
from cv_masking.ports.verification import InspectionError, OutputInspection

MAX_RAW_CHARS: Final = 64 * 1024 * 1024
_RENDER: Final = pymupdf.Matrix(0.25, 0.25)
_LINE_GAP: Final = 4.0
_REMOVED_KEYS: Final = (
    "AA",
    "AcroForm",
    "Collection",
    "EmbeddedFile",
    "EmbeddedFiles",
    "GoToE",
    "GoToR",
    "ImportData",
    "JS",
    "JavaScript",
    "Launch",
    "MarkInfo",
    "Metadata",
    "OCProperties",
    "OpenAction",
    "Outlines",
    "PageLabels",
    "PieceInfo",
    "StructParent",
    "StructParents",
    "StructTreeRoot",
    "SubmitForm",
    "Thumb",
    "URI",
    "XFA",
)
_REMOVED_KEY_RE: Final = re.compile(rf"/(?:{'|'.join(_REMOVED_KEYS)})(?![A-Za-z0-9#])(?!\s*null\b)")
_FONT_SUBTYPES: Final = frozenset({"/Type1C", "/CIDFontType0C", "/OpenType"})
_ERRORS: Final = (*OPEN_ERRORS, pymupdf.mupdf.FzErrorBase)


class _InvalidOutputError(Exception):
    pass


class PyMuPDFVerifier:
    """Stateless; safe to share. Never logs or stores document text."""

    def inspect(self, output: bytes, source: bytes) -> OutputInspection:
        silence_mupdf()
        expected_pages = _page_count(source)
        if not output.startswith(b"%PDF-"):
            return _invalid()
        try:
            document = pymupdf.open(stream=output, filetype="pdf")
        except _ERRORS:
            return _invalid()
        try:
            return _inspect(document, output, expected_pages)
        except (_InvalidOutputError, *_ERRORS):
            return _invalid()
        finally:
            document.close()


def _invalid() -> OutputInspection:
    return OutputInspection(None, (), frozenset({ErrorCode.VERIFY_OUTPUT_INVALID}))


def _page_count(source: bytes) -> int:
    try:
        document = pymupdf.open(stream=source, filetype="pdf")
    except _ERRORS as error:
        raise InspectionError("source does not open") from error
    try:
        return int(document.page_count)
    finally:
        document.close()


def _inspect(document: pymupdf.Document, output: bytes, expected_pages: int) -> OutputInspection:
    if (
        bool(getattr(document, "is_encrypted", False))
        or bool(getattr(document, "needs_pass", False))
        or bool(getattr(document, "is_repaired", False))
        or not 1 <= document.page_count <= HARD_MAX_PDF_PAGES
        or document.xref_length() > MAX_XREFS
    ):
        raise _InvalidOutputError
    failures: set[ErrorCode] = set()
    if document.page_count != expected_pages:
        failures.add(ErrorCode.VERIFY_PAGE_COUNT_MISMATCH)
    parts = []
    for index in range(document.page_count):
        page = document.load_page(index)
        page.get_pixmap(matrix=_RENDER, alpha=False)
        parts.append(_page_text(page, index + 1))
        if page.first_annot is not None or page.get_links() or next(page.widgets(), None):
            failures.add(ErrorCode.VERIFY_RESIDUAL_METADATA)
    raw, has_removed_key = _objects(document)
    if (
        has_removed_key
        or output.count(b"startxref") != 1
        or _has_metadata(document)
        or scan_hidden(document)
    ):
        failures.add(ErrorCode.VERIFY_RESIDUAL_METADATA)
    extracted = ExtractedDocument(DocumentFormat.PDF, tuple(parts))
    return OutputInspection(extracted, raw, frozenset(failures))


def _has_metadata(document: pymupdf.Document) -> bool:
    metadata = document.metadata or {}
    if any(value for key, value in metadata.items() if key not in {"format", "encryption"}):
        return True
    return bool(document.get_xml_metadata()) or bool(document.get_toc())


def _objects(document: pymupdf.Document) -> tuple[tuple[str, ...], bool]:
    """Decoded object sources and non-font, non-image streams; and whether any
    object still has an always-removed key."""
    raw: list[str] = []
    total = 0
    found = False
    for xref in range(1, document.xref_length()):
        source = document.xref_object(xref, compressed=True)
        if not isinstance(source, str):
            continue
        found = found or _REMOVED_KEY_RE.search(source) is not None
        raw.append(source)
        total += len(source)
        if document.xref_is_stream(xref) and not _is_binary_stream(document, xref):
            stream = document.xref_stream(xref)
            if stream:
                raw.append(stream.decode("latin-1"))
                total += len(stream)
        if total > MAX_RAW_CHARS:
            raise _InvalidOutputError
    trailer = document.pdf_trailer(compressed=True)
    if isinstance(trailer, str):
        found = found or _REMOVED_KEY_RE.search(trailer) is not None
    return tuple(raw), found


def _is_binary_stream(document: pymupdf.Document, xref: int) -> bool:
    _kind, subtype = document.xref_get_key(xref, "Subtype")
    if subtype in {"/Image", *_FONT_SUBTYPES}:
        return True
    return any(
        document.xref_get_key(xref, key)[0] not in {None, "null", ""}
        for key in ("Length1", "Length2", "Length3")
    )


def _page_text(page: pymupdf.Page, number: int) -> TextPart:
    pieces: list[str] = []
    spans: list[TextSpan] = []
    offset = 0
    last_y1: float | None = None
    for item in page.get_text("words", sort=True, clip=pymupdf.INFINITE_RECT()):
        if len(item) < 5 or not isinstance(item[4], str) or item[4] == "":
            continue
        x0, y0, x1, y1 = (float(value) for value in item[:4])
        token = unicodedata.normalize("NFC", item[4])
        if last_y1 is not None and y0 > last_y1 + _LINE_GAP:
            pieces.append("\n")
            offset += 1
        elif offset:
            pieces.append(" ")
            offset += 1
        pieces.append(token)
        word_box = box(x0, y0, x1, y1)
        spans.append(TextSpan(offset, offset + len(token), () if word_box is None else (word_box,)))
        offset += len(token)
        last_y1 = y1
    return TextPart(text="".join(pieces), spans=tuple(spans), page_number=number)
