import logging
from collections.abc import Callable

import pytest
from service_helpers import uploaded_document
from synthetic_files import SYNTHETIC_PDF, synthetic_docx

# Load pymupdf via this helper first. Importing it from a pytest-rewritten
# module (conftest or test_*) segfaults PyMuPDF 1.28 on macOS.
from synthetic_pdfs import (
    CELL,
    EMAIL,
    HEADER,
    SCHOOL,
    SKILL,
    ZERO_PAGE_PDF,
    encrypted_pdf,
    hidden_content_pdf,
    image_only_pdf,
    many_pages_pdf,
    supported_layouts_pdf,
)

from cv_masking.adapters.docx import DocxExtractor
from cv_masking.adapters.local_storage import LocalInputStore
from cv_masking.adapters.pdf import PyMuPDFExtractor
from cv_masking.application import JobService, ValidationService
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.ports.extraction import ExtractionResult


@pytest.fixture
def extractor() -> PyMuPDFExtractor:
    return PyMuPDFExtractor()


@pytest.fixture
def validation(
    service: JobService, input_store: LocalInputStore, extractor: PyMuPDFExtractor
) -> ValidationService:
    return ValidationService(
        service,
        input_store,
        {DocumentFormat.PDF: extractor, DocumentFormat.DOCX: DocxExtractor()},
    )


def _combined(result: ExtractionResult) -> str:
    if result.document is None:
        return ""
    return "\n".join(part.text for part in result.document.parts)


def test_extracts_supported_layouts_deterministically(extractor: PyMuPDFExtractor) -> None:
    data = supported_layouts_pdf()
    first = extractor.extract(data)
    second = extractor.extract(data)
    assert first.document is not None
    assert second.document is not None
    combined = _combined(first)
    assert HEADER in combined
    assert SKILL in combined
    assert SCHOOL in combined
    assert CELL in combined
    assert combined.count(EMAIL) == 2
    assert "Mau" in combined
    assert all(part.spans and part.spans[0].boxes for part in first.document.parts)
    assert [part.text for part in first.document.parts] == [
        part.text for part in second.document.parts
    ]
    assert [part.spans for part in first.document.parts] == [
        part.spans for part in second.document.parts
    ]


@pytest.mark.parametrize(
    ("builder", "failure", "review"),
    [
        (encrypted_pdf, None, ReviewReason.PDF_ENCRYPTED),
        (lambda: ZERO_PAGE_PDF, ErrorCode.PDF_NO_PAGES, None),
        (many_pages_pdf, None, ReviewReason.PDF_TOO_MANY_PAGES),
        (image_only_pdf, None, ReviewReason.PDF_NO_TEXT_LAYER),
        (lambda: SYNTHETIC_PDF, ErrorCode.PDF_MALFORMED, None),
    ],
    ids=("encrypted", "zero_page", "too_many_pages", "image_only", "malformed"),
)
def test_classifies_unsupported_pdfs(
    extractor: PyMuPDFExtractor,
    builder: Callable[[], bytes],
    failure: ErrorCode | None,
    review: ReviewReason | None,
) -> None:
    result = extractor.extract(builder())
    assert result.document is None
    assert result.failure is failure
    assert result.review == (frozenset({review}) if review is not None else frozenset())


def test_hidden_content_holds_the_document_without_leaking_text(
    service: JobService, input_store: LocalInputStore, validation: ValidationService
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id, content=hidden_content_pdf())
    outcome = validation.validate(job.document_id)
    assert outcome.job.state is DocumentState.REVIEW_REQUIRED
    assert outcome.job.review_reasons == frozenset({ReviewReason.PDF_HIDDEN_CONTENT})
    kinds = {alert.category for alert in outcome.alerts}
    assert HiddenContentCategory.ANNOTATIONS in kinds
    assert HiddenContentCategory.EMBEDDED_FILES in kinds
    dumped = repr(outcome.alerts)
    for fragment in ("Nguyen", "secret", "never leak", "app.alert"):
        assert fragment not in dumped


def test_validate_queues_a_supported_pdf_without_logging_text(
    service: JobService,
    input_store: LocalInputStore,
    validation: ValidationService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id, content=supported_layouts_pdf())
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        outcome = validation.validate(job.document_id)
    assert outcome.job.state is DocumentState.QUEUED
    assert outcome.extracted is not None
    assert EMAIL in "\n".join(part.text for part in outcome.extracted.parts)
    combined = " ".join(record.getMessage() for record in caplog.records)
    for fragment in ("Nguyen", EMAIL, "Mau"):
        assert fragment not in combined


def test_validate_fails_a_malformed_pdf(
    service: JobService, input_store: LocalInputStore, validation: ValidationService
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id, content=SYNTHETIC_PDF)
    outcome = validation.validate(job.document_id)
    assert outcome.job.state is DocumentState.FAILED
    assert outcome.job.error_code is ErrorCode.PDF_MALFORMED
    assert outcome.extracted is None


def test_validate_queues_a_simple_docx(
    service: JobService, input_store: LocalInputStore, validation: ValidationService
) -> None:
    batch = service.create_batch()
    job = uploaded_document(
        service, input_store, batch.batch_id, DocumentFormat.DOCX, synthetic_docx()
    )
    outcome = validation.validate(job.document_id)
    assert outcome.job.state is DocumentState.QUEUED
    assert outcome.extracted is not None
    assert "synthetic" in "\n".join(part.text for part in outcome.extracted.parts)
