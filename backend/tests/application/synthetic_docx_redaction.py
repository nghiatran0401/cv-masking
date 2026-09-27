"""Synthetic DOCX packages for Stage 10b redaction. Generated at test time; never commit.

The base CV carries every always-stripped item from supported-pdf.md §6.3.
``HIDDEN_BUILDERS`` add one hidden-content category each (§6.4), always holding
``HIDDEN`` so a test can prove the category left no trace.
"""

import io
import unicodedata
import zipfile
from collections.abc import Callable

NAME = "Nguyễn Văn Mẫu"
EMAIL = "mau.nguyen@example.test"
PHONE = "0900000000"
SALARY = "20.000.000 VND"
COMPANY = "Example Bank Ltd"
BODY = "Kinh nghiệm làm việc tại Example Bank Ltd với Python và SQL"
AUTHOR = "Jane Example"
REFEREE = "John Sample"
HIDDEN = "HiddenSyntheticSecret"
BOX_TEXT = "Hộp văn bản"
MEDIA = b"\x89PNG\r\n\x1a\nsynthetic-image-bytes"
STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    '<w:style w:type="paragraph" w:styleId="Normal"><w:name w:val="Normal"/></w:style>'
    "</w:styles>"
)

_W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
_NAMESPACES = (
    f'xmlns:w="{_W}" xmlns:r="{_R}" '
    'xmlns:mc="http://schemas.openxmlformats.org/markup-compatibility/2006" '
    'xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml" '
    'xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing" '
    'xmlns:o="urn:schemas-microsoft-com:office:office" '
    'mc:Ignorable="w14"'
)
_WML = "application/vnd.openxmlformats-officedocument.wordprocessingml"
_BODY, _RELS, _TYPES, _SETTINGS = "<!--body-->", "<!--rels-->", "<!--types-->", "<!--settings-->"

type Parts = dict[str, str | bytes]


def run(text: str, props: str = "") -> str:
    rpr = f"<w:rPr>{props}</w:rPr>" if props else ""
    return f'<w:r>{rpr}<w:t xml:space="preserve">{text}</w:t></w:r>'


def para(*runs: str) -> str:
    return f'<w:p w:rsidR="00AB12CD" w:rsidRDefault="00AB12CD">{"".join(runs)}</w:p>'


def _document() -> str:
    given = unicodedata.normalize("NFD", "Mẫu")
    field = (
        '<w:r><w:fldChar w:fldCharType="begin"/></w:r>'
        f"<w:r><w:instrText> HYPERLINK mailto:{EMAIL} </w:instrText></w:r>"
        '<w:r><w:fldChar w:fldCharType="separate"/></w:r>'
        f"{run('profile link')}"
        '<w:r><w:fldChar w:fldCharType="end"/></w:r>'
    )
    drawing = (
        "<w:r><w:drawing><wp:inline>"
        f'<wp:docPr id="1" name="Picture 1" descr="{AUTHOR}" title="{AUTHOR}"/>'
        "</wp:inline></w:drawing></w:r>"
    )
    box = (
        "<w:r><mc:AlternateContent>"
        f'<mc:Choice Requires="wps"><w:txbxContent>{para(run(BOX_TEXT))}</w:txbxContent>'
        "</mc:Choice>"
        f"<mc:Fallback><w:txbxContent>{para(run(BOX_TEXT))}</w:txbxContent></mc:Fallback>"
        "</mc:AlternateContent></w:r>"
    )
    body = (
        para(run("Họ và tên: "), run("Nguyễn Văn ", "<w:i/>"), run(given, "<w:b/>"))
        + para(
            run("Email: "),
            f'<w:hyperlink r:id="rIdLink" w:tooltip="{EMAIL}">{run(EMAIL)}</w:hyperlink>',
            run(f" | {PHONE}"),
        )
        + para(run(f"Mức lương mong muốn: {SALARY}"))
        + para(run(BODY))
        + '<w:tbl><w:tblGrid><w:gridCol w:w="4000"/><w:gridCol w:w="4000"/></w:tblGrid>'
        + f"<w:tr><w:tc>{para(run('Kỹ năng'))}</w:tc>"
        f"<w:tc>{para(run('Python'))}</w:tc></w:tr></w:tbl>" + para(field) + para(drawing, box)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f"<w:document {_NAMESPACES}><w:body>{body}{_BODY}<w:sectPr/></w:body></w:document>"
    )


