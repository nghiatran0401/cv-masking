"""Remove painting inside hidden optional-content blocks of a PDF content stream.

Only painting operators are dropped (text showing, XObjects, shadings, inline
images; path painting becomes ``n``), so graphics and text state stay balanced
for the visible content that follows. Anything the tokenizer cannot parse with
certainty raises ``ContentError``; callers fail closed.
"""

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Final

_WHITESPACE: Final = b"\x00\t\n\x0c\r "
_DELIMITERS: Final = b"()<>[]{}/%"
_TEXT_SHOW: Final = frozenset({b"Tj", b"TJ"})
_PATH_PAINT: Final = frozenset({b"S", b"s", b"f", b"F", b"f*", b"B", b"B*", b"b", b"b*"})
_OPERAND_WORDS: Final = frozenset({b"true", b"false", b"null", b"R"})
"""``R`` is the indirect-reference keyword inside dictionaries, not a painting operator."""
_MAX_STRING_DEPTH: Final = 64


class ContentError(Exception):
    """The content stream cannot be filtered safely."""


@dataclass(frozen=True, slots=True)
class _Token:
    is_operator: bool
    start: int
    end: int
    value: bytes


type NamePredicate = Callable[[bytes], bool]


def strip_hidden(
    data: bytes,
    *,
    hidden_property: NamePredicate,
    hidden_xobject: NamePredicate,
    hidden_inline: NamePredicate | None = None,
) -> tuple[bytes, int]:
    """Return the filtered stream and the number of painting operations removed.

    ``hidden_property`` answers for ``/OC /<name> BDC`` names, ``hidden_xobject``
    for ``/<name> Do`` names (an XObject whose own ``/OC`` is hidden),
    ``hidden_inline`` for ``/OC <<...>> BDC`` dictionaries. Every ``/OC`` BDC/EMC
    pair is unwrapped so dropping ``OCProperties`` cannot change remaining
    painting.
    """
    cuts: list[tuple[int, int, bytes]] = []
    stack: list[tuple[bool, bool]] = []
    inline = hidden_inline or _reject_inline
    for operands, token in _operations(data):
        hidden = bool(stack) and stack[-1][0]
        op = token.value
        if op == b"BDC":
            is_oc = len(operands) >= 1 and operands[0].value == b"/OC"
            nested_hidden = hidden or _bdc_hidden(operands, hidden_property, inline)
            stack.append((nested_hidden, is_oc))
            if is_oc:
                cuts.append((_first_start(operands, token), token.end, b" "))
        elif op == b"BMC":
            stack.append((hidden, False))
        elif op == b"EMC":
            if not stack:
                raise ContentError("unbalanced EMC")
            _was_hidden, unwrap = stack.pop()
            if unwrap:
                cuts.append((token.start, token.end, b" "))
        elif op == b"Do":
            name = _single_name(operands)
            if hidden or hidden_xobject(name):
                cuts.append((_first_start(operands, token), token.end, b" "))
        elif hidden:
            replacement = _hidden_replacement(op, operands)
            if replacement is not None:
                cuts.append((_first_start(operands, token), token.end, replacement))
    if stack:
        raise ContentError("unbalanced BDC/BMC")
    return _apply(data, cuts), len(cuts)


def _operations(data: bytes) -> Iterator[tuple[list[_Token], _Token]]:
    """Operator tokens with their operands; dictionaries and arrays are one operand each."""
    operands: list[_Token] = []
    opened: list[int] = []
    for token in _tokens(data):
        if token.value in {b"<<", b"["}:
            opened.append(token.start)
            continue
        if token.value in {b">>", b"]"}:
            if not opened:
                raise ContentError("unbalanced dictionary or array")
            start = opened.pop()
            if not opened:
                operands.append(_Token(False, start, token.end, data[start : token.end]))
            continue
        if opened:
            if token.is_operator:
                raise ContentError("operator inside a dictionary or array")
            continue
        if not token.is_operator:
            operands.append(token)
            continue
        yield operands, token
        operands = []
    if opened or operands:
        raise ContentError("trailing operands")


def _reject_inline(_raw: bytes) -> bool:
    raise ContentError("inline optional-content dictionary")


def _bdc_hidden(
    operands: list[_Token], hidden_property: NamePredicate, hidden_inline: NamePredicate
) -> bool:
    if len(operands) != 2 or not operands[0].value.startswith(b"/"):
        raise ContentError("BDC needs a tag and properties")
    if operands[0].value != b"/OC":
        return False
    raw = operands[1].value
    if raw.startswith(b"<<"):
        return hidden_inline(raw)
    return hidden_property(_name_of(operands[1]))


