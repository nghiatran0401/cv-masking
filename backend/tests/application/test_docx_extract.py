import logging
from collections.abc import Callable

import pytest
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
from cv_masking.adapters.local_storage import LocalInputStore, StorageRoot
from cv_masking.api.runtime import build_pipeline
from cv_masking.application import DocumentPipeline
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.ports.extraction import ExtractionResult
from cv_masking.ports.storage import StoredObject


def _combined(result: ExtractionResult) -> str:
    if result.document is None:
        return ""
    return "\n".join(part.text for part in result.document.parts)


@pytest.fixture
def extractor() -> DocxExtractor:
    return DocxExtractor()


@pytest.fixture
def pipeline(root: StorageRoot) -> DocumentPipeline:
    return build_pipeline(root.path)


def _source(input_store: LocalInputStore, data: bytes) -> StoredObject:
    return input_store.save_stream(DocumentFormat.DOCX, [data], max_bytes=HARD_MAX_FILE_BYTES)


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


def test_hidden_content_is_reported_by_kind_and_count_only(
    input_store: LocalInputStore, pipeline: DocumentPipeline
) -> None:
    report = pipeline.validate(_source(input_store, hidden_comments_docx()))
    assert report.passed
    assert HiddenContentCategory.COMMENTS in report.hidden_removed.as_dict()
    dumped = repr(report)
    for fragment in ("Nguyen", "secret comment", "comments.xml"):
        assert fragment not in dumped


@pytest.mark.parametrize(
    ("builder", "category", "secret"),
    [
        (hidden_tracked_docx, HiddenContentCategory.TRACKED_CHANGES, "inserted name"),
        (hidden_vanish_docx, HiddenContentCategory.HIDDEN_TEXT, "secret vanish"),
    ],
    ids=("tracked", "vanish"),
)
def test_hidden_categories_are_detected(
    extractor: DocxExtractor,
    builder: Callable[[], bytes],
    category: HiddenContentCategory,
    secret: str,
) -> None:
    result = extractor.extract(builder())
    assert result.document is not None
    assert not result.review
    assert category in {alert.category for alert in result.document.hidden}
    dumped = repr(result.document.hidden)
    assert secret not in dumped


def test_hidden_text_never_enters_the_text_model(extractor: DocxExtractor) -> None:
    document = extractor.extract(hidden_vanish_docx()).document
    assert document is not None
    extracted = any("secret vanish" in part.text for part in document.parts)
    assert not extracted


def test_validate_passes_without_logging_text(
    input_store: LocalInputStore,
    pipeline: DocumentPipeline,
    caplog: pytest.LogCaptureFixture,
) -> None:
    source = _source(input_store, supported_layouts_docx())
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        report = pipeline.validate(source)
    assert report.passed
    logged = " ".join(record.getMessage() for record in caplog.records)
    for fragment in ("Nguyen", EMAIL, "Mau", CORE_CREATOR):
        assert fragment not in logged
