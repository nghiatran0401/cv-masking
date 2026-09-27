"""Byte-level edits on one XML part, keyed by ElementTree elements.

The part is parsed twice: by defusedxml (the tree callers inspect) and by expat
(byte offsets of every element). The two element sequences are matched in
document order and must agree tag by tag. Edits splice the original bytes, so
namespace prefixes, declarations, and everything not edited stay byte-identical.

The only operations are removals and text replacement: delete an element,
unwrap it (drop its tags, keep its children), drop attributes, and replace the
text of a ``w:t``. Nothing can add formatting.
"""

import re
from dataclasses import dataclass, field
from typing import Final
from xml.etree.ElementTree import Element
from xml.parsers import expat

from cv_masking.adapters.docx.text import W, parse_xml

XML_NS: Final = "{http://www.w3.org/XML/1998/namespace}"
_SPACE: Final = f"{XML_NS}space"
_TEXT: Final = f"{W}t"
_ATTRIBUTE_RE: Final = re.compile(rb"""\s+([^\s=/>]+)\s*=\s*("[^"]*"|'[^']*')""")
_DECLARED_ENCODING_RE: Final = re.compile(rb"""^<\?xml[^>]*encoding\s*=\s*["']([^"']+)["']""")
_UTF16_BOMS: Final = (b"\xff\xfe", b"\xfe\xff")


class XmlEditError(Exception):
    """The part cannot be edited safely; the caller fails closed."""


@dataclass(slots=True)
class _Node:
    tag: str
    start: int
    open_end: int
    close_start: int
    end: int
    self_closing: bool
    attributes: tuple[tuple[str, int, int], ...]
    """(resolved name, start, end) of each attribute, relative to the start tag."""


@dataclass(slots=True)
class _Ops:
    delete: bool = False
    unwrap: bool = False
    text: str | None = None
    drop: set[str] = field(default_factory=set)


class XmlPart:
    """One parsed part and its pending edits."""

    __slots__ = ("_data", "_nodes", "_ops", "root")

    def __init__(self, data: bytes) -> None:
        _require_utf8(data)
        self._data = data
        self.root = parse_xml(data)
        elements = list(self.root.iter())
        nodes = _locate(data)
        if len(nodes) != len(elements) or any(
            node.tag != element.tag for node, element in zip(nodes, elements, strict=True)
        ):
            raise XmlEditError("parsers disagree on the element sequence")
        self._nodes = {id(element): node for element, node in zip(elements, nodes, strict=True)}
        self._ops: dict[int, _Ops] = {}

    @property
    def changed(self) -> bool:
        return bool(self._ops)

    def delete(self, element: Element) -> None:
        self._op(element).delete = True

    def unwrap(self, element: Element) -> None:
        self._op(element).unwrap = True

    def drop_attributes(self, element: Element, names: set[str]) -> None:
        present = {name for name, _, _ in self._node(element).attributes}
        if names & present:
            self._op(element).drop |= names & present

    def set_text(self, element: Element, text: str) -> None:
        if element.tag != _TEXT:
            raise XmlEditError("only w:t text can be replaced")
        self._op(element).text = text

    def serialize(self) -> bytes:
        if not self._ops:
            return self._data
        edits: list[tuple[int, int, bytes]] = []
        for key, ops in self._ops.items():
            edits.extend(self._edits(self._nodes[key], ops))
        edits.sort(key=lambda edit: (edit[0], edit[1]))
        out: list[bytes] = []
        cursor = 0
        for start, end, replacement in edits:
            if end <= cursor and start < cursor:
                continue
            if start < cursor:
                raise XmlEditError("overlapping edits")
            out.append(self._data[cursor:start])
            out.append(replacement)
            cursor = end
        out.append(self._data[cursor:])
        return b"".join(out)

    def _op(self, element: Element) -> _Ops:
        self._node(element)
        return self._ops.setdefault(id(element), _Ops())

    def _node(self, element: Element) -> _Node:
        node = self._nodes.get(id(element))
        if node is None:
            raise XmlEditError("element is not part of this document")
        return node

    def _edits(self, node: _Node, ops: _Ops) -> list[tuple[int, int, bytes]]:
        if ops.delete or (ops.unwrap and node.self_closing):
            return [(node.start, node.end, b"")]
        edits: list[tuple[int, int, bytes]] = []
        start_tag = self._data[node.start : node.open_end]
        if ops.unwrap:
            edits.append((node.start, node.open_end, b""))
            edits.append((node.close_start, node.end, b""))
            return edits
        if ops.drop or ops.text is not None:
            rebuilt = _without_attributes(start_tag, node, ops.drop)
            if ops.text is not None:
                rebuilt = _with_preserved_space(rebuilt, node, ops.text)
            if node.self_closing and ops.text is not None:
                rebuilt = rebuilt[:-2].rstrip() + b">"
            edits.append((node.start, node.open_end, rebuilt))
        if ops.text is not None:
            content = _escape(ops.text)
            if node.self_closing:
                qname = _qname(start_tag)
                edits.append((node.open_end, node.open_end, content + b"</" + qname + b">"))
            else:
                edits.append((node.open_end, node.close_start, content))
        return edits


