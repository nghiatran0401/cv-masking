"""Tampered copies of a redacted synthetic DOCX for Stage 11b. Built at test time only."""

import io
import unicodedata
import zipfile
from collections.abc import Callable

from synthetic_docx_redaction import AUTHOR, EMAIL, NAME, decompressed

type Parts = dict[str, bytes]

_DOCUMENT = "word/document.xml"
_HEADER = "word/header1.xml"
_STYLES = "word/styles.xml"
_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def repack(parts: Parts) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def tampered(data: bytes, change: Callable[[Parts], None]) -> bytes:
    parts = decompressed(data)
    change(parts)
    return repack(parts)


def _replace(name: str, old: str, new: str) -> Callable[[Parts], None]:
    def change(parts: Parts) -> None:
        text = parts[name].decode()
        if old not in text:
            raise AssertionError("tamper anchor missing")
        parts[name] = text.replace(old, new, 1).encode()

    return change


def _add(name: str, data: bytes) -> Callable[[Parts], None]:
    def change(parts: Parts) -> None:
        parts[name] = data

    return change


def _in_body(xml: str) -> Callable[[Parts], None]:
    return _replace(_DOCUMENT, "<w:sectPr/>", f"{xml}<w:sectPr/>")


def _run(text: str, props: str = "") -> str:
    return f'<w:p><w:r>{props}<w:t xml:space="preserve">{text}</w:t></w:r></w:p>'


def _both(*changes: Callable[[Parts], None]) -> Callable[[Parts], None]:
    def change(parts: Parts) -> None:
        for item in changes:
            item(parts)

    return change


def _without(*names: str) -> Callable[[Parts], None]:
    def change(parts: Parts) -> None:
        for name in names:
            del parts[name]

    return change


def _styled(style: str, used: str) -> Callable[[Parts], None]:
    return _both(
        _replace(_STYLES, "</w:styles>", f"{style}</w:styles>"),
        _in_body(f'<w:p><w:pPr><w:pStyle w:val="{used}"/></w:pPr>{_run("Synthetic")[5:]}'),
    )


_HIDING_STYLE = (
    '<w:style w:type="paragraph" w:styleId="Secret"><w:rPr><w:vanish/></w:rPr></w:style>'
)
_BASED_STYLE = '<w:style w:type="paragraph" w:styleId="Child"><w:basedOn w:val="Secret"/></w:style>'
_CORE = (
    '<?xml version="1.0" encoding="UTF-8"?><cp:coreProperties '
    'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
    f'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:creator>{NAME}</dc:creator>'
    "</cp:coreProperties>"
).encode()
_COMMENTS = (
    f'<?xml version="1.0" encoding="UTF-8"?><w:comments xmlns:w="{_W}"><w:comment w:id="0">'
    f"{_run(EMAIL)}</w:comment></w:comments>"
).encode()
_EXTERNAL_LINK = (
    '<Relationship Id="rIdTampered" '
    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/hyperlink" '
    f'Target="mailto:{EMAIL}" TargetMode="External"/></Relationships>'
)

VALUE_TAMPERS: dict[str, Callable[[Parts], None]] = {
    "fallback_copy": _replace(
        _DOCUMENT,
        '<mc:Fallback><w:txbxContent><w:p><w:r><w:t xml:space="preserve">Hộp văn bản',
        f'<mc:Fallback><w:txbxContent><w:p><w:r><w:t xml:space="preserve">Hộp văn bản {NAME}',
    ),
    "header_value": _replace(_HEADER, "[EMAIL]", EMAIL),
    "split_across_runs": _replace(
        _DOCUMENT, "[NAME]", "Nguyễn </w:t></w:r><w:r><w:t xml:space='preserve'>Văn Mẫu"
    ),
    "nfd_name": _replace(_DOCUMENT, "[NAME]", unicodedata.normalize("NFD", NAME)),
    "short_value": _replace(_DOCUMENT, "[PHONE]", "Nam"),
    "changed_kept_text": _replace(_DOCUMENT, "với Python", "với Pythons"),
    "document_properties": _add("docProps/core.xml", _CORE),
    "comments": _add("word/comments.xml", _COMMENTS),
    "field_code": _in_body(
        f'<w:p><w:r><w:instrText> HYPERLINK "mailto:{EMAIL}" </w:instrText></w:r></w:p>'
    ),
    "thumbnail": _add("docProps/thumbnail.jpeg", b"\xff\xd8synthetic " + EMAIL.encode()),
    "alt_text": _replace(_DOCUMENT, 'name="Picture 1"', f'name="Picture 1" descr="{NAME}"'),
    "hyperlink_target": _replace(
        "word/_rels/document.xml.rels", "</Relationships>", _EXTERNAL_LINK
    ),
}

METADATA_TAMPERS: dict[str, Callable[[Parts], None]] = {
    "rsid": _replace(_DOCUMENT, "<w:p>", '<w:p w:rsidR="00AB12CD">'),
    "doc_vars": _replace(
        "word/settings.xml",
        "</w:settings>",
        '<w:docVars><w:docVar w:name="x" w:val="y"/></w:docVars></w:settings>',
    ),
    "hidden_run": _in_body(_run("Synthetic", "<w:rPr><w:vanish/></w:rPr>")),
    "tracked_insert": _in_body(
        '<w:p><w:ins w:id="9" w:author="x"><w:r><w:t>Synthetic</w:t></w:r></w:ins></w:p>'
    ),
    "tooltip": _replace(_DOCUMENT, "<w:hyperlink>", '<w:hyperlink w:tooltip="Synthetic">'),
    "author_alt_text": _replace(
        _DOCUMENT, 'name="Picture 1"', f'name="Picture 1" title="{AUTHOR}"'
    ),
    "used_hiding_style": _styled(_HIDING_STYLE, "Secret"),
    "style_based_on_a_hiding_style": _styled(_HIDING_STYLE + _BASED_STYLE, "Child"),
    "default_hiding_style": _replace(
        _STYLES,
        "</w:styles>",
        '<w:style w:type="paragraph" w:default="1" w:styleId="Quiet">'
        "<w:rPr><w:vanish/></w:rPr></w:style></w:styles>",
    ),
    "hiding_document_defaults": _replace(
        _STYLES,
        "</w:styles>",
        "<w:docDefaults><w:rPrDefault><w:rPr><w:vanish/></w:rPr></w:rPrDefault>"
        "</w:docDefaults></w:styles>",
    ),
}

UNUSED_HIDING_STYLE = _replace(_STYLES, "</w:styles>", f"{_HIDING_STYLE}</w:styles>")

_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
STYLES_REMOVED_CLEANLY = _both(
    _without(_STYLES),
    _replace(
        "word/_rels/document.xml.rels",
        f'<Relationship Id="rId4" Type="{_REL}/styles" Target="styles.xml"/>',
        "",
    ),
    _replace(
        "[Content_Types].xml",
        '<Override PartName="/word/styles.xml" '
        'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>',
        "",
    ),
)

INVALID_TAMPERS: dict[str, Callable[[Parts], None]] = {
    "malformed_xml": _replace(_DOCUMENT, "</w:body>", "</w:bdy>"),
    "doctype": _replace(
        _DOCUMENT,
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>',
        '<?xml version="1.0"?><!DOCTYPE w:document [<!ENTITY x "y">]>',
    ),
    "missing_document": _without(_DOCUMENT),
    "dangling_relationship": _without(_STYLES),
}


def zip_bomb() -> bytes:
    return repack({"[Content_Types].xml": b"<Types/>", _DOCUMENT: b"\0" * (10 * 1024 * 1024)})