def _hidden_replacement(op: bytes, operands: list[_Token]) -> bytes | None:
    if op in _TEXT_SHOW or op in {b"sh", b"BI"}:
        return b" "
    if op == b"'":
        return b" T* "
    if op == b'"':
        if len(operands) != 3:
            raise ContentError('" needs three operands')
        return b" " + operands[0].value + b" Tw " + operands[1].value + b" Tc T* "
    if op in _PATH_PAINT:
        return b" n "
    return None


def _first_start(operands: list[_Token], operator: _Token) -> int:
    return operands[0].start if operands else operator.start


def _single_name(operands: list[_Token]) -> bytes:
    if len(operands) != 1:
        raise ContentError("Do needs one name")
    return _name_of(operands[0])


def _name_of(token: _Token) -> bytes:
    if not token.value.startswith(b"/") or len(token.value) < 2:
        raise ContentError("expected a name")
    return decode_name(token.value[1:])


def decode_name(raw: bytes) -> bytes:
    """Resolve ``#xx`` escapes so names compare equal however they are written."""
    out = bytearray()
    index = 0
    while index < len(raw):
        char = raw[index]
        if char == ord("#") and _is_hex(raw[index + 1 : index + 3]):
            out.append(int(raw[index + 1 : index + 3], 16))
            index += 3
            continue
        out.append(char)
        index += 1
    return bytes(out)


def _is_hex(pair: bytes) -> bool:
    return len(pair) == 2 and all(chr(value) in "0123456789abcdefABCDEF" for value in pair)


def _apply(data: bytes, cuts: list[tuple[int, int, bytes]]) -> bytes:
    if not cuts:
        return data
    out = bytearray()
    cursor = 0
    for start, end, replacement in cuts:
        if start < cursor:
            raise ContentError("overlapping cuts")
        out += data[cursor:start]
        out += replacement
        cursor = end
    out += data[cursor:]
    return bytes(out)


def _tokens(data: bytes) -> Iterator[_Token]:
    index = 0
    length = len(data)
    while index < length:
        char = data[index]
        if char in _WHITESPACE:
            index += 1
            continue
        if char == ord("%"):
            while index < length and data[index] not in b"\r\n":
                index += 1
            continue
        start = index
        if char == ord("("):
            index = _string_end(data, index)
        elif data.startswith(b"<<", index) or data.startswith(b">>", index):
            index += 2
        elif char == ord("<"):
            close = data.find(b">", index)
            if close < 0:
                raise ContentError("unterminated hex string")
            index = close + 1
        elif char in b"[]":
            index += 1
        elif char == ord("/"):
            index += 1
            while index < length and data[index] not in _WHITESPACE + _DELIMITERS:
                index += 1
        elif char in b")>{}":
            raise ContentError("unexpected delimiter")
        else:
            while index < length and data[index] not in _WHITESPACE + _DELIMITERS:
                index += 1
        value = data[start:index]
        if value == b"BI":
            index = _inline_image_end(data, index)
            yield _Token(True, start, index, b"BI")
            continue
        yield _Token(_is_operator(value), start, index, value)


def _is_operator(value: bytes) -> bool:
    if value[:1] in {b"(", b"<", b"[", b"]", b"/"} or value in {b"<<", b">>"}:
        return False
    if value in _OPERAND_WORDS:
        return False
    try:
        float(value)
    except ValueError:
        return True
    return False


def _string_end(data: bytes, index: int) -> int:
    depth = 0
    length = len(data)
    while index < length:
        char = data[index]
        if char == ord("\\"):
            index += 2
            continue
        if char == ord("("):
            depth += 1
            if depth > _MAX_STRING_DEPTH:
                raise ContentError("string nesting too deep")
        elif char == ord(")"):
            depth -= 1
            if depth == 0:
                return index + 1
        index += 1
    raise ContentError("unterminated string")


def _inline_image_end(data: bytes, index: int) -> int:
    """Skip ``BI <dict> ID <binary> EI``; the data ends at whitespace + EI + whitespace/EOF."""
    marker = data.find(b"ID", index)
    while marker >= 0 and not (
        data[marker - 1 : marker] in (b"", *(bytes([c]) for c in _WHITESPACE))
        and data[marker + 2 : marker + 3] in (b"", *(bytes([c]) for c in _WHITESPACE))
    ):
        marker = data.find(b"ID", marker + 2)
    if marker < 0:
        raise ContentError("inline image without ID")
    cursor = marker + 3
    while True:
        end = data.find(b"EI", cursor)
        if end < 0:
            raise ContentError("inline image without EI")
        before = data[end - 1 : end]
        after = data[end + 2 : end + 3]
        if before and before[0] in _WHITESPACE and (not after or after[0] in _WHITESPACE):
            return end + 2
        cursor = end + 2
