"""Classify and extract text from a DOCX. Text is never logged or stored."""

from collections import defaultdict
from typing import Final
from xml.etree.ElementTree import Element

from cv_masking.adapters.docx.archive import DocxArchiveError, read_docx_archive
from cv_masking.adapters.docx.text import (
    VANISH,
    MalformedXmlError,
    W,
    parse_xml,
    text_part_names,
    walk_part,
)
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentAlert, HiddenContentCategory
from cv_masking.domain.limits import MAX_DOCX_TEXT_CHARS
from cv_masking.ports.extraction import ExtractedDocument, ExtractionResult, TextPart, TextSpan

_OLE_MAGIC: Final = bytes.fromhex("d0cf11e0a1b11ae1")
REL: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}"
_CONTENT_TYPES: Final = "[Content_Types].xml"
_DOCUMENT: Final = "word/document.xml"
_HYPERLINK_TYPE_SUFFIX: Final = "/hyperlink"
_MACRO_OR_TEMPLATE: Final = (
    b"macroEnabled",
    b"vbaProject",
    b"wordprocessingml.template",
    b"vnd.ms-word.template",
)
_TRACKED: Final = frozenset({f"{W}ins", f"{W}del", f"{W}moveFrom", f"{W}moveTo"})
_OPEN_ERRORS: Final = (RuntimeError, ValueError, OSError, LookupError)


class DocxExtractor:
    """Read-only DOCX classifier/extractor. Does not modify the input bytes."""

    def extract(self, data: bytes) -> ExtractionResult:
        if not data:
            return ExtractionResult(failure=ErrorCode.DOCX_MALFORMED)
        if data.startswith(_OLE_MAGIC):
            return ExtractionResult(review=frozenset({ReviewReason.DOCX_ENCRYPTED}))
        try:
            parts = read_docx_archive(data)
        except DocxArchiveError as error:
            return ExtractionResult(failure=error.code)
        if _CONTENT_TYPES not in parts or _DOCUMENT not in parts:
            return ExtractionResult(failure=ErrorCode.DOCX_MALFORMED)
        if _is_macro_or_template(parts):
            return ExtractionResult(failure=ErrorCode.DOCX_MACRO_OR_TEMPLATE)
        try:
            return _classify(parts)
        except MalformedXmlError:
            return ExtractionResult(failure=ErrorCode.DOCX_MALFORMED)
        except _OPEN_ERRORS:
            return ExtractionResult(failure=ErrorCode.DOCX_MALFORMED)


def _is_macro_or_template(parts: dict[str, bytes]) -> bool:
    types = parts.get(_CONTENT_TYPES, b"")
    if any(marker in types for marker in _MACRO_OR_TEMPLATE):
        return True
    return any(name.startswith("word/vbaProject") for name in parts)


def _classify(parts: dict[str, bytes]) -> ExtractionResult:
    hidden_parts: dict[HiddenContentCategory, set[str]] = defaultdict(set)
    hidden_counts: dict[HiddenContentCategory, int] = defaultdict(int)
    _collect_package_hidden(parts, hidden_parts, hidden_counts)
    extracted: list[TextPart] = []
    total = 0
    for name in text_part_names(parts):
        root = parse_xml(parts[name])
        kind = _part_kind(name)
        _collect_xml_hidden(root, kind, hidden_parts, hidden_counts)
        part = _extract_part(name, root)
        total += sum(1 for char in part.text if not char.isspace())
        if total > MAX_DOCX_TEXT_CHARS:
            return ExtractionResult(review=frozenset({ReviewReason.DOCX_TOO_LARGE_TEXT}))
        extracted.append(part)
    alerts = _alerts(hidden_parts, hidden_counts)
    if alerts:
        return ExtractionResult(review=frozenset({ReviewReason.DOCX_HIDDEN_CONTENT}), alerts=alerts)
    visible = sum(1 for part in extracted for char in part.text if not char.isspace())
    if visible < 1:
        return ExtractionResult(review=frozenset({ReviewReason.DOCX_NO_TEXT}))
    return ExtractionResult(
        document=ExtractedDocument(DocumentFormat.DOCX, tuple(extracted), hidden=())
    )


