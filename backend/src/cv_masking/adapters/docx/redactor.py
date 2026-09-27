"""Permanent DOCX redaction: remove text from the XML and write a new package.

Redacted characters are removed from their ``w:t`` elements and replaced with
the policy label in the first redacted run, so the label keeps that run's
formatting. Formatting is never used to hide anything. The always-strip list
and every hidden-content category (supported-pdf.md §6.3 and §6.4) are removed.
The result is re-extracted and must match the predicted text exactly.
"""

import logging
import posixpath
import zipfile
from collections import defaultdict
from collections.abc import Iterable
from io import BytesIO
from typing import Final
from xml.etree.ElementTree import Element

from cv_masking.adapters.docx.archive import DocxArchiveError, read_docx_archive
from cv_masking.adapters.docx.extractor import DocxExtractor
from cv_masking.adapters.docx.text import (
    VANISH,
    MalformedXmlError,
    Piece,
    W,
    is_text_part,
    parse_xml,
    walk_part,
)
from cv_masking.adapters.docx.xmledit import XmlEditError, XmlPart
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.findings import DocxRedactionRange
from cv_masking.ports.redaction import RedactionResult

logger = logging.getLogger("cv_masking.redaction")

MC: Final = "{http://schemas.openxmlformats.org/markup-compatibility/2006}"
R: Final = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
REL: Final = "{http://schemas.openxmlformats.org/package/2006/relationships}"
CT: Final = "{http://schemas.openxmlformats.org/package/2006/content-types}"
_CONTENT_TYPES: Final = "[Content_Types].xml"
_ZIP_EPOCH: Final = (1980, 1, 1, 0, 0, 0)

_DROPPED_PARTS: Final = frozenset(
    {"docProps/core.xml", "docProps/app.xml", "docProps/custom.xml", "word/people.xml"}
)
_DROPPED_PREFIXES: Final = (
    "docProps/thumbnail",
    "word/comments",
    "word/embeddings/",
    "word/glossary/",
    "customXml/",
)
_DROPPED_REL_TYPES: Final = ("/aFChunk",)
_DELETED: Final = frozenset(
    f"{W}{name}"
    for name in (
        # Field codes; the displayed result is kept and was scanned.
        "instrText",
        # Settings that hold paths, variables, or edit history.
        "attachedTemplate",
        "docVars",
        "mailMerge",
        "rsids",
        "rsid",
        # Tracked changes are accepted: deletions and old formatting go.
        "del",
        "moveFrom",
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
        # Comments, embedded objects, imported chunks, custom XML bindings.
        "commentRangeStart",
        "commentRangeEnd",
        "commentReference",
        "object",
        "altChunk",
        "dataBinding",
        "customXmlPr",
    )
)
_UNWRAPPED: Final = frozenset({f"{W}ins", f"{W}moveTo", f"{W}fldSimple", f"{W}customXml"})
_PICTURE_PROPERTIES: Final = frozenset({"docPr", "cNvPr"})
_PICTURE_TEXT: Final = {"descr", "title"}
_HYPERLINK: Final = f"{W}hyperlink"
_TOOLTIP: Final = f"{W}tooltip"
_RUN: Final = f"{W}r"
_RUN_PROPERTIES: Final = f"{W}rPr"
_ALTERNATE: Final = f"{MC}AlternateContent"

_ERRORS: Final = (
    DocxArchiveError,
    MalformedXmlError,
    XmlEditError,
    zipfile.BadZipFile,
    UnicodeError,
    RuntimeError,
    ValueError,
    OSError,
    LookupError,
)


class _RedactionError(Exception):
    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


class DocxXmlRedactor:
    """Stateless; safe to share. Never logs or stores document text."""

    def redact(
        self, data: bytes, units: tuple[DocxRedactionRange, ...], *, remove_hidden: bool
    ) -> RedactionResult:
        try:
            output = _redact(data, units, remove_hidden=remove_hidden)
        except _RedactionError as error:
            logger.info("docx redaction refused code=%s", error.code)
            return RedactionResult(failure=error.code)
        except _ERRORS:
            logger.info("docx redaction refused code=%s", ErrorCode.REDACT_FAILED)
            return RedactionResult(failure=ErrorCode.REDACT_FAILED)
        logger.info("docx redaction applied ranges=%d", len(units))
        return RedactionResult(output=output, labelled_regions=len(units))


def _redact(data: bytes, ranges: tuple[DocxRedactionRange, ...], *, remove_hidden: bool) -> bytes:
    checked = DocxExtractor().extract(data)
    if checked.failure is not None:
        raise _RedactionError(ErrorCode.REDACT_FAILED)
    if checked.review - {ReviewReason.DOCX_HIDDEN_CONTENT}:
        raise _RedactionError(ErrorCode.REDACT_FAILED)
    if checked.review and not remove_hidden:
        raise _RedactionError(ErrorCode.REDACT_SANITIZE_FAILED)
    parts = read_docx_archive(data)
    by_part: dict[str, list[DocxRedactionRange]] = defaultdict(list)
    for item in ranges:
        if item.part_name not in parts or not is_text_part(item.part_name):
            raise _RedactionError(ErrorCode.REDACT_FAILED)
        by_part[item.part_name].append(item)
    package = _Package(parts)
    expected: dict[str, str] = {}
    for name in sorted(name for name in parts if is_text_part(name)):
        expected[name] = _redact_text(package.xml(name), by_part.get(name, []))
    try:
        _sanitize(package)
    except (XmlEditError, MalformedXmlError) as error:
        raise _RedactionError(ErrorCode.REDACT_SANITIZE_FAILED) from error
    output = package.write()
    _check_output(output, expected)
    return output