def _relationships(*items: tuple[str, str, str], external: bool = False) -> str:
    mode = ' TargetMode="External"' if external else ""
    return "".join(
        f'<Relationship Id="{rid}" Type="{kind}" Target="{target}"{mode}/>'
        for rid, kind, target in items
    )


def _base_parts() -> Parts:
    header = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:hdr xmlns:w="{_W}">{para(run(f"Liên hệ {EMAIL}"))}</w:hdr>'
    )
    footnotes = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:footnotes xmlns:w="{_W}"><w:footnote w:id="1">'
        f"{para(run(f'Điện thoại {PHONE}'))}</w:footnote></w:footnotes>"
    )
    settings = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:settings xmlns:w="{_W}" xmlns:r="{_R}">{_SETTINGS}'
        '<w:rsids><w:rsidRoot w:val="00AB12CD"/><w:rsid w:val="00AB12CD"/></w:rsids>'
        f'<w:docVars><w:docVar w:name="candidate" w:val="{AUTHOR}"/></w:docVars>'
        "</w:settings>"
    )
    people = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<w15:people xmlns:w15="http://schemas.microsoft.com/office/word/2012/wordml">'
        f'<w15:person w15:author="{AUTHOR}"/></w15:people>'
    )
    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<cp:coreProperties xmlns:cp="http://schemas.openxmlformats.org/package/2006/'
        'metadata/core-properties" xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f"<dc:creator>{AUTHOR}</dc:creator><dc:title>CV {AUTHOR}</dc:title>"
        "</cp:coreProperties>"
    )
    app = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/'
        f'extended-properties"><Company>{AUTHOR} Consulting</Company></Properties>'
    )
    root_rels = _relationships(
        ("rId1", f"{_REL}/officeDocument", "word/document.xml"),
        ("rId2", f"{_PKG_REL}/metadata/core-properties", "docProps/core.xml"),
        ("rId3", f"{_REL}/extended-properties", "docProps/app.xml"),
        ("rId4", f"{_PKG_REL}/metadata/thumbnail", "docProps/thumbnail.jpeg"),
    )
    document_rels = _relationships(
        ("rId1", f"{_REL}/header", "header1.xml"),
        ("rId2", f"{_REL}/footnotes", "footnotes.xml"),
        ("rId3", f"{_REL}/settings", "settings.xml"),
        ("rId4", f"{_REL}/styles", "styles.xml"),
        ("rId5", f"{_REL}/image", "media/image1.png"),
        ("rId6", "http://schemas.microsoft.com/office/2011/relationships/people", "people.xml"),
    ) + _relationships(("rIdLink", f"{_REL}/hyperlink", f"mailto:{EMAIL}"), external=True)
    return {
        "[Content_Types].xml": _content_types(),
        "_rels/.rels": _rels_xml(root_rels),
        "word/document.xml": _document(),
        "word/_rels/document.xml.rels": _rels_xml(document_rels + _RELS),
        "word/header1.xml": header,
        "word/footnotes.xml": footnotes,
        "word/settings.xml": settings,
        "word/styles.xml": STYLES,
        "word/people.xml": people,
        "word/media/image1.png": MEDIA,
        "docProps/core.xml": core,
        "docProps/app.xml": app,
        "docProps/thumbnail.jpeg": b"\xff\xd8\xffsynthetic-thumbnail",
    }


