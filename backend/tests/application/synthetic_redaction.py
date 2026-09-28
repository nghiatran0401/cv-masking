# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Synthetic PDFs for Stage 10 redaction. Generated at test time; never commit the bytes.

PYTEST_DONT_REWRITE
"""

import io
import re
from collections.abc import Callable

import pymupdf

NAME = "Nguyễn Văn Mẫu"
EMAIL = "mau.nguyen@example.test"
PHONE = "0900000000"
SALARY = "20.000.000 VND"
COMPANY = "Example Bank Ltd"
ABOVE = "Alpha Bravo Charlie"
TARGET = "Delta"
AFTER_TARGET = "Echo Foxtrot"
BELOW = "Golf Hotel India"
HIDDEN = "Hidden synthetic secret"
AUTHOR = "Jane Example"
ALT_TEXT = "John Sample"
BODY = "Kinh nghiệm làm việc tại Example Bank Ltd với Python và SQL"


def _bytes(document: pymupdf.Document) -> bytes:
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def _image(page: pymupdf.Page, rect: pymupdf.Rect, oc: int = 0) -> None:
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 8, 8), 0)
    pixmap.clear_with(90)
    page.insert_image(rect, pixmap=pixmap, oc=oc)


IMAGE_RECT = pymupdf.Rect(400, 600, 460, 660)


LINKEDIN = "https://linkedin.com/in/mau-example"
GITHUB = "https://github.com/mau-example"
DOB = "01/01/1990"


def contact_header_cv() -> bytes:
    """One contact line with email, phone, DOB, and two URLs, then work years.

    Designed CVs often put those fields on one extracted line; employment dates
    must stay after the DOB is labelled.
    """
    document = pymupdf.open()
    page = document.new_page()
    page.insert_htmlbox(pymupdf.Rect(40, 30, 560, 70), f'<p style="font-size:22px">{NAME}</p>')
    page.insert_htmlbox(
        pymupdf.Rect(40, 80, 560, 130),
        f"<p>Email: {EMAIL} | Phone: {PHONE} | Date of birth: {DOB} | "
        f"LinkedIn: {LINKEDIN} | GitHub: {GITHUB}</p>",
    )
    page.insert_htmlbox(
        pymupdf.Rect(40, 160, 560, 230),
        f"<p>Experience</p><p>{COMPANY} 2019-2023 Python</p>",
    )
    return _bytes(document)


def profile_slug_cv() -> bytes:
    """Display name redacted; LinkedIn/GitHub path still contains the folded name.

    D-43 keeps those URLs visible. Verification must not treat the slug as a leftover name.
    """
    document = pymupdf.open()
    page = document.new_page()
    page.insert_htmlbox(pymupdf.Rect(40, 30, 560, 70), f'<p style="font-size:22px">{NAME}</p>')
    page.insert_htmlbox(
        pymupdf.Rect(40, 80, 560, 160),
        "<p>Email: "
        f"{EMAIL}</p><p>Phone: {PHONE}</p>"
        "<p>LinkedIn: linkedin.com/in/nguyen-van-mau-example</p>"
        "<p>GitHub: github.com/nguyenvanmau-example</p>",
    )
    page.insert_htmlbox(
        pymupdf.Rect(40, 180, 560, 250),
        f"<p>Experience</p><p>{COMPANY} 2019-2023 Python</p>",
    )
    return _bytes(document)


WESTERN_NAME = "Mau Nguyen"
WESTERN_EMAIL = "thmau0401@example.test"


def unlabeled_header_cv() -> bytes:
    """Centered display name with no Name: label, then a bullet contact row.

    Designed CVs put the name in a large font and the phone/email/URLs on the
    next line; tight spacing often extracts as one line.
    """
    document = pymupdf.open()
    page = document.new_page()
    page.insert_htmlbox(
        pymupdf.Rect(40, 36, 560, 78),
        f'<p style="font-size:28px;text-align:center">{WESTERN_NAME}</p>',
    )
    page.insert_htmlbox(
        pymupdf.Rect(40, 80, 560, 108),
        f"<p style='font-size:11px;text-align:center'>"
        f"{PHONE} • {WESTERN_EMAIL} • {LINKEDIN} • {GITHUB}</p>",
    )
    page.insert_htmlbox(
        pymupdf.Rect(40, 140, 560, 220),
        f"<p>Experience</p><p>{COMPANY} 2019-2023 Python</p>",
    )
    return _bytes(document)


ALL_CAPS_NAME = "NGUYEN VAN MAU ANH"
JOB_TITLE = "Software Developer"


def all_caps_title_cv() -> bytes:
    """All-caps four-token header with a job title tight underneath.

    Designed CVs often extract those two lines as one, so the title must not
    swallow the name.
    """
    document = pymupdf.open()
    page = document.new_page()
    page.insert_htmlbox(
        pymupdf.Rect(40, 30, 560, 78),
        f'<p style="font-size:28px;text-align:center">{ALL_CAPS_NAME}</p>',
    )
    page.insert_htmlbox(
        pymupdf.Rect(40, 72, 560, 100),
        f'<p style="font-size:14px;text-align:center">{JOB_TITLE}</p>',
    )
    page.insert_htmlbox(
        pymupdf.Rect(40, 110, 560, 150),
        f"<p>Ho Chi Minh City | Phone: {PHONE} | Email: {EMAIL} | LinkedIn | Github</p>",
    )
    return _bytes(document)


def education_project_cv() -> bytes:
    """Education bullets that contain ``multi-agent`` (must not be read as Age)."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_htmlbox(pymupdf.Rect(40, 30, 560, 70), f'<p style="font-size:22px">{NAME}</p>')
    page.insert_htmlbox(pymupdf.Rect(40, 80, 560, 110), f"<p>Email: {EMAIL} | {PHONE}</p>")
    page.insert_htmlbox(
        pymupdf.Rect(40, 130, 560, 280),
        "<p>Education</p>"
        "<p>Example University Bachelor Computer Science</p>"
        "<p>Cybersecurity Multi-agent System: built a Python service "
        f"for {COMPANY} (Example Conf 2023)</p>",
    )
    return _bytes(document)


