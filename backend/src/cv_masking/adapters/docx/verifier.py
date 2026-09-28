"""Independent re-inspection of a redacted DOCX with a fresh archive read.

Shares no code or state with the redactor. It uses the Stage 6b archive
reader (limits and entry-name safety) and text walk, and adds its own checks:
every XML part is well-formed, every internal relationship and content-type
override resolves, no source part is missing unless the policy removes it,
and nothing from the always-strip list (supported-pdf.md §6.3) or any hidden
content category (§6.4, and styles that hide text, D-36) remains.
"""

import posixpath
from collections.abc import Iterable, Mapping
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
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.formats import DocumentFormat
from cv_masking.ports.extraction import ExtractedDocument, TextPart, TextSpan
from cv_masking.ports.verification import InspectionError, OutputInspection

REL: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT: Final = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_CONTENT_TYPES: Final = "[Content_Types].xml"
_DOCUMENT: Final = "word/document.xml"
_STYLES: Final = "word/styles.xml"
_OLE_MAGIC: Final = bytes.fromhex("d0cf11e0a1b11ae1")
_REMOVED_PARTS: Final = frozenset(
    {"docProps/core.xml", "docProps/app.xml", "docProps/custom.xml", "word/people.xml"}
)
_REMOVED_PREFIXES: Final = (
    "docProps/thumbnail",
    "word/comments",
    "word/embeddings/",
    "word/glossary/",
    "customXml/",
    "word/vbaProject",
)
_REMOVED_REL_SUFFIXES: Final = ("/aFChunk", "/attachedTemplate")
_NOT_SEARCHED_PREFIXES: Final = ("word/media/", "word/fonts/")
"""Images are kept unchanged (D-13); embedded fonts are glyph data."""
_RESIDUE: Final = frozenset(
    f"{W}{name}"
    for name in (
        "instrText",
        "fldSimple",
        "attachedTemplate",
        "docVars",
        "mailMerge",
        "rsids",
        "del",
        "ins",
        "moveFrom",
        "moveTo",
        "moveFromRangeStart",
        "moveFromRangeEnd",
        "moveToRangeStart",
        "moveToRangeEnd",
        "rPrChange",
        "pPrChange",
        "sectPrChange",
        "tblPrChange",
        "tblPrExChange",
        "trPrChange",
        "tcPrChange",
        "tblGridChange",
        "numberingChange",
        "cellIns",
        "cellDel",
        "cellMerge",
        "commentRangeStart",
        "commentRangeEnd",
        "commentReference",
        "object",
        "altChunk",
        "dataBinding",
        "customXml",
        "customXmlPr",
        "vanish",
        "specVanish",
    )
)
_DESCRIBED: Final = frozenset({"docPr", "cNvPr"})
_STYLE_REFERENCES: Final = frozenset({f"{W}pStyle", f"{W}rStyle", f"{W}tblStyle"})
_ERRORS: Final = (DocxArchiveError, MalformedXmlError, RuntimeError, ValueError, LookupError)


class _InvalidOutputError(Exception):
    pass


class DocxVerifier:
    """Stateless; safe to share. Never logs or stores document text."""

    def inspect(self, output: bytes, source: bytes) -> OutputInspection:
        try:
            source_parts = read_docx_archive(source)
        except DocxArchiveError as error:
            raise InspectionError("source does not open") from error
        if output.startswith(_OLE_MAGIC):
            return _invalid()
        try:
            return _inspect(read_docx_archive(output), source_parts)
        except (_InvalidOutputError, *_ERRORS):
            return _invalid()


def _invalid() -> OutputInspection:
    return OutputInspection(None, (), frozenset({ErrorCode.VERIFY_OUTPUT_INVALID}))


def _inspect(parts: dict[str, bytes], source_parts: Mapping[str, bytes]) -> OutputInspection:
    if _CONTENT_TYPES not in parts or _DOCUMENT not in parts:
        raise _InvalidOutputError
    roots = {name: parse_xml(data) for name, data in parts.items() if _is_xml(name)}
    if not _references_resolve(parts, roots):
        raise _InvalidOutputError
    failures: set[ErrorCode] = set()
    if not set(source_parts) - _removed_by_policy(source_parts) <= set(parts):
        failures.add(ErrorCode.VERIFY_STRUCTURE_MISMATCH)
    if _has_residue(parts, roots):
        failures.add(ErrorCode.VERIFY_RESIDUAL_METADATA)
    text_parts = tuple(_text_part(name, roots[name]) for name in text_part_names(parts))
    document = ExtractedDocument(DocumentFormat.DOCX, text_parts)
    return OutputInspection(document, _raw(parts, roots), frozenset(failures))


def _is_xml(name: str) -> bool:
    return name.endswith((".xml", ".rels"))


def _text_part(name: str, root: Element) -> TextPart:
    walked = walk_part(root)
    spans = tuple(
        TextSpan(piece.start, piece.start + len(piece.text), ()) for piece in walked.pieces
    )
    return TextPart(text=walked.text, spans=spans, part_name=name)


# ------------------------------------------------------------------ package structure


def _relationships(
    roots: Mapping[str, Element],
) -> Iterable[tuple[str, Element]]:
    for name, root in roots.items():
        if name.endswith(".rels"):
            for relationship in root.iter(f"{REL}Relationship"):
                yield name, relationship


