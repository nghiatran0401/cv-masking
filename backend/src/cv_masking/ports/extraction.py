"""Format-neutral extracted text. Transient only: never persisted or logged."""

from dataclasses import dataclass
from typing import Protocol

from cv_masking.domain._validation import require_int
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import BoundingBox
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentAlert
from cv_masking.domain.limits import HARD_MAX_PDF_PAGES


@dataclass(frozen=True, slots=True)
class TextSpan:
    """Half-open range [start, end) in the part text, with PDF boxes when known."""

    start: int
    end: int
    boxes: tuple[BoundingBox, ...]

    def __post_init__(self) -> None:
        require_int(self.start, "TextSpan.start", minimum=0)
        require_int(self.end, "TextSpan.end", minimum=1)
        if self.end <= self.start:
            raise InvariantError("TextSpan.end must be greater than start")
        if not isinstance(self.boxes, tuple) or not all(
            isinstance(box, BoundingBox) for box in self.boxes
        ):
            raise InvariantError("TextSpan.boxes must contain BoundingBox values")


@dataclass(frozen=True, slots=True)
class TextPart:
    """One PDF page or one DOCX part, in reading order, Unicode NFC."""

    text: str
    spans: tuple[TextSpan, ...]
    page_number: int | None = None
    part_name: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.text, str):
            raise InvariantError("TextPart.text must be a string")
        if not isinstance(self.spans, tuple) or not all(
            isinstance(span, TextSpan) for span in self.spans
        ):
            raise InvariantError("TextPart.spans must contain TextSpan values")
        has_page = self.page_number is not None
        has_part = self.part_name is not None
        if has_page == has_part:
            raise InvariantError("TextPart needs either page_number or part_name")
        if has_page:
            require_int(
                self.page_number, "TextPart.page_number", minimum=1, maximum=HARD_MAX_PDF_PAGES
            )
        for span in self.spans:
            if span.end > len(self.text):
                raise InvariantError("TextSpan is outside TextPart.text")


@dataclass(frozen=True, slots=True)
class ExtractedDocument:
    document_format: DocumentFormat
    parts: tuple[TextPart, ...]
    hidden: tuple[HiddenContentAlert, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.document_format, DocumentFormat):
            raise InvariantError("ExtractedDocument.document_format must be a DocumentFormat")
        if not isinstance(self.parts, tuple) or not self.parts:
            raise InvariantError("ExtractedDocument.parts must be a non-empty tuple")
        if not all(isinstance(part, TextPart) for part in self.parts):
            raise InvariantError("ExtractedDocument.parts must contain TextPart values")
        if not isinstance(self.hidden, tuple) or not all(
            isinstance(alert, HiddenContentAlert) for alert in self.hidden
        ):
            raise InvariantError("ExtractedDocument.hidden must contain HiddenContentAlert values")


@dataclass(frozen=True, slots=True)
class ExtractionResult:
    """Exactly one of: extracted document, a failure code, or review reasons."""

    document: ExtractedDocument | None = None
    failure: ErrorCode | None = None
    review: frozenset[ReviewReason] = frozenset()
    alerts: tuple[HiddenContentAlert, ...] = ()

    def __post_init__(self) -> None:
        outcomes = (
            self.document is not None,
            self.failure is not None,
            bool(self.review),
        )
        if sum(outcomes) != 1:
            raise InvariantError("ExtractionResult needs exactly one outcome")
        if self.failure is not None and not isinstance(self.failure, ErrorCode):
            raise InvariantError("ExtractionResult.failure must be an ErrorCode")
        if not isinstance(self.review, frozenset) or not all(
            isinstance(reason, ReviewReason) for reason in self.review
        ):
            raise InvariantError("ExtractionResult.review must be ReviewReason values")
        if not isinstance(self.alerts, tuple) or not all(
            isinstance(alert, HiddenContentAlert) for alert in self.alerts
        ):
            raise InvariantError("ExtractionResult.alerts must contain HiddenContentAlert values")
        if self.document is not None and self.alerts:
            raise InvariantError("a successful extract reports hidden content on the document")


class DocumentExtractor(Protocol):
    def extract(self, data: bytes) -> ExtractionResult:
        """Classify and, if supported, extract text. Never logs or stores ``data``."""
        ...