class _Package:
    """The input parts, with lazily parsed XML parts and a set of dropped names."""

    __slots__ = ("_xml", "dropped", "parts")

    def __init__(self, parts: dict[str, bytes]) -> None:
        self.parts = parts
        self._xml: dict[str, XmlPart] = {}
        self.dropped: set[str] = set()

    def xml(self, name: str) -> XmlPart:
        part = self._xml.get(name)
        if part is None:
            part = XmlPart(self.parts[name])
            self._xml[name] = part
        return part

    def xml_names(self) -> list[str]:
        return [
            name
            for name in self.parts
            if name not in self.dropped and name.endswith((".xml", ".rels"))
        ]

    def write(self) -> bytes:
        buffer = BytesIO()
        names = [name for name in self.parts if name not in self.dropped]
        names.sort(key=lambda name: name != _CONTENT_TYPES)
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name in names:
                parsed = self._xml.get(name)
                payload = parsed.serialize() if parsed is not None else self.parts[name]
                info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, payload)
        return buffer.getvalue()


def _redact_text(part: XmlPart, ranges: list[DocxRedactionRange]) -> str:
    """Replace each range in its ``w:t`` elements; return the text the output must extract."""
    walked = walk_part(part.root)
    edits: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    for item in sorted(ranges, key=lambda r: r.start):
        if item.end > len(walked.text):
            raise _RedactionError(ErrorCode.REDACT_FAILED)
        touched = [
            index
            for index, piece in enumerate(walked.pieces)
            if piece.start < item.end and piece.start + len(piece.text) > item.start
        ]
        if not touched:
            raise _RedactionError(ErrorCode.REDACT_FAILED)
        for position, index in enumerate(touched):
            piece = walked.pieces[index]
            local_start = max(item.start - piece.start, 0)
            local_end = min(item.end - piece.start, len(piece.text))
            label = item.replacement_label if position == 0 else ""
            edits[index].append((local_start, local_end, label))
    _mirror_alternates(part.root, walked.pieces, edits)
    replaced: dict[int, str] = {}
    for index, piece_edits in edits.items():
        piece = walked.pieces[index]
        text = _apply(piece.text, piece_edits)
        part.set_text(piece.element, text)
        replaced[id(piece.element)] = text
    return walk_part(part.root, replaced).text


def _mirror_alternates(
    root: Element, pieces: tuple[Piece, ...], edits: dict[int, list[tuple[int, int, str]]]
) -> None:
    """Copy edits between the Choice and Fallback copies of the same content.

    Both copies are extracted and scanned, but a finding may be placed in only
    one. When the copies hold the same run texts, the other copy gets the same
    edits; when they differ, each copy keeps only its own findings.
    """
    index_of = {id(piece.element): index for index, piece in enumerate(pieces)}
    for alternate in root.iter(_ALTERNATE):
        branches = [
            [index_of[id(node)] for node in branch.iter() if id(node) in index_of]
            for branch in alternate
        ]
        texts = [[pieces[index].text for index in branch] for branch in branches]
        if len(branches) < 2 or any(text != texts[0] for text in texts):
            continue
        for position in range(len(branches[0])):
            shared = sorted(
                {edit for branch in branches for edit in edits.get(branch[position], [])}
            )
            if not shared:
                continue
            for branch in branches:
                edits[branch[position]] = list(shared)


def _apply(text: str, edits: Iterable[tuple[int, int, str]]) -> str:
    """Apply non-overlapping replacements; overlapping ones merge and keep the first label."""
    merged: list[tuple[int, int, str]] = []
    for start, end, label in sorted(edits):
        if merged and start < merged[-1][1]:
            first_start, first_end, first_label = merged[-1]
            merged[-1] = (first_start, max(first_end, end), first_label or label)
        else:
            merged.append((start, end, label))
    out: list[str] = []
    cursor = 0
    for start, end, label in merged:
        out.append(text[cursor:start])
        out.append(label)
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def _sanitize(package: _Package) -> None:
    package.dropped.update(name for name in package.parts if _is_dropped_name(name))
    _drop_relationships(package)
    for name in package.xml_names():
        if name.startswith("word/") and name.endswith(".xml"):
            _strip_part(package.xml(name), text_part=is_text_part(name))
    _drop_content_type_overrides(package)