def cv_pdf(line_height: float = 1.2) -> bytes:
    """Name, contact line, salary, body text, three tight lines, and an image."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_htmlbox(pymupdf.Rect(50, 30, 550, 70), f'<p style="font-size:22px">{NAME}</p>')
    page.insert_htmlbox(pymupdf.Rect(50, 80, 550, 100), f"<p>Email: {EMAIL} | {PHONE}</p>")
    page.insert_htmlbox(pymupdf.Rect(50, 110, 550, 130), f"<p>Mức lương mong muốn: {SALARY}</p>")
    page.insert_htmlbox(pymupdf.Rect(50, 140, 550, 180), f"<p>{BODY}</p>")
    page.insert_htmlbox(
        pymupdf.Rect(50, 200, 550, 300),
        f"<p style='line-height:{line_height}'>{ABOVE}<br>{TARGET} {AFTER_TARGET}<br>{BELOW}</p>",
    )
    _image(page, IMAGE_RECT)
    return _bytes(document)


def with_always_stripped(data: bytes) -> bytes:
    """Metadata, XMP, a mailto link, outlines, page labels, and a thumbnail."""
    document = pymupdf.open(stream=data, filetype="pdf")
    document.set_metadata({"author": AUTHOR, "title": f"CV {AUTHOR}", "keywords": EMAIL})
    document.set_xml_metadata(
        f'<x:xmpmeta xmlns:x="adobe:ns:meta/"><rdf:RDF xmlns:rdf="http://www.w3.org/1999/'
        f'02/22-rdf-syntax-ns#"><rdf:Description>{AUTHOR}</rdf:Description></rdf:RDF>'
        "</x:xmpmeta>"
    )
    page = document[0]
    page.insert_link(
        {"kind": pymupdf.LINK_URI, "from": pymupdf.Rect(50, 80, 300, 100), "uri": f"mailto:{EMAIL}"}
    )
    document.set_toc([[1, AUTHOR, 1]])
    document.set_page_labels([{"startpage": 0, "prefix": AUTHOR, "style": "D"}])
    thumb = document.get_new_xref()
    document.update_object(
        thumb, "<< /Width 1 /Height 1 /ColorSpace /DeviceGray /BitsPerComponent 8 >>"
    )
    document.update_stream(thumb, b"\x80")
    document.xref_set_key(page.xref, "Thumb", f"{thumb} 0 R")
    _tagged(document, page)
    return _bytes(document)


def _tagged(document: pymupdf.Document, page: pymupdf.Page) -> None:
    """A structure tree with figure alt text, and application private data."""
    root = document.get_new_xref()
    element = document.get_new_xref()
    document.update_object(root, f"<< /Type /StructTreeRoot /K {element} 0 R >>")
    document.update_object(
        element,
        f"<< /Type /StructElem /S /Figure /P {root} 0 R /Pg {page.xref} 0 R /Alt ({ALT_TEXT}) >>",
    )
    catalog = document.pdf_catalog()
    document.xref_set_key(catalog, "StructTreeRoot", f"{root} 0 R")
    document.xref_set_key(catalog, "MarkInfo", "<< /Marked true >>")
    document.xref_set_key(page.xref, "StructParents", "0")
    document.xref_set_key(
        page.xref, "PieceInfo", f"<< /SyntheticApp << /Private ({ALT_TEXT}) >> >>"
    )


def _annotations(document: pymupdf.Document) -> None:
    document[0].add_text_annot(pymupdf.Point(300, 400), HIDDEN)
    document[0].add_freetext_annot(pymupdf.Rect(300, 420, 500, 450), HIDDEN)


def _embedded_files(document: pymupdf.Document) -> None:
    document.embfile_add("synthetic-attachment.txt", HIDDEN.encode())


def _forms(document: pymupdf.Document) -> None:
    widget = pymupdf.Widget()
    widget.field_type = pymupdf.PDF_WIDGET_TYPE_TEXT
    widget.field_name = "synthetic_field"
    widget.field_value = HIDDEN
    widget.rect = pymupdf.Rect(300, 460, 500, 480)
    document[0].add_widget(widget)


def _javascript(document: pymupdf.Document) -> None:
    xref = document.get_new_xref()
    document.update_object(xref, "<< /S /JavaScript /JS (app.alert(1);) >>")
    document.xref_set_key(document.pdf_catalog(), "OpenAction", f"{xref} 0 R")
    launch = document.get_new_xref()
    document.update_object(launch, "<< /S /Launch /F (synthetic.exe) >>")
    document.xref_set_key(document[0].xref, "AA", f"<< /O {launch} 0 R >>")


def _optional_content(document: pymupdf.Document) -> None:
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    page = document[0]
    page.insert_text((300, 520), HIDDEN, fontsize=11, oc=ocg)
    page.draw_rect(pymupdf.Rect(300, 530, 340, 560), color=(1, 0, 0), oc=ocg)
    _image(page, pymupdf.Rect(480, 600, 540, 660), oc=ocg)


def _add_hidden_ocmd(document: pymupdf.Document, *, policy: str = "AllOn") -> int:
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    return document.set_ocmd(ocgs=[ocg], policy=policy)


def with_ocmd_allon(data: bytes) -> bytes:
    """Hidden OCMD AllOn of an off group: MuPDF draws it, the PDF rules hide it."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocmd = _add_hidden_ocmd(document)
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    return _bytes(document)


