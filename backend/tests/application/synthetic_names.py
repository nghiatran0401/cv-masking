"""Synthetic name, family, and contact-block fixtures. Only policy-approved people.

Confounders (companies, universities, titles, cities) use the synthetic
organisations from docs/masking-policy.md §3 or clearly invented names.
"""

from collections.abc import Sequence

from cv_masking.domain.findings import BoundingBox
from cv_masking.domain.formats import DocumentFormat
from cv_masking.ports.extraction import ExtractedDocument, TextPart, TextSpan

VN_NAME = "Nguyễn Văn Mẫu"
VN_NAME_FOLDED = "Nguyen Van Mau"
VN_NAME_UPPER = "NGUYỄN VĂN MẪU"
VN_NAME_SHORT = "Mẫu Nguyễn"
VN_REFEREE = "Trần Thị Thử"
EN_NAME = "Jane Example"
EN_REFEREE = "John Sample"
VN_COMPANY = "Công ty TNHH Ví Dụ"
EN_COMPANY = "Example Bank Ltd"
VN_UNIVERSITY = "Đại học Ví Dụ"
EN_UNIVERSITY = "Example University"
VN_EMAIL = "mau.nguyen@example.test"
EN_EMAIL = "jane.example@example.invalid"
UNRELATED_EMAIL = "hr@example.test"
VN_ADDRESS = "Số 1 đường Ví Dụ, phường Mẫu, quận Thử"
EN_ADDRESS = "1 Example Street, Sample Ward, Test District"
FAMILY_LINE = "Bố: Trần Thị Thử - 1960 - Hưu trí"
FAMILY_LINE_2 = "Mẹ: Jane Example - 1962 - Nội trợ"

_BODY_HEIGHT = 10.0
_TITLE_HEIGHT = 20.0


def docx(*paragraphs: str, part_name: str = "word/document.xml") -> ExtractedDocument:
    return docx_parts({part_name: paragraphs})


def docx_parts(parts: dict[str, Sequence[str]]) -> ExtractedDocument:
    built: list[TextPart] = []
    for name, paragraphs in parts.items():
        text = "\n".join(paragraphs)
        spans = (TextSpan(0, len(text), ()),) if text else ()
        built.append(TextPart(text, spans, part_name=name))
    return ExtractedDocument(DocumentFormat.DOCX, tuple(built))


def pdf(*pages: Sequence[tuple[str, float]]) -> ExtractedDocument:
    """Pages of ``(line, word_height)``; one span and box per word like the PDF adapter."""
    built: list[TextPart] = []
    for number, lines in enumerate(pages, start=1):
        text_parts: list[str] = []
        spans: list[TextSpan] = []
        offset = 0
        y = 0.0
        for line_index, (line, height) in enumerate(lines):
            if line_index:
                text_parts.append("\n")
                offset += 1
            x = 0.0
            for word_index, word in enumerate(line.split(" ")):
                if word_index:
                    text_parts.append(" ")
                    offset += 1
                width = max(1.0, len(word) * height * 0.5)
                spans.append(
                    TextSpan(
                        offset, offset + len(word), (BoundingBox(x, y, x + width, y + height),)
                    )
                )
                text_parts.append(word)
                offset += len(word)
                x += width + 3.0
            y += height + 6.0
        built.append(TextPart("".join(text_parts), tuple(spans), page_number=number))
    return ExtractedDocument(DocumentFormat.PDF, tuple(built))


def title(line: str) -> tuple[str, float]:
    return line, _TITLE_HEIGHT


def body(line: str) -> tuple[str, float]:
    return line, _BODY_HEIGHT


def span_of(text: str, value: str, occurrence: int = 0) -> tuple[int, int]:
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(value, start + 1)
    return start, start + len(value)