def _part_kind(name: str) -> str:
    if name == _DOCUMENT:
        return "document"
    if name.startswith("word/header"):
        return "header"
    if name.startswith("word/footer"):
        return "footer"
    if name.startswith("word/footnotes"):
        return "footnotes"
    if name.startswith("word/endnotes"):
        return "endnotes"
    if name.startswith("word/comments"):
        return "comments"
    return "other"


def _collect_package_hidden(
    parts: dict[str, bytes],
    hidden_parts: dict[HiddenContentCategory, set[str]],
    hidden_counts: dict[HiddenContentCategory, int],
) -> None:
    embeddings = [name for name in parts if name.startswith("word/embeddings/")]
    if embeddings:
        hidden_parts[HiddenContentCategory.EMBEDDED_FILES].add("document")
        hidden_counts[HiddenContentCategory.EMBEDDED_FILES] += len(embeddings)
    custom = [name for name in parts if name.startswith("customXml/")]
    if custom:
        hidden_parts[HiddenContentCategory.CUSTOM_XML].add("other")
        hidden_counts[HiddenContentCategory.CUSTOM_XML] += len(custom)
    if any(name.startswith("word/glossary/") for name in parts):
        hidden_parts[HiddenContentCategory.GLOSSARY].add("other")
        hidden_counts[HiddenContentCategory.GLOSSARY] += 1
    comments = [name for name in parts if name.startswith("word/comments")]
    if comments:
        hidden_parts[HiddenContentCategory.COMMENTS].add("comments")
        hidden_counts[HiddenContentCategory.COMMENTS] += len(comments)
    for name, data in parts.items():
        if not name.endswith(".rels"):
            continue
        _collect_external_rels(data, hidden_parts, hidden_counts)


def _collect_external_rels(
    data: bytes,
    hidden_parts: dict[HiddenContentCategory, set[str]],
    hidden_counts: dict[HiddenContentCategory, int],
) -> None:
    try:
        root = parse_xml(data)
    except MalformedXmlError:
        return
    for child in root.iter(f"{REL}Relationship"):
        target_mode = (child.get("TargetMode") or "").lower()
        rel_type = child.get("Type") or ""
        if target_mode != "external":
            continue
        if rel_type.endswith(_HYPERLINK_TYPE_SUFFIX):
            continue
        hidden_parts[HiddenContentCategory.EXTERNAL_RELATIONSHIPS].add("document")
        hidden_counts[HiddenContentCategory.EXTERNAL_RELATIONSHIPS] += 1


def _collect_xml_hidden(
    root: Element,
    kind: str,
    hidden_parts: dict[HiddenContentCategory, set[str]],
    hidden_counts: dict[HiddenContentCategory, int],
) -> None:
    for element in root.iter():
        if element.tag in _TRACKED:
            hidden_parts[HiddenContentCategory.TRACKED_CHANGES].add(kind)
            hidden_counts[HiddenContentCategory.TRACKED_CHANGES] += 1
        if element.tag in VANISH:
            hidden_parts[HiddenContentCategory.HIDDEN_TEXT].add(kind)
            hidden_counts[HiddenContentCategory.HIDDEN_TEXT] += 1
        if element.tag == f"{W}altChunk":
            hidden_parts[HiddenContentCategory.IMPORTED_CHUNKS].add(kind)
            hidden_counts[HiddenContentCategory.IMPORTED_CHUNKS] += 1
        if element.tag == f"{W}commentReference":
            hidden_parts[HiddenContentCategory.COMMENTS].add(kind)
            hidden_counts[HiddenContentCategory.COMMENTS] += 1


def _extract_part(name: str, root: Element) -> TextPart:
    walked = walk_part(root)
    spans = tuple(
        TextSpan(piece.start, piece.start + len(piece.text), ()) for piece in walked.pieces
    )
    return TextPart(text=walked.text, spans=spans, part_name=name)


def _alerts(
    hidden_parts: dict[HiddenContentCategory, set[str]],
    hidden_counts: dict[HiddenContentCategory, int],
) -> tuple[HiddenContentAlert, ...]:
    alerts: list[HiddenContentAlert] = []
    for category in HiddenContentCategory:
        found = hidden_parts.get(category)
        count = hidden_counts.get(category, 0)
        if not found or count < 1:
            continue
        alerts.append(HiddenContentAlert(category, count, parts=tuple(sorted(found))))
    return tuple(alerts)
