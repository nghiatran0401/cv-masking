import logging
from collections.abc import Callable

import pytest
from service_helpers import uploaded_document
from synthetic_docxs import (
    CELL,
    CONTROLLED,
    CORE_CREATOR,
    EMAIL,
    FOOTNOTE,
    HEADER,
    SKILL,
    dtd_docx,
    empty_docx,
    encrypted_docx,
    hidden_comments_docx,
    hidden_tracked_docx,
    hidden_vanish_docx,
    oversized_docx,
    supported_layouts_docx,
    traversal_docx,
    zip_bomb_docx,
)
from synthetic_files import SYNTHETIC_PDF, synthetic_docx

from cv_masking.adapters.docx import DocxExtractor
from cv_masking.adapters.local_storage import LocalInputStore
from cv_masking.application import JobService, ValidationService
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.ports.extraction import ExtractionResult


def _combined(result: ExtractionResult) -> str:
    if result.document is None:
        return ""
    return "\n".join(part.text for part in result.document.parts)


@pytest.fixture
def extractor() -> DocxExtractor:
    return DocxExtractor()


@pytest.fixture
def validation(service: JobService, input_store: LocalInputStore) -> ValidationService:
    return ValidationService(service, input_store, {DocumentFormat.DOCX: DocxExtractor()})


def test_extracts_supported_layouts_deterministically(extractor: DocxExtractor) -> None:
    data = supported_layouts_docx()
    first = extractor.extract(data)
    second = extractor.extract(data)
    assert first.document is not None
    assert second.document is not None
    combined = _combined(first)
    assert HEADER in combined
    assert SKILL in combined
    assert CELL in combined
    assert EMAIL in combined
    assert "Nguyen" in combined
    assert "Mau" in combined
    assert "choice box" in combined
    assert "fallback box" in combined
    assert "profile link" in combined
    assert FOOTNOTE in combined
    assert CONTROLLED in combined
    assert "hidden@example.test" not in combined
    assert "mailto" not in combined
    assert CORE_CREATOR not in combined
    names = {part.part_name for part in first.document.parts}
    assert "word/document.xml" in names
    assert "word/header1.xml" in names
    assert "word/footnotes.xml" in names
    assert all(part.spans for part in first.document.parts if part.text)
    assert [part.text for part in first.document.parts] == [
        part.text for part in second.document.parts
    ]


@pytest.mark.parametrize(
    ("builder", "failure", "review"),
    [
        (encrypted_docx, None, ReviewReason.DOCX_ENCRYPTED),
        (empty_docx, None, ReviewReason.DOCX_NO_TEXT),
        (oversized_docx, None, ReviewReason.DOCX_TOO_LARGE_TEXT),
        (traversal_docx, ErrorCode.DOCX_UNSAFE_ARCHIVE, None),
        (zip_bomb_docx, ErrorCode.DOCX_RESOURCE_LIMIT, None),
        (dtd_docx, ErrorCode.DOCX_MALFORMED, None),
        (lambda: SYNTHETIC_PDF, ErrorCode.DOCX_MALFORMED, None),
        (lambda: synthetic_docx(macro=True), ErrorCode.DOCX_MACRO_OR_TEMPLATE, None),
    ],
    ids=(
        "encrypted",
        "empty",
        "oversized",
        "traversal",
        "zip_bomb",
        "dtd",
        "not_zip",
        "macro",
    ),
)
def test_classifies_unsupported_docx(
    extractor: DocxExtractor,
    builder: Callable[[], bytes],
    failure: ErrorCode | None,
    review: ReviewReason | None,
) -> None:
    result = extractor.extract(builder())
    assert result.document is None
    assert result.failure is failure
    assert result.review == (frozenset({review}) if review is not None else frozenset())


def test_hidden_content_holds_without_leaking_text(
    service: JobService, input_store: LocalInputStore, validation: ValidationService
) -> None:
    batch = service.create_batch()
    job = uploaded_document(
        service,
        input_store,
        batch.batch_id,
        DocumentFormat.DOCX,
        hidden_comments_docx(),
    )
    outcome = validation.validate(job.document_id)
    assert outcome.job.state is DocumentState.REVIEW_REQUIRED
    assert outcome.job.review_reasons == frozenset({ReviewReason.DOCX_HIDDEN_CONTENT})
    kinds = {alert.category for alert in outcome.alerts}
    assert HiddenContentCategory.COMMENTS in kinds
    dumped = repr(outcome.alerts)
    for fragment in ("Nguyen", "secret comment", "comments.xml"):
        assert fragment not in dumped


@pytest.mark.parametrize(
    ("builder", "category"),
    [
        (hidden_tracked_docx, HiddenContentCategory.TRACKED_CHANGES),
        (hidden_vanish_docx, HiddenContentCategory.HIDDEN_TEXT),
    ],
    ids=("tracked", "vanish"),
)
def test_hidden_categories_are_detected(
    extractor: DocxExtractor,
    builder: Callable[[], bytes],
    category: HiddenContentCategory,
) -> None:
    result = extractor.extract(builder())
    assert result.review == frozenset({ReviewReason.DOCX_HIDDEN_CONTENT})
    assert category in {alert.category for alert in result.alerts}
    dumped = repr(result.alerts)
    assert "inserted name" not in dumped
    assert "secret vanish" not in dumped


def test_validate_queues_without_logging_text(
    service: JobService,
    input_store: LocalInputStore,
    validation: ValidationService,
    caplog: pytest.LogCaptureFixture,
) -> None:
    batch = service.create_batch()
    job = uploaded_document(
        service,
        input_store,
        batch.batch_id,
        DocumentFormat.DOCX,
        supported_layouts_docx(),
    )
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        outcome = validation.validate(job.document_id)
    assert outcome.job.state is DocumentState.QUEUED
    assert outcome.extracted is not None
    logged = " ".join(record.getMessage() for record in caplog.records)
    for fragment in ("Nguyen", EMAIL, "Mau", CORE_CREATOR):
        assert fragment not in logged
