# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Synthetic PDFs for Stage 10 redaction. Generated at test time; never commit the bytes.

PYTEST_DONT_REWRITE
"""

import io
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
    return _bytes(document)


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