def with_inline_oc_property(data: bytes) -> bytes:
    """Named ``/Properties`` entry holds the OCMD dict itself (Canva/Figma style)."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocmd = _add_hidden_ocmd(document)
    page = document[0]
    page.insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    _inline_named_ocmd(document, page, ocmd)
    return _bytes(document)


def with_inline_bdc_oc(data: bytes) -> bytes:
    """Content stream uses ``/OC << /Type /OCMD ... >> BDC`` instead of a name."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    ocmd = document.set_ocmd(ocgs=[ocg], policy="AllOn")
    page = document[0]
    page.insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    contents = page.read_contents()
    inline = f"<< /Type /OCMD /OCGs [{ocg} 0 R] /P /AllOn >>".encode()
    replaced = re.sub(rb"/OC /[^\s]+ BDC", b"/OC " + inline + b" BDC", contents, count=1)
    if replaced == contents:
        raise AssertionError("synthetic fixture did not find an OC BDC marker")
    xref = document.get_new_xref()
    document.update_object(xref, "<<>>")
    document.update_stream(xref, replaced)
    page.set_contents(xref)
    return _bytes(document)


def with_inline_xobject_oc(data: bytes) -> bytes:
    """Image XObject carries an inline OCMD dict on ``/OC``."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    page = document[0]
    _image(page, pymupdf.Rect(480, 600, 540, 660), oc=ocg)
    images = page.get_images(full=True)
    if not images:
        raise AssertionError("synthetic fixture did not embed an image")
    document.xref_set_key(images[0][0], "OC", f"<< /Type /OCMD /OCGs [{ocg} 0 R] /P /AllOn >>")
    return _bytes(document)


def with_nested_ocmd(data: bytes) -> bytes:
    """OCMD whose ``/OCGs`` array points at another OCMD, not an OCG."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    inner = document.set_ocmd(ocgs=[ocg], policy="AllOn")
    outer = document.get_new_xref()
    document.update_object(outer, f"<< /Type /OCMD /OCGs [{inner} 0 R] /P /AllOn >>")
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=outer)
    return _bytes(document)


