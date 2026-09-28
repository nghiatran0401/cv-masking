# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Stage 10: hidden content and always-stripped components are removed.

masking-policy.md §6 and D-32: hidden content is always removed, never approved.
Every category is removed and checked on its own and all together. Checks are
booleans or counts; messages carry category names and case indexes only.
"""

import io
from pathlib import Path

import pymupdf
import pytest
from synthetic_redaction import (
    ALT_TEXT,
    AUTHOR,
    EMAIL,
    HIDDEN,
    HIDDEN_BUILDERS,
    all_text,
    cv_pdf,
    image_digests,
    visible_words,
    with_always_stripped,
    with_cyclic_ocmd,
    with_hidden,
    with_indirect_ocmd_ocgs,
    with_indirect_ocmd_ve,
    with_inline_bdc_oc,
    with_inline_oc_property,
    with_inline_xobject_oc,
    with_nested_ocmd,
    with_ocmd_allon,
    with_ocmd_ve_and,
    with_ocmd_ve_not_visible,
    with_unknown_oc_name,
    with_unsupported_ve,
    with_visible_and_hidden_layers,
)

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor
from cv_masking.adapters.pdf.hidden import scan_hidden
from cv_masking.application import DetectionService
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
def test_hidden_content_is_always_removed(categories: tuple[str, ...]) -> None:
    base = cv_pdf()
    data = with_hidden(base, *categories)
    result = PyMuPDFRedactor().redact(data, _regions(base))
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
    result = PyMuPDFRedactor().redact(base, _regions(base))
    assert result.output is not None
    return result.output


@pytest.mark.parametrize("category", _CATEGORIES)
def test_hidden_content_is_removed_with_nothing_to_redact(category: str) -> None:
    result = PyMuPDFRedactor().redact(with_hidden(cv_pdf(), category), ())
    assert result.output is not None, "removal failed"
    assert _categories(result.output) == set()


def test_extraction_reports_hidden_content_and_still_returns_the_text() -> None:
    result = PyMuPDFExtractor().extract(with_hidden(cv_pdf(), *_CATEGORIES))
    assert result.document is not None
    assert not result.review
    found = {alert.category for alert in result.document.hidden}
    assert found == {HiddenContentCategory(c) for c in _CATEGORIES}


def test_render_mode_three_text_is_hidden_and_never_extracted() -> None:
    document = pymupdf.open(stream=cv_pdf(), filetype="pdf")
    document[0].insert_text((300, 700), HIDDEN, fontsize=11, render_mode=3)
    buffer = io.BytesIO()
    document.save(buffer)
    model = PyMuPDFExtractor().extract(buffer.getvalue()).document
    assert model is not None
    assert [alert.category for alert in model.hidden] == [HiddenContentCategory.INVISIBLE_TEXT]
    extracted = any(HIDDEN in part.text for part in model.parts)
    assert not extracted, "invisible text entered the text model"


def test_fully_transparent_text_is_hidden() -> None:
    document = pymupdf.open(stream=cv_pdf(), filetype="pdf")
    document[0].insert_text((300, 700), HIDDEN, fontsize=11, fill_opacity=0)
    buffer = io.BytesIO()
    document.save(buffer)
    assert _categories(buffer.getvalue()) == {HiddenContentCategory.INVISIBLE_TEXT.value}


def test_ocmd_allon_hidden_layer_is_removed() -> None:
    """MuPDF draws this membership-dictionary content; the PDF rules hide it.

    After removal the bytes are gone, so every viewer agrees. A render change
    confined to that hidden text is accepted.
    """
    data = with_ocmd_allon(cv_pdf())
    result = PyMuPDFRedactor().redact(data, ())
    assert result.failure is None
    assert result.output is not None
    assert HIDDEN not in all_text(result.output)
    assert HIDDEN.encode() not in _every_decoded_object(result.output)
    assert visible_words(result.output) == visible_words(cv_pdf())


def test_inline_oc_property_dictionary_is_removed() -> None:
    result = PyMuPDFRedactor().redact(with_inline_oc_property(cv_pdf()), ())
    assert result.output is not None, "inline Properties OCMD was not removed"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)


def test_inline_bdc_oc_dictionary_is_removed() -> None:
    result = PyMuPDFRedactor().redact(with_inline_bdc_oc(cv_pdf()), ())
    assert result.output is not None, "inline BDC OCMD was not removed"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)


def test_inline_xobject_oc_dictionary_is_removed() -> None:
    result = PyMuPDFRedactor().redact(with_inline_xobject_oc(cv_pdf()), ())
    assert result.output is not None, "inline XObject OCMD was not removed"
    assert _categories(result.output) == set()


def test_nested_ocmd_is_removed() -> None:
    result = PyMuPDFRedactor().redact(with_nested_ocmd(cv_pdf()), ())
    assert result.output is not None, "nested OCMD was not removed"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)


def test_visibility_expression_hiding_an_off_group_is_removed() -> None:
    result = PyMuPDFRedactor().redact(with_ocmd_ve_and(cv_pdf()), ())
    assert result.output is not None, "VE And of an off group was not removed"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)


def test_visibility_expression_showing_an_off_group_is_kept() -> None:
    result = PyMuPDFRedactor().redact(with_ocmd_ve_not_visible(cv_pdf()), ())
    assert result.output is not None
    assert HIDDEN in all_text(result.output)


def test_visible_optional_content_layer_is_kept() -> None:
    result = PyMuPDFRedactor().redact(with_visible_and_hidden_layers(cv_pdf()), ())
    assert result.output is not None
    assert "Keep" in all_text(result.output)
    assert HIDDEN.encode() not in _every_decoded_object(result.output)


def test_unknown_visibility_expression_is_over_stripped() -> None:
    result = PyMuPDFRedactor().redact(with_unsupported_ve(cv_pdf()), ())
    assert result.output is not None, "unparseable VE should be removed, not refuse the file"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)
    assert visible_words(result.output) == visible_words(cv_pdf())


def test_indirect_ocmd_groups_array_is_removed() -> None:
    result = PyMuPDFRedactor().redact(with_indirect_ocmd_ocgs(cv_pdf()), ())
    assert result.output is not None, "indirect OCMD OCGs array was not removed"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)
    assert visible_words(result.output) == visible_words(cv_pdf())


def test_indirect_visibility_expression_is_removed() -> None:
    result = PyMuPDFRedactor().redact(with_indirect_ocmd_ve(cv_pdf()), ())
    assert result.output is not None, "indirect VE array was not removed"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)
    assert visible_words(result.output) == visible_words(cv_pdf())


def test_unknown_optional_content_name_is_over_stripped() -> None:
    result = PyMuPDFRedactor().redact(with_unknown_oc_name(cv_pdf()), ())
    assert result.output is not None, "unknown OC property name was not removed"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)
    assert visible_words(result.output) == visible_words(cv_pdf())


def test_cyclic_membership_is_over_stripped() -> None:
    result = PyMuPDFRedactor().redact(with_cyclic_ocmd(cv_pdf()), ())
    assert result.output is not None, "cyclic OCMD was not removed"
    assert HIDDEN.encode() not in _every_decoded_object(result.output)
    assert visible_words(result.output) == visible_words(cv_pdf())


def test_always_stripped_components_are_removed() -> None:
    data = with_always_stripped(cv_pdf())
    assert _categories(data) == set()
    result = PyMuPDFRedactor().redact(data, _regions(cv_pdf()))
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
        catalog = document.pdf_catalog()
        for key in ("StructTreeRoot", "MarkInfo"):
            assert document.xref_get_key(catalog, key)[0] == "null", key
        for key in ("StructParents", "PieceInfo"):
            assert document.xref_get_key(page.xref, key)[0] == "null", key
    finally:
        document.close()
    raw = _every_decoded_object(result.output)
    for index, value in enumerate((AUTHOR, ALT_TEXT, f"mailto:{EMAIL}", EMAIL)):
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
    result = PyMuPDFRedactor().redact(incremental, ())
    assert result.output is not None
    assert result.output.count(b"%%EOF") == 1
    leaked = AUTHOR.encode() in result.output
    assert not leaked
