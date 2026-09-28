# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Synthetic annotated CVs for Stage 16. Values are policy-approved and never reported."""

from __future__ import annotations

import io
import zipfile
from typing import Final

import pymupdf

from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.policy import EntityType

EMAIL: Final = "mau.nguyen@example.test"
PHONE: Final = "0900000000"
CCCD: Final = "000000000012"
CMND: Final = "000000003"
PASSPORT: Final = "A0000001"
URL: Final = "https://linkedin.com/in/mau-example"
REF_EMAIL: Final = "jane.example@example.invalid"
NAME: Final = "Nguyen Van Mau"
REFEREE: Final = "John Sample"
ADDRESS: Final = "12 Pho Mau, Ha Noi"
DOB: Final = "01/01/1990"
SALARY: Final = "20.000.000 VND"
FAMILY: Final = "Bo: Tran Thi Thu - 1960 - Huu tri"
COMPANY: Final = "Example Bank Ltd"

SENTINELS: Final = (
    EMAIL,
    PHONE,
    CCCD,
    CMND,
    PASSPORT,
    URL,
    REF_EMAIL,
    NAME,
    REFEREE,
    ADDRESS,
    DOB,
    SALARY,
    FAMILY,
    "Nguyen",
    "Mẫu",
    "0900000000",
)

ANNOTATIONS: Final = (
    (EntityType.CANDIDATE_NAME, NAME),
    (EntityType.EMAIL, EMAIL),
    (EntityType.PHONE, PHONE),
    (EntityType.NATIONAL_ID, CCCD),
    (EntityType.NATIONAL_ID, CMND),
    (EntityType.PASSPORT, PASSPORT),
    (EntityType.GENDER, "Nam"),
    (EntityType.MARITAL_STATUS, "Doc than"),
    (EntityType.NATIONALITY, "Viet Nam"),
    (EntityType.RELIGION, "Khong"),
    (EntityType.ETHNICITY, "Kinh"),
    (EntityType.HEALTH, "170 cm"),
    (EntityType.POSTAL_ADDRESS, ADDRESS),
    (EntityType.DATE_OF_BIRTH, DOB),
    (EntityType.SALARY, SALARY),
    (EntityType.PERSONAL_URL, URL),
    (EntityType.FAMILY_DETAILS, FAMILY),
    (EntityType.REFERENCE_NAME, REFEREE),
    (EntityType.EMAIL, REF_EMAIL),
)

_CV_LINES: Final = (
    f"Ho va ten: {NAME}",
    f"Email: {EMAIL}",
    f"Dien thoai: {PHONE}",
    f"CCCD: {CCCD}",
    f"CMND: {CMND}",
    f"Ho chieu: {PASSPORT}",
    "Gioi tinh: Nam",
    "Hon nhan: Doc than",
    "Quoc tich: Viet Nam",
    "Ton giao: Khong",
    "Dan toc: Kinh",
    "Chieu cao: 170 cm",
    f"Dia chi: {ADDRESS}",
    f"Ngay sinh: {DOB}",
    f"Muc luong: {SALARY}",
    f"LinkedIn: {URL}",
    "Thong tin gia dinh",
    FAMILY,
    "Nguoi tham chieu",
    REFEREE,
    f"Lien he: {REF_EMAIL}",
    "Experience",
    f"{COMPANY} 2019-2023 Python",
)


def cv_text() -> str:
    return "\n".join(_CV_LINES)


def annotated_pdf() -> bytes:
    """Labeled synthetic CV plus a 16x16 image (D-13: images stay)."""
    document = pymupdf.open()
    page = document.new_page()
    page.insert_htmlbox(pymupdf.Rect(40, 40, 560, 720), "<br/>".join(_CV_LINES))
    pixmap = pymupdf.Pixmap(pymupdf.csRGB, pymupdf.IRect(0, 0, 16, 16), 0)
    pixmap.clear_with(180)
    page.insert_image(pymupdf.Rect(500, 40, 540, 80), pixmap=pixmap)
    buffer = io.BytesIO()
    document.save(buffer)
    document.close()
    return buffer.getvalue()


def malformed_pdf() -> bytes:
    return b"%PDF-not-a-real-file Nguyen"


def annotated_docx() -> bytes:
    wml = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body = "".join(
        f"<w:p><w:r><w:t xml:space='preserve'>{line}</w:t></w:r></w:p>" for line in _CV_LINES
    )
    document = (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<w:document xmlns:w="{wml}"><w:body>{body}</w:body></w:document>'
    )
    types = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="xml" ContentType="application/xml"/>'
        '<Default Extension="rels" '
        'ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Override PartName="/word/document.xml" ContentType="'
        'application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
        "</Types>"
    )
    rels = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
        '<Relationship Id="rId1" Type="'
        'http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
        'Target="word/document.xml"/>'
        "</Relationships>"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", types)
        archive.writestr("_rels/.rels", rels)
        archive.writestr("word/document.xml", document)
    return buffer.getvalue()


def malformed_docx() -> bytes:
    return b"PK\x03\x04not-a-docx"


def magic_format(data: bytes) -> DocumentFormat | None:
    if data.startswith(b"%PDF"):
        return DocumentFormat.PDF
    if data.startswith(b"PK"):
        return DocumentFormat.DOCX
    return None