def with_ocmd_ve_and(data: bytes) -> bytes:
    """VE ``And`` of an off group is hidden (same outcome as AllOn)."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    ocmd = document.set_ocmd(ocgs=[ocg], ve=["and", ocg])
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    return _bytes(document)


def with_ocmd_ve_not_visible(data: bytes) -> bytes:
    """VE ``Not`` of an off group is visible and must stay."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    ocmd = document.set_ocmd(ocgs=[ocg], ve=["not", ocg])
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    return _bytes(document)


def with_unsupported_ve(data: bytes) -> bytes:
    """Xor is not a PDF visibility operator; the block must be over-stripped."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    ocmd = document.set_ocmd(ocgs=[ocg], policy="AllOn")
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    document.update_object(ocmd, f"<< /Type /OCMD /VE [ /Xor {ocg} 0 R ] >>")
    return _bytes(document)


def with_indirect_ocmd_ocgs(data: bytes) -> bytes:
    """OCMD ``/OCGs`` is an indirect array, a form Canva-style exporters use."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    ocmd = document.set_ocmd(ocgs=[ocg], policy="AllOn")
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    array = document.get_new_xref()
    document.update_object(array, f"[{ocg} 0 R]")
    document.update_object(ocmd, f"<< /Type /OCMD /OCGs {array} 0 R /P /AllOn >>")
    return _bytes(document)