def _rels_xml(body: str) -> str:
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<Relationships xmlns="{_PKG_REL}">{body}</Relationships>'
    )


def _content_types() -> str:
    overrides = {
        "/word/document.xml": f"{_WML}.document.main+xml",
        "/word/header1.xml": f"{_WML}.header+xml",
        "/word/footnotes.xml": f"{_WML}.footnotes+xml",
        "/word/settings.xml": f"{_WML}.settings+xml",
        "/word/styles.xml": f"{_WML}.styles+xml",
        "/word/people.xml": "application/vnd.ms-word.people+xml",
        "/docProps/core.xml": "application/vnd.openxmlformats-package.core-properties+xml",
        "/docProps/app.xml": (
            "application/vnd.openxmlformats-officedocument.extended-properties+xml"
        ),
    }
    items = "".join(
        f'<Override PartName="{name}" ContentType="{kind}"/>' for name, kind in overrides.items()
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="png" ContentType="image/png"/>'
        '<Default Extension="jpeg" ContentType="image/jpeg"/>'
        '<Default Extension="bin" ContentType="application/vnd.openxmlformats-officedocument.'
        'oleObject"/>'
        '<Default Extension="htm" ContentType="text/html"/>'
        f"{items}{_TYPES}</Types>"
    )


def pack(parts: Parts) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            if isinstance(data, str):
                for marker in (_BODY, _RELS, _TYPES, _SETTINGS):
                    data = data.replace(marker, "")
                data = data.encode("utf-8")
            archive.writestr(name, data)
    return buffer.getvalue()


def base_parts() -> Parts:
    return _base_parts()


def cv_docx(body: str = "") -> bytes:
    parts = _base_parts()
    _insert(parts, "word/document.xml", _BODY, body)
    return pack(parts)


def _insert(parts: Parts, name: str, marker: str, xml: str) -> None:
    current = parts[name]
    assert isinstance(current, str)
    parts[name] = current.replace(marker, xml + marker)


def _tracked(parts: Parts) -> None:
    _insert(
        parts,
        "word/document.xml",
        _BODY,
        para(
            f'<w:ins w:id="1" w:author="{AUTHOR}">{run("Inserted line")}</w:ins>',
            f'<w:del w:id="2" w:author="{AUTHOR}"><w:r><w:delText>{HIDDEN}</w:delText></w:r>'
            "</w:del>",
        ),
    )


def _hidden_text(parts: Parts) -> None:
    _insert(parts, "word/document.xml", _BODY, para(run("Shown"), run(HIDDEN, "<w:vanish/>")))


def _comments(parts: Parts) -> None:
    parts["word/comments.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:comments xmlns:w="{_W}"><w:comment w:id="0" w:author="{AUTHOR}">'
        f"{para(run(HIDDEN))}</w:comment></w:comments>"
    )
    _insert(
        parts,
        "word/_rels/document.xml.rels",
        _RELS,
        _relationships(("rIdC", f"{_REL}/comments", "comments.xml")),
    )
    _insert(
        parts,
        "[Content_Types].xml",
        _TYPES,
        f'<Override PartName="/word/comments.xml" ContentType="{_WML}.comments+xml"/>',
    )
    _insert(
        parts,
        "word/document.xml",
        _BODY,
        para(
            '<w:commentRangeStart w:id="0"/>',
            run("Commented"),
            '<w:commentRangeEnd w:id="0"/>',
            '<w:r><w:commentReference w:id="0"/></w:r>',
        ),
    )


def _embedded_files(parts: Parts) -> None:
    parts["word/embeddings/oleObject1.bin"] = b"\xd0\xcf\x11\xe0" + HIDDEN.encode()
    _insert(
        parts,
        "word/_rels/document.xml.rels",
        _RELS,
        _relationships(("rIdOle", f"{_REL}/oleObject", "embeddings/oleObject1.bin")),
    )
    _insert(
        parts,
        "word/document.xml",
        _BODY,
        para('<w:r><w:object><o:OLEObject ProgID="Package" r:id="rIdOle"/></w:object></w:r>'),
    )