def _strip_part(part: XmlPart, *, text_part: bool) -> None:
    parents = {id(child): parent for parent in part.root.iter() for child in parent}
    for element in part.root.iter():
        tag = element.tag
        if tag in _DELETED:
            part.delete(element)
        elif tag in _UNWRAPPED:
            part.unwrap(element)
        elif text_part and tag in VANISH:
            _remove_vanished(part, element, parents)
        local = tag.rpartition("}")[2]
        if local in _PICTURE_PROPERTIES:
            part.drop_attributes(element, _PICTURE_TEXT)
        if tag == _HYPERLINK:
            part.drop_attributes(element, {_TOOLTIP})
        rsids = {
            name
            for name in element.attrib
            if name.startswith(W) and name.removeprefix(W).startswith("rsid")
        }
        if rsids:
            part.drop_attributes(element, rsids)


def _remove_vanished(part: XmlPart, vanish: Element, parents: dict[int, Element]) -> None:
    props = parents.get(id(vanish))
    run = parents.get(id(props)) if props is not None else None
    if props is not None and props.tag == _RUN_PROPERTIES and run is not None and run.tag == _RUN:
        part.delete(run)
    else:
        part.delete(vanish)


def _drop_relationships(package: _Package) -> None:
    """Drop external relationships and those pointing at dropped parts, and their references."""
    for rels_name in [name for name in package.xml_names() if name.endswith(".rels")]:
        owner = _owner_of(rels_name)
        if owner in package.dropped:
            package.dropped.add(rels_name)
            continue
        rels = package.xml(rels_name)
        dropped_ids: set[str] = set()
        for relationship in rels.root.iter(f"{REL}Relationship"):
            target = relationship.get("Target") or ""
            external = (relationship.get("TargetMode") or "").lower() == "external"
            rel_type = relationship.get("Type") or ""
            resolved = None if external else _resolve(owner, target)
            if rel_type.endswith(_DROPPED_REL_TYPES) and resolved is not None:
                package.dropped.add(resolved)
            if external or resolved in package.dropped:
                rels.delete(relationship)
                dropped_ids.add(relationship.get("Id") or "")
        if dropped_ids and owner in package.parts and owner.endswith(".xml"):
            _drop_references(package.xml(owner), dropped_ids - {""})


def _drop_references(part: XmlPart, ids: set[str]) -> None:
    for element in part.root.iter():
        references = {
            name for name, value in element.attrib.items() if name.startswith(R) and value in ids
        }
        if not references:
            continue
        if element.tag == _HYPERLINK:
            part.drop_attributes(element, references)
        else:
            part.delete(element)


def _drop_content_type_overrides(package: _Package) -> None:
    types = package.xml(_CONTENT_TYPES)
    for override in types.root.iter(f"{CT}Override"):
        name = (override.get("PartName") or "").lstrip("/")
        if name in package.dropped:
            types.delete(override)


def _owner_of(rels_name: str) -> str:
    """``word/_rels/document.xml.rels`` → ``word/document.xml``; ``_rels/.rels`` → ``""``."""
    folder, _, base = rels_name.rpartition("/")
    parent = folder.removesuffix("_rels").rstrip("/")
    owner = base.removesuffix(".rels")
    return f"{parent}/{owner}" if parent else owner


def _resolve(owner: str, target: str) -> str:
    if target.startswith("/"):
        return posixpath.normpath(target).lstrip("/")
    folder = posixpath.dirname(owner)
    return posixpath.normpath(posixpath.join(folder, target))


def _is_dropped_name(name: str) -> bool:
    return name in _DROPPED_PARTS or name.startswith(_DROPPED_PREFIXES)


def _check_output(output: bytes, expected: dict[str, str]) -> None:
    """Re-open the output: nothing hidden, the predicted text exactly, no stripped residue."""
    result = DocxExtractor().extract(output)
    if ReviewReason.DOCX_HIDDEN_CONTENT in result.review:
        raise _RedactionError(ErrorCode.REDACT_SANITIZE_FAILED)
    if result.document is None:
        raise _RedactionError(ErrorCode.REDACT_FAILED)
    actual = {part.part_name: part.text for part in result.document.parts}
    if actual != expected:
        raise _RedactionError(ErrorCode.REDACT_FAILED)
    if _has_stripped_residue(read_docx_archive(output)):
        raise _RedactionError(ErrorCode.REDACT_SANITIZE_FAILED)


def _has_stripped_residue(parts: dict[str, bytes]) -> bool:
    if any(_is_dropped_name(name) for name in parts):
        return True
    for name, data in parts.items():
        if not name.endswith((".xml", ".rels")):
            continue
        root = parse_xml(data)
        for element in root.iter():
            if element.tag in _DELETED or element.tag in _UNWRAPPED:
                return True
            if element.tag == f"{REL}Relationship":
                if (element.get("TargetMode") or "").lower() == "external":
                    return True
                target = _resolve(_owner_of(name), element.get("Target") or "")
                if target not in parts and _is_dropped_name(target):
                    return True
            local = element.tag.rpartition("}")[2]
            if local in _PICTURE_PROPERTIES and _PICTURE_TEXT & set(element.attrib):
                return True
            if element.tag == _HYPERLINK and _TOOLTIP in element.attrib:
                return True
            if any(key.startswith(f"{W}rsid") for key in element.attrib):
                return True
    return False