def with_indirect_ocmd_ve(data: bytes) -> bytes:
    """Visibility expression stored as an indirect array."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    ocmd = document.set_ocmd(ocgs=[ocg], ve=["and", ocg])
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    array = document.get_new_xref()
    document.update_object(array, f"[ /And {ocg} 0 R ]")
    document.update_object(ocmd, f"<< /Type /OCMD /VE {array} 0 R >>")
    return _bytes(document)


def with_unknown_oc_name(data: bytes) -> bytes:
    """Stream names a Properties key that does not exist; treat the block as hidden."""
    document = pymupdf.open(stream=data, filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    page = document[0]
    page.insert_text((300, 520), HIDDEN, fontsize=11, oc=ocg)
    contents = page.read_contents()
    replaced = re.sub(rb"/OC /[^\s]+ BDC", b"/OC /Ghost BDC", contents, count=1)
    if replaced == contents:
        raise AssertionError("synthetic fixture did not find an OC BDC marker")
    xref = document.get_new_xref()
    document.update_object(xref, "<<>>")
    document.update_stream(xref, replaced)
    page.set_contents(xref)
    return _bytes(document)


def with_cyclic_ocmd(data: bytes) -> bytes:
    """Two OCMDs that name each other; membership cannot be walked."""
    document = pymupdf.open(stream=data, filetype="pdf")
    document.add_ocg("Synthetic unused off layer", on=False)
    first = document.get_new_xref()
    second = document.get_new_xref()
    document.update_object(first, f"<< /Type /OCMD /OCGs [{second} 0 R] /P /AllOn >>")
    document.update_object(second, f"<< /Type /OCMD /OCGs [{first} 0 R] /P /AllOn >>")
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=first)
    return _bytes(document)


def with_visible_and_hidden_layers(data: bytes) -> bytes:
    document = pymupdf.open(stream=data, filetype="pdf")
    page = document[0]
    visible = document.add_ocg("Synthetic visible layer", on=True)
    hidden = document.add_ocg("Synthetic hidden layer", on=False)
    page.insert_text((40, 780), "Keep visible layer", fontsize=11, oc=visible)
    page.insert_text((300, 520), HIDDEN, fontsize=11, oc=hidden)
    return _bytes(document)


def _inline_named_ocmd(document: pymupdf.Document, page: pymupdf.Page, ocmd: int) -> None:
    kind, value = document.xref_get_key(page.xref, "Resources")
    if kind != "xref":
        raise AssertionError("synthetic page resources are not an indirect dict")
    res_xref = int(value.split()[0])
    raw = document.xref_object(res_xref)
    needle = f"/MC0 {ocmd} 0 R"
    if needle not in raw:
        # PyMuPDF names the first OC property MC0; accept MC<n>.
        match = re.search(rf"/MC\d+ {ocmd} 0 R", raw)
        if match is None:
            raise AssertionError("synthetic fixture did not find the OC property")
        needle = match.group(0)
    replacement = needle.split()[0] + " " + document.xref_object(ocmd)
    document.update_object(res_xref, raw.replace(needle, replacement))


def _invisible_text(document: pymupdf.Document) -> None:
    page = document[0]
    page.insert_text((300, 700), HIDDEN, fontsize=11, render_mode=3)
    page.insert_text((300, 720), HIDDEN, fontsize=1.0)
    page.insert_text((300, 740), HIDDEN, fontsize=11, color=(1, 1, 1))


HIDDEN_BUILDERS: dict[str, Callable[[pymupdf.Document], None]] = {
    "annotations": _annotations,
    "embedded_files": _embedded_files,
    "forms": _forms,
    "javascript": _javascript,
    "optional_content": _optional_content,
    "invisible_text": _invisible_text,
}


def with_hidden(data: bytes, *categories: str) -> bytes:
    document = pymupdf.open(stream=data, filetype="pdf")
    for category in categories:
        HIDDEN_BUILDERS[category](document)
    return _bytes(document)


def image_digests(data: bytes) -> list[tuple[int, int, bytes]]:
    """Size and decoded samples of every image; the output may recompress the stream."""
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        found: list[tuple[int, int, bytes]] = []
        for page in document:
            for item in page.get_images(full=True):
                xref, width, height = item[0], item[2], item[3]
                found.append((width, height, document.xref_stream(xref)))
        return found
    finally:
        document.close()


def visible_words(data: bytes, page_number: int = 1) -> list[str]:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        return [item[4] for item in document[page_number - 1].get_text("words", sort=True)]
    finally:
        document.close()


def all_text(data: bytes) -> str:
    """Text of every page, including text a viewer hides, for leak checks."""
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        return "".join(page.get_text("text") for page in document) + "".join(
            str(item.get("text") or "") for page in document for item in page.get_texttrace()
        )
    finally:
        document.close()