def _imported_chunks(parts: Parts) -> None:
    parts["word/afchunk.htm"] = f"<html><body>{HIDDEN}</body></html>".encode()
    _insert(
        parts,
        "word/_rels/document.xml.rels",
        _RELS,
        _relationships(("rIdChunk", f"{_REL}/aFChunk", "afchunk.htm")),
    )
    _insert(parts, "word/document.xml", _BODY, '<w:altChunk r:id="rIdChunk"/>')


def _custom_xml(parts: Parts) -> None:
    parts["customXml/item1.xml"] = f"<data><secret>{HIDDEN}</secret></data>".encode()
    parts["customXml/itemProps1.xml"] = (
        b'<ds:datastoreItem ds:itemID="{00000000-0000-0000-0000-000000000000}" '
        b'xmlns:ds="http://schemas.openxmlformats.org/officeDocument/2006/customXml"/>'
    )
    parts["customXml/_rels/item1.xml.rels"] = _rels_xml(
        _relationships(("rId1", f"{_REL}/customXmlProps", "itemProps1.xml"))
    )
    _insert(
        parts,
        "word/_rels/document.xml.rels",
        _RELS,
        _relationships(("rIdX", f"{_REL}/customXml", "../customXml/item1.xml")),
    )
    _insert(
        parts,
        "word/document.xml",
        _BODY,
        "<w:sdt><w:sdtPr>"
        '<w:dataBinding w:xpath="/data/secret" '
        'w:storeItemID="{00000000-0000-0000-0000-000000000000}"/>'
        f"</w:sdtPr><w:sdtContent>{para(run('Bound'))}</w:sdtContent></w:sdt>",
    )


def _glossary(parts: Parts) -> None:
    parts["word/glossary/document.xml"] = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        f'<w:glossaryDocument xmlns:w="{_W}"><w:docParts><w:docPart><w:docPartBody>'
        f"{para(run(HIDDEN))}</w:docPartBody></w:docPart></w:docParts></w:glossaryDocument>"
    )
    _insert(
        parts,
        "word/_rels/document.xml.rels",
        _RELS,
        _relationships(("rIdG", f"{_REL}/glossaryDocument", "glossary/document.xml")),
    )
    _insert(
        parts,
        "[Content_Types].xml",
        _TYPES,
        f'<Override PartName="/word/glossary/document.xml" '
        f'ContentType="{_WML}.document.glossary+xml"/>',
    )


def _external_relationships(parts: Parts) -> None:
    parts["word/_rels/settings.xml.rels"] = _rels_xml(
        _relationships(
            ("rIdT", f"{_REL}/attachedTemplate", f"file:///Users/{HIDDEN}/Template.dotx"),
            external=True,
        )
    )
    _insert(parts, "word/settings.xml", _SETTINGS, '<w:attachedTemplate r:id="rIdT"/>')


HIDDEN_BUILDERS: dict[str, Callable[[Parts], None]] = {
    "tracked_changes": _tracked,
    "hidden_text": _hidden_text,
    "comments": _comments,
    "embedded_files": _embedded_files,
    "imported_chunks": _imported_chunks,
    "custom_xml": _custom_xml,
    "glossary": _glossary,
    "external_relationships": _external_relationships,
}


def with_hidden(*categories: str) -> bytes:
    parts = _base_parts()
    for category in categories:
        HIDDEN_BUILDERS[category](parts)
    return pack(parts)


def decompressed(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def appears(value: str, data: bytes) -> bool:
    """True if ``value`` is anywhere in any decompressed part, in NFC or NFD bytes."""
    forms = {unicodedata.normalize(form, value).encode("utf-8") for form in ("NFC", "NFD")}
    return any(form in part for part in decompressed(data).values() for form in forms)