def _target(rels_name: str, target: str) -> str:
    """Part name a relationship target points to, relative to the rels' source part."""
    if target.startswith("/"):
        return posixpath.normpath(target.lstrip("/"))
    folder = posixpath.dirname(posixpath.dirname(rels_name))
    return posixpath.normpath(posixpath.join(folder, target))


def _references_resolve(parts: Mapping[str, bytes], roots: Mapping[str, Element]) -> bool:
    for rels_name, relationship in _relationships(roots):
        if (relationship.get("TargetMode") or "").lower() == "external":
            continue
        if _target(rels_name, relationship.get("Target") or "") not in parts:
            return False
    types = roots[_CONTENT_TYPES]
    return all(
        (override.get("PartName") or "").lstrip("/") in parts
        for override in types.iter(f"{CT}Override")
    )


def _removed_by_policy(source_parts: Mapping[str, bytes]) -> set[str]:
    removed = {
        name
        for name in source_parts
        if name in _REMOVED_PARTS or name.startswith(_REMOVED_PREFIXES)
    }
    try:
        roots = {
            name: parse_xml(data) for name, data in source_parts.items() if name.endswith(".rels")
        }
    except MalformedXmlError as error:
        raise InspectionError("source relationships do not parse") from error
    for rels_name, relationship in _relationships(roots):
        if (relationship.get("Type") or "").endswith(_REMOVED_REL_SUFFIXES):
            removed.add(_target(rels_name, relationship.get("Target") or ""))
    for name in list(removed):
        folder, base = posixpath.split(name)
        removed.add(posixpath.join(folder, "_rels", f"{base}.rels"))
    return removed


# ------------------------------------------------------------------ residue


def _has_residue(parts: Mapping[str, bytes], roots: Mapping[str, Element]) -> bool:
    if any(name in _REMOVED_PARTS or name.startswith(_REMOVED_PREFIXES) for name in parts):
        return True
    for _rels_name, relationship in _relationships(roots):
        if (relationship.get("TargetMode") or "").lower() == "external" or (
            relationship.get("Type") or ""
        ).endswith(_REMOVED_REL_SUFFIXES):
            return True
    for name, root in roots.items():
        if name.startswith("word/") and _has_element_residue(root, styles=name == _STYLES):
            return True
    return _a_used_style_hides_text(roots)


def _has_element_residue(root: Element, *, styles: bool) -> bool:
    """In ``styles.xml`` hidden-text markers are judged by D-36 (used styles only)."""
    for element in root.iter():
        if styles and element.tag in VANISH:
            continue
        if element.tag in _RESIDUE or element.get(f"{W}tooltip") is not None:
            return True
        if any(_local(key).startswith("rsid") for key in element.attrib):
            return True
        if _local(element.tag) in _DESCRIBED and (
            element.get("descr") is not None or element.get("title") is not None
        ):
            return True
    return False


def _a_used_style_hides_text(roots: Mapping[str, Element]) -> bool:
    """D-36: a style that hides text (directly or through ``basedOn``) is used by
    the document, is a default style, or the document defaults hide text."""
    styles = roots.get(_STYLES)
    if styles is None:
        return False
    defaults = styles.find(f"{W}docDefaults")
    if defaults is not None and any(element.tag in VANISH for element in defaults.iter()):
        return True
    own: dict[str, bool] = {}
    bases: dict[str, str] = {}
    defaults_used: set[str] = set()
    for style in styles.iter(f"{W}style"):
        style_id = style.get(f"{W}styleId") or ""
        properties = style.find(f"{W}rPr")
        own[style_id] = properties is not None and any(child.tag in VANISH for child in properties)
        based_on = style.find(f"{W}basedOn")
        if based_on is not None:
            bases[style_id] = based_on.get(f"{W}val") or ""
        if (style.get(f"{W}default") or "").lower() in {"1", "true", "on"}:
            defaults_used.add(style_id)
    used = defaults_used | {
        element.get(f"{W}val") or ""
        for name, root in roots.items()
        if name.startswith("word/") and name != _STYLES
        for element in root.iter()
        if element.tag in _STYLE_REFERENCES
    }
    return any(_hides(style_id, own, bases) for style_id in used)


def _hides(style_id: str, own: Mapping[str, bool], bases: Mapping[str, str]) -> bool:
    seen: set[str] = set()
    current: str | None = style_id
    while current and current not in seen:
        if own.get(current, False):
            return True
        seen.add(current)
        current = bases.get(current)
    return False


def _local(name: str) -> str:
    return name.rsplit("}", 1)[-1]


# ------------------------------------------------------------------ raw search material


def _raw(parts: Mapping[str, bytes], roots: Mapping[str, Element]) -> tuple[str, ...]:
    """Every text node and attribute value of every XML part, and the decoded bytes
    of other non-image parts, for the plain value search. Nodes are joined with a
    space so a value never runs into the next paragraph's text; values split
    across runs are found in the extracted text instead."""
    raw: list[str] = []
    for name, data in parts.items():
        if name.startswith(_NOT_SEARCHED_PREFIXES):
            continue
        root = roots.get(name)
        if root is None:
            raw.append(data.decode("utf-8", "replace"))
            continue
        raw.append(" ".join(root.itertext()))
        raw.append(" ".join(value for element in root.iter() for value in element.attrib.values()))
    return tuple(raw)
