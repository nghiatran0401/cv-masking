# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Optional-content membership (OCG, OCMD, visibility expressions).

Designer PDFs (Canva, Figma, Illustrator) put layer visibility in membership
dictionaries, inline resource dicts, and ``/OC <<...>> BDC`` blocks — not only
in named groups listed as off. Evaluation follows ISO 32000-1 §8.11.2.
Membership that cannot be decided is treated as hidden (over-redaction);
callers still fail closed on malformed content streams and on a render that
introduces new extractable text.
"""

from __future__ import annotations

import re
from typing import Final

import pymupdf

from cv_masking.adapters.pdf.content import ContentError, decode_name

_REF_RE: Final = re.compile(r"(\d+)\s+\d+\s+R")
_WS: Final = frozenset(" \t\n\r\x00\x0c")
_DELIM: Final = frozenset("/<>[](){}%")
_VE_OPS: Final = frozenset({"and", "or", "not"})
_MAX_VE_DEPTH: Final = 8
_MAX_DICT_ENTRIES: Final = 256


def oc_properties(document: pymupdf.Document, owner: int | None) -> dict[bytes, tuple[str, str]]:
    """Resource ``/Properties`` names mapped to ``('xref', 'n 0 R')`` or ``('dict', '<<...>>')``."""
    if owner is None:
        return {}
    try:
        kind, value = document.xref_get_key(owner, "Resources/Properties")
        if kind == "xref":
            value = document.xref_object(_first_ref(value))
            kind = "dict"
        if kind != "dict":
            return {}
        return _property_entries(value)
    except ContentError:
        return {}


def oc_is_hidden(
    document: pymupdf.Document,
    kind: str,
    value: str,
    hidden: set[int],
    seen: set[int] | None = None,
) -> bool:
    """True if membership hides the content, or cannot be decided (over-strip)."""
    try:
        return oc_value_hidden(document, kind, value, hidden, seen)
    except ContentError:
        return True


def oc_value_hidden(
    document: pymupdf.Document,
    kind: str,
    value: str,
    hidden: set[int],
    seen: set[int] | None = None,
) -> bool:
    """Whether an ``/OC`` value (group, membership dict, or inline dict) hides content."""
    if kind == "hidden":
        return True
    if kind == "xref":
        return oc_hidden(document, _first_ref(value), hidden, seen)
    if kind == "dict":
        return _ocmd_from_entries(document, parse_pdf_dict(value), hidden, seen or set())
    raise ContentError("inline optional-content dictionary")


def oc_hidden(
    document: pymupdf.Document, xref: int, hidden: set[int], seen: set[int] | None = None
) -> bool:
    walking = set() if seen is None else set(seen)
    if xref in walking:
        raise ContentError("cyclic optional-content membership")
    walking.add(xref)
    oc_type = document.xref_get_key(xref, "Type")[1]
    ve_kind, ve_raw = document.xref_get_key(xref, "VE")
    groups_kind, groups_raw = document.xref_get_key(xref, "OCGs")
    policy = document.xref_get_key(xref, "P")[1]
    if oc_type == "/OCMD" or ve_kind != "null":
        return _ocmd_hidden(
            document,
            groups_kind=groups_kind,
            groups_raw=groups_raw,
            policy=policy,
            ve_kind=ve_kind,
            ve_raw=ve_raw,
            hidden=hidden,
            seen=walking,
        )
    if oc_type in {"/OCG", "null", ""}:
        return xref in hidden
    raise ContentError("unsupported optional-content type")


def xobject_is_hidden(document: pymupdf.Document, xref: int, hidden: set[int]) -> bool:
    kind, value = document.xref_get_key(xref, "OC")
    if kind == "null":
        return False
    return oc_is_hidden(document, kind, value, hidden)


def _property_entries(raw: str) -> dict[bytes, tuple[str, str]]:
    found: dict[bytes, tuple[str, str]] = {}
    for key, value in parse_pdf_dict(raw).items():
        name = decode_name(key.encode("latin-1"))
        stripped = value.strip()
        if stripped.startswith("<<"):
            found[name] = ("dict", stripped)
        elif _REF_RE.search(stripped):
            found[name] = ("xref", stripped)
        else:
            found[name] = ("hidden", "")
    return found


def _ocmd_from_entries(
    document: pymupdf.Document,
    entries: dict[str, str],
    hidden: set[int],
    seen: set[int],
) -> bool:
    oc_type = entries.get("Type", "").strip()
    groups_kind, groups_raw = _membership_kind(entries.get("OCGs"))
    ve_kind, ve_raw = _membership_kind(entries.get("VE"))
    policy = entries.get("P", "null").strip() or "null"
    if oc_type == "/OCMD" or ve_kind != "null":
        return _ocmd_hidden(
            document,
            groups_kind=groups_kind,
            groups_raw=groups_raw,
            policy=policy,
            ve_kind=ve_kind,
            ve_raw=ve_raw,
            hidden=hidden,
            seen=seen,
        )
    if oc_type in {"/OCG", ""}:
        return _inline_ocg_hidden(document, entries, hidden)
    raise ContentError("unsupported optional-content type")


def _inline_ocg_hidden(
    document: pymupdf.Document, entries: dict[str, str], hidden: set[int]
) -> bool:
    """An inline ``/Type /OCG`` dict has no xref; match the unique named group."""
    raw_name = entries.get("Name", "").strip()
    if not (raw_name.startswith("(") and raw_name.endswith(")")):
        raise ContentError("inline optional-content group without a name")
    label = _pdf_literal(raw_name[1:-1])
    matches = [
        xref
        for xref, info in (document.get_ocgs() or {}).items()
        if isinstance(info, dict) and info.get("name") == label
    ]
    if len(matches) != 1:
        raise ContentError("inline optional-content group did not match one layer")
    return matches[0] in hidden


def _ocmd_hidden(
    document: pymupdf.Document,
    *,
    groups_kind: str,
    groups_raw: str,
    policy: str,
    ve_kind: str,
    ve_raw: str,
    hidden: set[int],
    seen: set[int],
) -> bool:
    ve_kind, ve_raw = _deref_membership(document, ve_kind, ve_raw)
    if ve_kind != "null":
        return not _ve_visible(document, ve_raw, hidden, seen, depth=0)
    refs = _group_xrefs(document, groups_kind, groups_raw)
    if not refs:
        return False
    on = [not _group_hidden(document, ref, hidden, seen) for ref in refs]
    visible = {
        "/AllOn": all(on),
        "/AnyOff": not all(on),
        "/AllOff": not any(on),
    }.get(policy, any(on))
    return not visible


def _group_hidden(document: pymupdf.Document, xref: int, hidden: set[int], seen: set[int]) -> bool:
    try:
        return oc_hidden(document, xref, hidden, seen)
    except ContentError:
        return True


def _membership_kind(raw: str | None) -> tuple[str, str]:
    if raw is None:
        return "null", "null"
    stripped = raw.strip()
    if stripped.startswith("["):
        return "array", stripped
    if stripped.startswith("<<"):
        return "dict", stripped
    if _REF_RE.search(stripped):
        return "xref", stripped
    raise ContentError("unsupported optional-content membership")


def _deref_membership(document: pymupdf.Document, kind: str, raw: str) -> tuple[str, str]:
    if kind != "xref":
        return kind, raw
    obj = document.xref_object(_first_ref(raw)).strip()
    if obj.startswith("["):
        return "array", obj
    if obj.startswith("<<"):
        return "dict", obj
    raise ContentError("unsupported optional-content membership")


def _group_xrefs(document: pymupdf.Document, kind: str, raw: str) -> list[int]:
    if kind == "null":
        return []
    if kind == "xref":
        xref = _first_ref(raw)
        obj = document.xref_object(xref).strip()
        if obj.startswith("["):
            return [int(ref) for ref in _REF_RE.findall(obj)]
        if obj.startswith("<<"):
            oc_type = document.xref_get_key(xref, "Type")[1]
            if oc_type in {"/OCG", "/OCMD", "null", ""}:
                return [xref]
            return [int(ref) for ref in _REF_RE.findall(obj)]
        raise ContentError("unsupported optional-content membership")
    if kind in {"array", "dict"}:
        return [int(ref) for ref in _REF_RE.findall(raw)]
    raise ContentError("unsupported optional-content membership")


def _ve_visible(
    document: pymupdf.Document, raw: str, hidden: set[int], seen: set[int], *, depth: int
) -> bool:
    if depth > _MAX_VE_DEPTH:
        raise ContentError("visibility expression nested too deeply")
    expr = parse_pdf_array(raw)
    return _eval_ve(document, expr, hidden, seen, depth)


def _eval_ve(
    document: pymupdf.Document,
    expr: list[object],
    hidden: set[int],
    seen: set[int],
    depth: int,
) -> bool:
    if not expr or not isinstance(expr[0], str):
        raise ContentError("unsupported visibility expression")
    op = expr[0].lstrip("/").lower()
    if op not in _VE_OPS:
        raise ContentError("unsupported visibility expression")
    args = [_ve_operand(document, item, hidden, seen, depth) for item in expr[1:]]
    if op == "not":
        if len(args) != 1:
            raise ContentError("unsupported visibility expression")
        return not args[0]
    if not args:
        raise ContentError("unsupported visibility expression")
    return all(args) if op == "and" else any(args)


def _ve_operand(
    document: pymupdf.Document,
    item: object,
    hidden: set[int],
    seen: set[int],
    depth: int,
) -> bool:
    if isinstance(item, list):
        return _eval_ve(document, item, hidden, seen, depth + 1)
    if isinstance(item, int):
        return not _group_hidden(document, item, hidden, seen)
    raise ContentError("unsupported visibility expression")


def parse_pdf_dict(raw: str) -> dict[str, str]:
    """Top-level ``<< /Key value ... >>`` entries; values keep their raw PDF syntax."""
    body, _end = _read_dict(raw.strip(), 0)
    entries: dict[str, str] = {}
    index = 0
    while True:
        index = _skip_ws(body, index)
        if index >= len(body):
            break
        if len(entries) >= _MAX_DICT_ENTRIES:
            raise ContentError("optional-content dictionary too large")
        if body[index] != "/":
            raise ContentError("malformed optional-content dictionary")
        key, index = _read_name(body, index)
        index = _skip_ws(body, index)
        value, index = _read_value(body, index)
        entries[key] = value
    return entries


def parse_pdf_array(raw: str) -> list[object]:
    value, end = _read_array(raw.strip(), 0)
    if _skip_ws(raw.strip(), end) != len(raw.strip()):
        raise ContentError("trailing visibility-expression tokens")
    if not isinstance(value, list):
        raise ContentError("visibility expression must be an array")
    return value


def _read_value(data: str, index: int) -> tuple[str, int]:
    index = _skip_ws(data, index)
    if index >= len(data):
        raise ContentError("truncated optional-content dictionary")
    if data.startswith("<<", index):
        _body, end = _read_dict(data, index)
        return data[index:end], end
    if data[index] == "[":
        _parsed, end = _read_array(data, index)
        return data[index:end], end
    if data[index] == "/":
        _name, end = _read_name(data, index)
        return data[index:end], end
    if data[index] == "(":
        end = _string_end(data, index)
        return data[index:end], end
    if data[index] == "<":
        close = data.find(">", index)
        if close < 0:
            raise ContentError("unterminated hex string")
        return data[index : close + 1], close + 1
    return _read_number_or_ref(data, index)


def _read_dict(data: str, index: int) -> tuple[str, int]:
    if not data.startswith("<<", index):
        raise ContentError("expected a dictionary")
    depth = 0
    cursor = index
    while cursor < len(data):
        if data.startswith("<<", cursor):
            depth += 1
            cursor += 2
            continue
        if data.startswith(">>", cursor):
            depth -= 1
            cursor += 2
            if depth == 0:
                return data[index + 2 : cursor - 2], cursor
            continue
        if data[cursor] == "(":
            cursor = _string_end(data, cursor)
            continue
        if data[cursor] == "<" and not data.startswith("<<", cursor):
            close = data.find(">", cursor)
            if close < 0:
                raise ContentError("unterminated hex string")
            cursor = close + 1
            continue
        cursor += 1
    raise ContentError("unterminated dictionary")


def _read_array(data: str, index: int) -> tuple[list[object], int]:
    if index >= len(data) or data[index] != "[":
        raise ContentError("expected an array")
    items: list[object] = []
    cursor = index + 1
    while True:
        cursor = _skip_ws(data, cursor)
        if cursor >= len(data):
            raise ContentError("unterminated array")
        if data[cursor] == "]":
            return items, cursor + 1
        if data[cursor] == "[":
            nested, cursor = _read_array(data, cursor)
            items.append(nested)
            continue
        if data.startswith("<<", cursor):
            raw, cursor = _read_value(data, cursor)
            items.append(raw)
            continue
        if data[cursor] == "/":
            name, cursor = _read_name(data, cursor)
            items.append("/" + name)
            continue
        if data[cursor] == "(":
            end = _string_end(data, cursor)
            items.append(data[cursor:end])
            cursor = end
            continue
        raw, cursor = _read_number_or_ref(data, cursor)
        match = _REF_RE.search(raw)
        items.append(int(match.group(1)) if match else raw)


def _read_name(data: str, index: int) -> tuple[str, int]:
    if index >= len(data) or data[index] != "/":
        raise ContentError("expected a name")
    cursor = index + 1
    while cursor < len(data) and data[cursor] not in _WS and data[cursor] not in _DELIM:
        cursor += 1
    if cursor == index + 1:
        raise ContentError("expected a name")
    return data[index + 1 : cursor], cursor


def _read_number_or_ref(data: str, index: int) -> tuple[str, int]:
    cursor = index
    if cursor < len(data) and data[cursor] in "+-":
        cursor += 1
    if cursor >= len(data) or not (data[cursor].isdigit() or data[cursor] == "."):
        token, end = _read_word(data, index)
        if token in {"true", "false", "null"}:
            return token, end
        raise ContentError("malformed optional-content dictionary")
    while cursor < len(data) and (data[cursor].isdigit() or data[cursor] == "."):
        cursor += 1
    after = _skip_ws(data, cursor)
    gen_end = after
    while gen_end < len(data) and data[gen_end].isdigit():
        gen_end += 1
    after_gen = _skip_ws(data, gen_end)
    if (
        gen_end > after
        and after_gen < len(data)
        and data[after_gen] == "R"
        and (
            after_gen + 1 == len(data)
            or data[after_gen + 1] in _WS
            or data[after_gen + 1] in _DELIM
        )
    ):
        return data[index : after_gen + 1], after_gen + 1
    return data[index:cursor], cursor


def _read_word(data: str, index: int) -> tuple[str, int]:
    cursor = index
    while cursor < len(data) and data[cursor] not in _WS and data[cursor] not in _DELIM:
        cursor += 1
    return data[index:cursor], cursor


def _string_end(data: str, index: int) -> int:
    depth = 0
    cursor = index
    while cursor < len(data):
        char = data[cursor]
        if char == "\\":
            cursor += 2
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return cursor + 1
        cursor += 1
    raise ContentError("unterminated string")


def _skip_ws(data: str, index: int) -> int:
    while index < len(data) and data[index] in _WS:
        index += 1
    return index


def _pdf_literal(body: str) -> str:
    out: list[str] = []
    index = 0
    while index < len(body):
        if body[index] == "\\" and index + 1 < len(body):
            out.append(body[index + 1])
            index += 2
            continue
        out.append(body[index])
        index += 1
    return "".join(out)


def _first_ref(value: str) -> int:
    match = _REF_RE.search(value)
    if match is None:
        raise ContentError("expected an indirect reference")
    return int(match.group(1))
