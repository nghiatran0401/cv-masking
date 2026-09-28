import logging
from collections.abc import Callable

import pytest
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

from cv_masking.adapters.local_storage import LocalInputStore, StorageRoot
from cv_masking.adapters.pdf import PyMuPDFExtractor
from cv_masking.api.runtime import build_pipeline
from cv_masking.application import DocumentPipeline
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.ports.extraction import ExtractionResult
from cv_masking.ports.storage import StoredObject


@pytest.fixture
def extractor() -> PyMuPDFExtractor:
    return PyMuPDFExtractor()


@pytest.fixture
def pipeline(root: StorageRoot) -> DocumentPipeline:
    return build_pipeline(root.path)


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


def _source(input_store: LocalInputStore, data: bytes, fmt: DocumentFormat) -> StoredObject:
    return input_store.save_stream(fmt, [data], max_bytes=HARD_MAX_FILE_BYTES)


def test_hidden_content_is_reported_by_kind_and_count_only(
    input_store: LocalInputStore, pipeline: DocumentPipeline
) -> None:
    report = pipeline.validate(_source(input_store, hidden_content_pdf(), DocumentFormat.PDF))
    assert report.passed
    kinds = report.hidden_removed.as_dict()
    assert kinds[HiddenContentCategory.ANNOTATIONS] >= 1
    assert kinds[HiddenContentCategory.EMBEDDED_FILES] >= 1
    dumped = repr(report)
    for fragment in ("Nguyen", "secret", "never leak", "app.alert"):
        assert fragment not in dumped


def test_validate_passes_a_supported_pdf_without_logging_text(
    input_store: LocalInputStore,
    pipeline: DocumentPipeline,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = _source(input_store, supported_layouts_pdf(), DocumentFormat.PDF)
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        report = pipeline.validate(source)
    assert report.passed
    assert report.hidden_removed.items == ()
    combined = " ".join(record.getMessage() for record in caplog.records)
    for fragment in ("Nguyen", EMAIL, "Mau"):
        assert fragment not in combined


def test_validate_fails_a_malformed_pdf(
    input_store: LocalInputStore, pipeline: DocumentPipeline
) -> None:
    report = pipeline.validate(_source(input_store, SYNTHETIC_PDF, DocumentFormat.PDF))
    assert report.failure is ErrorCode.PDF_MALFORMED


def test_validate_passes_a_simple_docx(
    input_store: LocalInputStore, pipeline: DocumentPipeline
) -> None:
    report = pipeline.validate(_source(input_store, synthetic_docx(), DocumentFormat.DOCX))
    assert report.passed


def test_validate_reports_a_tampered_input(
    input_store: LocalInputStore, pipeline: DocumentPipeline, root: StorageRoot
) -> None:
    source = _source(input_store, supported_layouts_pdf(), DocumentFormat.PDF)
    path = root.path / "inputs" / f"{source.ref.value}.pdf"
    path.chmod(0o600)
    path.write_bytes(SYNTHETIC_PDF)
    assert pipeline.validate(source).failure is ErrorCode.STORAGE_INTEGRITY_FAILED