def _require_utf8(data: bytes) -> None:
    if data.startswith(_UTF16_BOMS):
        raise XmlEditError("only UTF-8 parts can be edited")
    declared = _DECLARED_ENCODING_RE.match(data.removeprefix(b"\xef\xbb\xbf"))
    if declared is not None and declared.group(1).lower() not in {b"utf-8", b"utf8"}:
        raise XmlEditError("only UTF-8 parts can be edited")


def _locate(data: bytes) -> list[_Node]:
    parser = expat.ParserCreate(namespace_separator="}")
    parser.SetParamEntityParsing(expat.XML_PARAM_ENTITY_PARSING_NEVER)
    nodes: list[_Node] = []
    open_nodes: list[_Node] = []
    scopes: list[dict[str, str]] = [{"xml": XML_NS[1:-1]}]
    pending: dict[str, str] = {}

    def refuse(*_: object) -> int:
        raise XmlEditError("DTDs and entities are not allowed")

    def declare(prefix: str | None, uri: str) -> None:
        pending[prefix or ""] = uri

    def start(name: str, attributes: dict[str, str]) -> None:
        begin = parser.CurrentByteIndex
        scope = {**scopes[-1], **pending}
        pending.clear()
        scopes.append(scope)
        close = _tag_end(data, begin)
        tag = data[begin:close]
        scanned = _attributes_of(tag, scope)
        if {item[0] for item in scanned} != {_resolved(key) for key in attributes}:
            raise XmlEditError("attribute scan disagrees with the parser")
        node = _Node(
            tag=_resolved(name),
            start=begin,
            open_end=close,
            close_start=close,
            end=close,
            self_closing=tag.endswith(b"/>"),
            attributes=scanned,
        )
        nodes.append(node)
        open_nodes.append(node)

    def end(_name: str) -> None:
        node = open_nodes.pop()
        scopes.pop()
        if node.self_closing:
            return
        node.close_start = parser.CurrentByteIndex
        node.end = data.index(b">", node.close_start) + 1

    parser.StartDoctypeDeclHandler = refuse
    parser.EntityDeclHandler = refuse
    parser.ExternalEntityRefHandler = refuse
    parser.StartNamespaceDeclHandler = declare
    parser.StartElementHandler = start
    parser.EndElementHandler = end
    try:
        parser.Parse(data, True)
    except expat.ExpatError as error:
        raise XmlEditError("malformed XML") from error
    return nodes


def _resolved(name: str) -> str:
    uri, separator, local = name.rpartition("}")
    return f"{{{uri}}}{local}" if separator else name


def _tag_end(data: bytes, begin: int) -> int:
    quote = 0
    for index in range(begin + 1, len(data)):
        byte = data[index]
        if quote:
            if byte == quote:
                quote = 0
        elif byte in (0x22, 0x27):
            quote = byte
        elif byte == 0x3E:
            return index + 1
    raise XmlEditError("unterminated tag")


def _attributes_of(tag: bytes, scope: dict[str, str]) -> tuple[tuple[str, int, int], ...]:
    found: list[tuple[str, int, int]] = []
    for match in _ATTRIBUTE_RE.finditer(tag):
        qname = match.group(1).decode("utf-8")
        if qname == "xmlns" or qname.startswith("xmlns:"):
            continue
        prefix, separator, local = qname.rpartition(":")
        if not separator:
            found.append((local, match.start(), match.end()))
            continue
        uri = scope.get(prefix)
        if uri is None:
            raise XmlEditError("undeclared attribute prefix")
        found.append((f"{{{uri}}}{local}", match.start(), match.end()))
    return tuple(found)


def _without_attributes(tag: bytes, node: _Node, names: set[str]) -> bytes:
    if not names:
        return tag
    kept: list[bytes] = []
    cursor = 0
    for name, start, end in node.attributes:
        if name in names:
            kept.append(tag[cursor:start])
            cursor = end
    kept.append(tag[cursor:])
    return b"".join(kept)


def _with_preserved_space(tag: bytes, node: _Node, text: str) -> bytes:
    needs = text != text.strip() or "  " in text
    has = any(name == _SPACE for name, _, _ in node.attributes)
    if not needs or has:
        return tag
    closing = 2 if tag.endswith(b"/>") else 1
    return tag[:-closing] + b' xml:space="preserve"' + tag[-closing:]


def _qname(tag: bytes) -> bytes:
    match = re.match(rb"<([^\s/>]+)", tag)
    if match is None:
        raise XmlEditError("start tag has no name")
    return match.group(1)


def _escape(text: str) -> bytes:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").encode("utf-8")
