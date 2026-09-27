"""Synthetic DOCX files generated at test time. Never commit the bytes."""

import io
import unicodedata
import zipfile

from cv_masking.domain.limits import MAX_DOCX_TEXT_CHARS

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
MC = "http://schemas.openxmlformats.org/markup-compatibility/2006"
CT_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
HEADER = "Header repeat"
FOOTNOTE = "Footnote line"
CONTROLLED = "controlled text"
SKILL = "Skill Python"
CELL = "Table cell"
EMAIL = "mau.nguyen@example.test"
VISIBLE = "Visible body text here ok"
CORE_CREATOR = "CorePropAuthor"
OLE_MAGIC = bytes.fromhex("d0cf11e0a1b11ae1")


def _document(body: str) -> str:
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{W}" xmlns:mc="{MC}">'
        f"<w:body>{body}</w:body></w:document>"
    )


def _pack(parts: dict[str, bytes | str], *, stored: bool = False) -> bytes:
    types = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">',
        '<Default Extension="xml" ContentType="application/xml"/>',
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>',
        f'<Override PartName="/word/document.xml" ContentType="{CT_MAIN}"/>',
    ]
    if "word/header1.xml" in parts:
        types.append(
            '<Override PartName="/word/header1.xml" ContentType="'
            'application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
        )
    if "word/footnotes.xml" in parts:
        types.append(
            '<Override PartName="/word/footnotes.xml" ContentType="'
            'application/vnd.openxmlformats-officedocument.wordprocessingml.footnotes+xml"/>'
        )
    types.append("</Types>")
    payload = dict(parts)
    payload.setdefault("[Content_Types].xml", "\n".join(types))
    buffer = io.BytesIO()
    compress = zipfile.ZIP_STORED if stored else zipfile.ZIP_DEFLATED
    with zipfile.ZipFile(buffer, "w", compression=compress) as archive:
        for name, data in payload.items():
            raw = data.encode("utf-8") if isinstance(data, str) else data
            archive.writestr(name, raw)
    return buffer.getvalue()


def _run(text: str, *, vanish: bool = False) -> str:
    props = "<w:rPr><w:vanish/></w:rPr>" if vanish else ""
    return f"<w:r>{props}<w:t xml:space='preserve'>{text}</w:t></w:r>"


def _para(*runs: str) -> str:
    return f"<w:p>{''.join(runs)}</w:p>"


def supported_layouts_docx() -> bytes:
    given = unicodedata.normalize("NFD", "Mau")
    box = (
        "<mc:AlternateContent>"
        '<mc:Choice Requires="wps"><w:txbxContent>'
        f"{_para(_run('choice box'))}</w:txbxContent></mc:Choice>"
        "<mc:Fallback><w:txbxContent>"
        f"{_para(_run('fallback box'))}</w:txbxContent></mc:Fallback>"
        "</mc:AlternateContent>"
    )
    body = (
        _para(_run("Ho va ten: Nguyen Van "), _run(given))
        + _para(_run("Ngu"), _run("yen"))
        + (
            "<w:tbl><w:tr>"
            f"<w:tc>{_para(_run(CELL))}</w:tc>"
            f"<w:tc>{_para(_run(SKILL))}</w:tc>"
            "</w:tr></w:tbl>"
        )
        + _para(_run(EMAIL))
        + (
            "<w:p><w:r><w:instrText> HYPERLINK mailto:hidden@example.test </w:instrText>"
            f"</w:r>{_run('profile link')}</w:p>"
        )
        + f"<w:sdt><w:sdtContent>{_para(_run(CONTROLLED))}</w:sdtContent></w:sdt>"
        + box
    )
    header_xml = (
        f'<?xml version="1.0" encoding="UTF-8"?><w:hdr xmlns:w="{W}">{_para(_run(HEADER))}</w:hdr>'
    )
    footnotes = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:footnotes xmlns:w="{W}">'
        f'<w:footnote w:id="1">{_para(_run(FOOTNOTE))}</w:footnote></w:footnotes>'
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties"'
        ' xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{CORE_CREATOR}</dc:creator></cp:coreProperties>"
    )
    return _pack(
        {
            "word/document.xml": _document(body),
            "word/header1.xml": header_xml,
            "word/footnotes.xml": footnotes,
            "docProps/core.xml": core,
        }
    )


def empty_docx() -> bytes:
    return _pack({"word/document.xml": _document("")})


def encrypted_docx() -> bytes:
    return OLE_MAGIC + b"synthetic-ole-container"


def traversal_docx() -> bytes:
    return _pack(
        {
            "word/document.xml": _document(_para(_run(VISIBLE))),
            "../evil.xml": b"x",
        }
    )


def zip_bomb_docx() -> bytes:
    return _pack({"word/document.xml": _document(_para(_run("a" * 200_000)))})


def dtd_docx() -> bytes:
    poisoned = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<!DOCTYPE w:document [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>'
        f'<w:document xmlns:w="{W}"><w:body>{_para(_run(VISIBLE))}</w:body></w:document>'
    )
    return _pack({"word/document.xml": poisoned})


def oversized_docx() -> bytes:
    return _pack(
        {"word/document.xml": _document(_para(_run("x" * (MAX_DOCX_TEXT_CHARS + 100))))},
        stored=True,
    )


def hidden_tracked_docx() -> bytes:
    body = _para(_run(VISIBLE)) + f"<w:ins>{_para(_run('inserted name'))}</w:ins>"
    return _pack({"word/document.xml": _document(body)})


def hidden_vanish_docx() -> bytes:
    body = _para(_run(VISIBLE), _run("secret vanish", vanish=True))
    return _pack({"word/document.xml": _document(body)})


def hidden_comments_docx() -> bytes:
    comments = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:comments xmlns:w="{W}">'
        f'<w:comment w:id="0">'
        f"{_para(_run('secret comment'))}</w:comment></w:comments>"
    )
    body = _para(_run(VISIBLE), '<w:commentReference w:id="0"/>')
    return _pack({"word/document.xml": _document(body), "word/comments.xml": comments})
