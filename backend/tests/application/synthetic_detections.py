"""Synthetic CV snippets and gold spans. Values stay out of test names."""

from cv_masking.domain.findings import BoundingBox
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.policy import EntityType
from cv_masking.ports.extraction import ExtractedDocument, TextPart, TextSpan

EMAIL = "mau.nguyen@example.test"
PHONE = "0900000000"
PHONE_PLUS = "+84 90 000 0000"
LANDLINE = "02400000000"
CCCD = "000000000012"
CMND = "000000003"
PASSPORT = "A0000001"
URL = "https://linkedin.com/in/mau-example"
REF_EMAIL = "jane.example@example.invalid"


def extracted(text: str, *, fmt: DocumentFormat = DocumentFormat.DOCX) -> ExtractedDocument:
    spans: tuple[TextSpan, ...]
    if text:
        boxes = (BoundingBox(0.0, 0.0, 12.0, 12.0),) if fmt is DocumentFormat.PDF else ()
        spans = (TextSpan(0, len(text), boxes),)
    else:
        spans = ()
    if fmt is DocumentFormat.DOCX:
        part = TextPart(text, spans, part_name="word/document.xml")
    else:
        part = TextPart(text, spans, page_number=1)
    return ExtractedDocument(fmt, (part,))


def gold_span(text: str, value: str) -> tuple[int, int]:
    start = text.index(value)
    return start, start + len(value)


def corpus() -> tuple[ExtractedDocument, list[tuple[EntityType, int, int]]]:
    lines = (
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
        "Dia chi: 12 Pho Mau, Ha Noi",
        "Ngay sinh: 01/01/1990",
        "Muc luong: 20.000.000 VND",
        f"LinkedIn: {URL}",
        "Nguoi tham chieu",
        f"Lien he: {REF_EMAIL}",
        "Kinh nghiem",
        "Example Bank Ltd 2019-2023",
    )
    text = "\n".join(lines)
    expected = [
        (EntityType.EMAIL, *gold_span(text, EMAIL)),
        (EntityType.PHONE, *gold_span(text, PHONE)),
        (EntityType.NATIONAL_ID, *gold_span(text, CCCD)),
        (EntityType.NATIONAL_ID, *gold_span(text, CMND)),
        (EntityType.PASSPORT, *gold_span(text, PASSPORT)),
        (EntityType.GENDER, *gold_span(text, "Nam")),
        (EntityType.MARITAL_STATUS, *gold_span(text, "Doc than")),
        (EntityType.NATIONALITY, *gold_span(text, "Viet Nam")),
        (EntityType.RELIGION, *gold_span(text, "Khong")),
        (EntityType.ETHNICITY, *gold_span(text, "Kinh")),
        (EntityType.HEALTH, *gold_span(text, "170 cm")),
        (EntityType.POSTAL_ADDRESS, *gold_span(text, "12 Pho Mau, Ha Noi")),
        (EntityType.DATE_OF_BIRTH, *gold_span(text, "01/01/1990")),
        (EntityType.SALARY, *gold_span(text, "20.000.000 VND")),
        (EntityType.PERSONAL_URL, *gold_span(text, URL)),
        (EntityType.EMAIL, *gold_span(text, REF_EMAIL)),
    ]
    return extracted(text), expected
