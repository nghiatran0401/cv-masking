# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Stage 10: approved hidden content and always-stripped components are removed.

masking-policy.md §6 and D-29. Every hidden-content category is removed and
checked on its own and all together. Checks are booleans or counts; messages
carry category names and case indexes only.
"""

import io
from pathlib import Path

import pymupdf
import pytest
from synthetic_redaction import (
    AUTHOR,
    EMAIL,
    HIDDEN,
    HIDDEN_BUILDERS,
    all_text,
    cv_pdf,
    image_digests,
    visible_words,
    with_always_stripped,
    with_hidden,
)

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor
from cv_masking.adapters.pdf.hidden import scan_hidden
from cv_masking.application import DetectionService
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.findings import RedactionRegion
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.domain.policy import MaskingPolicy

_CATEGORIES = tuple(HIDDEN_BUILDERS)


def _regions(data: bytes) -> tuple[RedactionRegion, ...]:
    document = PyMuPDFExtractor().extract(data).document
    assert document is not None
    outcome = DetectionService(PresidioDetector()).detect(document, MaskingPolicy())
    assert outcome.failure is None
    return outcome.regions


def _every_decoded_object(data: bytes) -> bytes:
    """Every object dictionary and decoded stream in the file, for raw leak searches."""
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        chunks: list[bytes] = []
        for xref in range(1, document.xref_length()):
            chunks.append(document.xref_object(xref).encode("latin-1", "replace"))
            if document.xref_is_stream(xref):
                chunks.append(document.xref_stream(xref) or b"")
        return b"\n".join(chunks)
    finally:
        document.close()


def _categories(data: bytes) -> set[str]:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        return {alert.category.value for alert in scan_hidden(document)}
    finally:
        document.close()


@pytest.mark.parametrize("category", _CATEGORIES)
def test_each_fixture_is_classified_as_its_category(category: str) -> None:
    assert _categories(with_hidden(cv_pdf(), category)) == {category}


@pytest.mark.parametrize("categories", [*((name,) for name in _CATEGORIES), _CATEGORIES])
def test_approved_hidden_content_is_removed(categories: tuple[str, ...]) -> None:
    base = cv_pdf()
    data = with_hidden(base, *categories)
    result = PyMuPDFRedactor().redact(data, _regions(base), remove_hidden=True)
    assert result.failure is None, "removal failed"
    assert result.output is not None
    assert _categories(result.output) == set()
    in_text = HIDDEN in all_text(result.output)
    in_objects = HIDDEN.encode() in _every_decoded_object(result.output)
    assert not in_text, "hidden text still extractable"
    assert not in_objects, "hidden text still in the file"
    same_body = visible_words(result.output) == visible_words(_redacted_base(base))
    assert same_body, "visible text changed"
    same_image = image_digests(result.output) == image_digests(base)
    assert same_image, "visible image changed"


def _redacted_base(base: bytes) -> bytes:
    result = PyMuPDFRedactor().redact(base, _regions(base), remove_hidden=False)
    assert result.output is not None
    return result.output


@pytest.mark.parametrize("category", _CATEGORIES)
def test_hidden_content_without_approval_is_refused(category: str) -> None:
    data = with_hidden(cv_pdf(), category)
    result = PyMuPDFRedactor().redact(data, (), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_SANITIZE_FAILED
    assert result.output is None


def test_hidden_content_is_refused_by_validation_before_redaction() -> None:
    result = PyMuPDFExtractor().extract(with_hidden(cv_pdf(), *_CATEGORIES))
    assert result.review == frozenset({ReviewReason.PDF_HIDDEN_CONTENT})
    found = {alert.category for alert in result.alerts}
    assert found == set(HiddenContentCategory) & {HiddenContentCategory(c) for c in _CATEGORIES}


def test_render_mode_three_text_is_hidden_and_never_extracted() -> None:
    document = pymupdf.open(stream=cv_pdf(), filetype="pdf")
    document[0].insert_text((300, 700), HIDDEN, fontsize=11, render_mode=3)
    buffer = io.BytesIO()
    document.save(buffer)
    result = PyMuPDFExtractor().extract(buffer.getvalue())
    assert result.review == frozenset({ReviewReason.PDF_HIDDEN_CONTENT})
    assert [alert.category for alert in result.alerts] == [HiddenContentCategory.INVISIBLE_TEXT]


def test_fully_transparent_text_is_hidden() -> None:
    document = pymupdf.open(stream=cv_pdf(), filetype="pdf")
    document[0].insert_text((300, 700), HIDDEN, fontsize=11, fill_opacity=0)
    buffer = io.BytesIO()
    document.save(buffer)
    assert _categories(buffer.getvalue()) == {HiddenContentCategory.INVISIBLE_TEXT.value}


def test_layer_visibility_viewers_disagree_on_fails_closed() -> None:
    """MuPDF draws this membership-dictionary content, the PDF rules hide it.

    The redactor removes it, the rendered page then differs, and it refuses the
    output rather than guess which viewer HR will use.
    """
    document = pymupdf.open(stream=cv_pdf(), filetype="pdf")
    ocg = document.add_ocg("Synthetic hidden layer", on=False)
    ocmd = document.set_ocmd(ocgs=[ocg], policy="AllOn")
    document[0].insert_text((300, 520), HIDDEN, fontsize=11, oc=ocmd)
    buffer = io.BytesIO()
    document.save(buffer)
    result = PyMuPDFRedactor().redact(buffer.getvalue(), (), remove_hidden=True)
    assert result.failure is ErrorCode.REDACT_SANITIZE_FAILED
    assert result.output is None


def test_always_stripped_components_are_removed_without_approval() -> None:
    data = with_always_stripped(cv_pdf())
    assert _categories(data) == set()
    result = PyMuPDFRedactor().redact(data, _regions(cv_pdf()), remove_hidden=False)
    assert result.output is not None
    document = pymupdf.open(stream=result.output, filetype="pdf")
    try:
        metadata = {k: v for k, v in (document.metadata or {}).items() if k != "format"}
        assert not any(metadata.values())
        assert document.get_xml_metadata() == ""
        assert document.get_toc() == []
        assert document.get_page_labels() == []
        page = document[0]
        assert page.get_links() == []
        assert document.xref_get_key(page.xref, "Thumb")[0] == "null"
    finally:
        document.close()
    raw = _every_decoded_object(result.output)
    for index, value in enumerate((AUTHOR, f"mailto:{EMAIL}", EMAIL)):
        leaked = value.encode() in raw
        assert not leaked, f"stripped value {index} still in the file"


def test_output_is_a_full_rewrite_without_earlier_revisions(tmp_path: Path) -> None:
    path = tmp_path / "synthetic-revisions.pdf"
    document = pymupdf.open(stream=cv_pdf(), filetype="pdf")
    document.set_metadata({"author": AUTHOR})
    document.save(path)
    document.close()
    document = pymupdf.open(path)
    document.set_metadata({"author": "Revised"})
    document.saveIncr()
    document.close()
    incremental = path.read_bytes()
    assert incremental.count(b"%%EOF") == 2
    result = PyMuPDFRedactor().redact(incremental, (), remove_hidden=False)
    assert result.output is not None
    assert result.output.count(b"%%EOF") == 1
    leaked = AUTHOR.encode() in result.output
    assert not leaked
