"""DOCX XML parsing and the text walk shared by the extractor and the redactor.

Both must see the same characters at the same offsets: a finding's range in the
extracted text is mapped back onto ``w:t`` elements by the same walk.
"""

import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final, cast
from xml.etree.ElementTree import Element

from defusedxml.common import DTDForbidden, EntitiesForbidden, NotSupportedError
from defusedxml.ElementTree import fromstring as xml_fromstring

from cv_masking.domain.limits import MAX_XML_DEPTH

W: Final = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
VANISH: Final = frozenset({f"{W}vanish", f"{W}specVanish"})
_SKIPPED: Final = frozenset({f"{W}instrText", f"{W}del", f"{W}moveFrom"})
_TEXT_PART_PREFIXES: Final = (
    "word/document.xml",
    "word/header",
    "word/footer",
    "word/footnotes.xml",
    "word/endnotes.xml",
)


class MalformedXmlError(Exception):
    pass


@dataclass(frozen=True, slots=True)
class Piece:
    """One visible ``w:t`` element and where its NFC text starts in the part text."""

    element: Element
    start: int
    text: str


@dataclass(frozen=True, slots=True)
class WalkedPart:
    """Each run's text is NFC. The part text is not normalized again as a whole: a
    combining mark that starts a run would compose with the previous run and shift
    every later offset."""

    text: str
    pieces: tuple[Piece, ...]


def parse_xml(data: bytes) -> Element:
    try:
        root = cast(Element, xml_fromstring(data))
    except (
        SyntaxError,
        ValueError,
        OSError,
        DTDForbidden,
        EntitiesForbidden,
        NotSupportedError,
    ) as error:
        raise MalformedXmlError from error
    _bound_depth(root, 0)
    return root


def _bound_depth(element: Element, depth: int) -> None:
    if depth > MAX_XML_DEPTH:
        raise MalformedXmlError
    for child in list(element):
        _bound_depth(child, depth + 1)


def text_part_names(parts: Mapping[str, bytes]) -> tuple[str, ...]:
    names = [name for name in parts if is_text_part(name)]
    return tuple(sorted(names, key=_text_part_order))


def is_text_part(name: str) -> bool:
    if name.startswith("word/comments"):
        return False
    return any(
        name == prefix or (name.startswith(prefix) and name.endswith(".xml"))
        for prefix in _TEXT_PART_PREFIXES
    )


def _text_part_order(name: str) -> tuple[int, str]:
    order = ("word/document.xml", "word/header", "word/footer", "word/footnotes", "word/endnotes")
    for index, prefix in enumerate(order):
        if name == prefix or name.startswith(prefix):
            return (index, name)
    return (len(order), name)


def walk_part(root: Element, replaced: Mapping[int, str] | None = None) -> WalkedPart:
    """Reading-order text of one part.

    ``replaced`` maps ``id(w:t element)`` to new text; the redactor uses it to
    predict the text its output must extract to.
    """
    overrides = replaced or {}
    chunks: list[str] = []
    pieces: list[Piece] = []
    offset = 0

    def visit(element: Element, vanished: bool) -> None:
        nonlocal offset
        hidden = vanished or element.tag in VANISH or child_has_vanish(element)
        if element.tag in _SKIPPED:
            return
        if element.tag == f"{W}t" and not hidden:
            source = overrides.get(id(element))
            if source is None:
                source = "".join(element.itertext())
            raw = unicodedata.normalize("NFC", source)
            if raw:
                chunks.append(raw)
                pieces.append(Piece(element, offset, raw))
                offset += len(raw)
            return
        if element.tag == f"{W}tab" and not hidden:
            chunks.append("\t")
            offset += 1
            return
        if element.tag in {f"{W}br", f"{W}cr"} and not hidden:
            chunks.append("\n")
            offset += 1
            return
        for child in list(element):
            visit(child, hidden)
        if element.tag == f"{W}p" and chunks and not chunks[-1].endswith("\n"):
            chunks.append("\n")
            offset += 1

    visit(root, vanished=False)
    return WalkedPart("".join(chunks).rstrip("\n"), tuple(pieces))


def child_has_vanish(element: Element) -> bool:
    props = element.find(f"{W}rPr")
    if props is None:
        return False
    return any(child.tag in VANISH for child in props)
