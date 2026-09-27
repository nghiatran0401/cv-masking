# mypy: disable-error-code="no-untyped-call,attr-defined"
"""Stage 10: synthetic PDF → extraction → detection → permanent redaction → re-open.

Every check is computed into a boolean or count first, so a failure prints no
fixture text. Messages carry case indexes and entity types only.
"""

import io
import logging
from collections.abc import Iterator
from uuid import uuid4

import pymupdf
import pytest
from synthetic_redaction import (
    ABOVE,
    AFTER_TARGET,
    BELOW,
    BODY,
    COMPANY,
    EMAIL,
    NAME,
    PHONE,
    SALARY,
    TARGET,
    all_text,
    cv_pdf,
    image_digests,
    visible_words,
)

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor
from cv_masking.adapters.pdf.redactor import MIN_LABEL_PT
from cv_masking.application import DetectionOutcome, DetectionService
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import BoundingBox, RedactionRegion
from cv_masking.domain.ids import FindingId
from cv_masking.domain.policy import REPLACEMENT_LABELS, EntityType, MaskingPolicy
from cv_masking.ports.extraction import ExtractedDocument
from cv_masking.ports.redaction import RedactionResult

_LABELS = frozenset(REPLACEMENT_LABELS.values())


def _extract(data: bytes) -> ExtractedDocument:
    result = PyMuPDFExtractor().extract(data)
    assert result.document is not None
    return result.document


def _detect(data: bytes, policy: MaskingPolicy | None = None) -> DetectionOutcome:
    outcome = DetectionService(PresidioDetector()).detect(_extract(data), policy or MaskingPolicy())
    assert outcome.failure is None
    return outcome


def _redact(data: bytes, regions: tuple[RedactionRegion, ...]) -> bytes:
    result = PyMuPDFRedactor().redact(data, regions, remove_hidden=False)
    assert result.failure is None
    assert result.output is not None
    return result.output


def _word_box(data: bytes, word: str) -> BoundingBox:
    document = _extract(data)
    part = document.parts[0]
    for span in part.spans:
        if part.text[span.start : span.end] == word:
            return span.boxes[0]
    raise AssertionError("fixture word not found")


def _region(*boxes: BoundingBox, entity: EntityType = EntityType.CANDIDATE_NAME) -> RedactionRegion:
    return RedactionRegion(1, boxes, entity, (FindingId(uuid4()),))


def _label_spans(data: bytes) -> Iterator[tuple[str, float]]:
    document = pymupdf.open(stream=data, filetype="pdf")
    try:
        for page in document:
            for block in page.get_text("dict")["blocks"]:
                for line in block.get("lines", []):
                    for span in line["spans"]:
                        if span["text"].strip() in _LABELS:
                            yield span["text"].strip(), float(span["size"])
    finally:
        document.close()


def test_detected_values_cannot_be_extracted_after_redaction() -> None:
    data = cv_pdf()
    output = _redact(data, _detect(data).regions)
    text = all_text(output)
    for index, value in enumerate((NAME, EMAIL, PHONE, SALARY, *NAME.split())):
        leaked = value in text
        assert not leaked, f"value {index} still extractable"


def test_unredacted_text_and_page_survive() -> None:
    data = cv_pdf()
    output = _redact(data, _detect(data).regions)
    words = visible_words(output)
    for index, word in enumerate((*COMPANY.split(), *ABOVE.split(), *BELOW.split(), "Python")):
        kept = word in words
        assert kept, f"kept word {index} missing"
    reopened = pymupdf.open(stream=output, filetype="pdf")
    assert reopened.page_count == 1
    assert reopened[0].get_pixmap(matrix=pymupdf.Matrix(0.5, 0.5)).width > 0


def test_every_region_gets_one_label_at_minimum_size_or_solid_fill() -> None:
    data = cv_pdf()
    regions = _detect(data).regions
    result = PyMuPDFRedactor().redact(data, regions, remove_hidden=False)
    assert result.output is not None
    labels = list(_label_spans(result.output))
    assert result.labelled_regions + result.solid_regions == len(regions)
    assert len(labels) == result.labelled_regions
    assert all(size >= MIN_LABEL_PT for _, size in labels)


def test_a_region_spanning_two_lines_gets_one_label() -> None:
    data = cv_pdf()
    region = _region(_word_box(data, "Alpha"), _word_box(data, "Golf"))
    output = _redact(data, (region,))
    labels = [label for label, _ in _label_spans(output)]
    assert labels == ["[NAME]"]
    words = visible_words(output)
    assert "Alpha" not in words
    assert "Golf" not in words


def test_a_label_that_does_not_fit_leaves_a_solid_box() -> None:
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 100), "Ab and more words here", fontsize=7)
    buffer = io.BytesIO()
    document.save(buffer)
    data = buffer.getvalue()
    region = _region(_word_box(data, "Ab"), entity=EntityType.EMAIL)
    result = PyMuPDFRedactor().redact(data, (region,), remove_hidden=False)
    assert result.output is not None
    assert (result.labelled_regions, result.solid_regions) == (0, 1)
    assert list(_label_spans(result.output)) == []
    words = visible_words(result.output)
    assert "Ab" not in words
    assert "more" in words


@pytest.mark.parametrize("line_height", [0.8, 1.0, 1.2], ids=["tight", "single", "normal"])
def test_neighbouring_lines_survive_and_the_word_is_removed(line_height: float) -> None:
    data = cv_pdf(line_height)
    output = _redact(data, (_region(_word_box(data, TARGET)),))
    words = visible_words(output)
    assert TARGET not in words
    kept = [word in words for word in (*ABOVE.split(), *AFTER_TARGET.split(), *BELOW.split())]
    assert all(kept), f"neighbour words lost: {kept.count(False)}"


def test_untrimmed_rectangles_would_damage_the_neighbouring_lines() -> None:
    """Why the redactor trims: PyMuPDF removes every glyph the rectangle touches."""
    data = cv_pdf(1.0)
    target = _word_box(data, TARGET)
    document = pymupdf.open(stream=data, filetype="pdf")
    page = document[0]
    page.add_redact_annot(pymupdf.Rect(target.x0, target.y0, target.x1, target.y1))
    page.apply_redactions(images=0, graphics=0, text=0)
    words = [item[4] for item in page.get_text("words")]
    neighbours = (*ABOVE.split(), *BELOW.split())
    assert sum(word in words for word in neighbours) < len(neighbours)


def test_embedded_image_outside_the_boxes_is_unchanged() -> None:
    data = cv_pdf()
    output = _redact(data, _detect(data).regions)
    same = image_digests(output) == image_digests(data)
    assert same, "image changed"


def test_salary_is_redacted_only_when_the_toggle_is_on() -> None:
    data = cv_pdf()
    masked = all_text(_redact(data, _detect(data, MaskingPolicy(mask_salary=True)).regions))
    unmasked = all_text(_redact(data, _detect(data, MaskingPolicy(mask_salary=False)).regions))
    in_masked = SALARY in masked
    in_unmasked = SALARY in unmasked
    assert not in_masked
    assert in_unmasked
    email_kept = EMAIL in unmasked
    assert not email_kept


def test_salary_findings_are_reported_but_not_regioned_when_the_toggle_is_off() -> None:
    outcome = _detect(cv_pdf(), MaskingPolicy(mask_salary=False))
    found = sum(finding.entity_type is EntityType.SALARY for finding in outcome.findings)
    regioned = sum(region.entity_type is EntityType.SALARY for region in outcome.regions)
    assert found >= 1
    assert regioned == 0


def test_rotated_pages_are_redacted_in_place() -> None:
    document = pymupdf.open(stream=cv_pdf(), filetype="pdf")
    document[0].set_rotation(90)
    buffer = io.BytesIO()
    document.save(buffer)
    data = buffer.getvalue()
    output = _redact(data, _detect(data).regions)
    text = all_text(output)
    leaked = [value in text for value in (NAME, EMAIL, PHONE)]
    assert not any(leaked), f"values leaked: {leaked.count(True)}"
    body = BODY.split()[-1] in visible_words(output)
    assert body


def test_redaction_without_regions_still_rewrites_the_file() -> None:
    data = cv_pdf()
    output = _redact(data, ())
    assert output != data
    same_words = visible_words(output) == visible_words(data)
    assert same_words


def test_input_bytes_are_never_modified() -> None:
    data = cv_pdf()
    copy = bytes(data)
    _redact(data, _detect(data).regions)
    assert data == copy


@pytest.mark.parametrize(
    "data",
    [b"", b"not a pdf at all", b"%PDF-1.7\n%%EOF\n"],
    ids=["empty", "garbage", "truncated"],
)
def test_unreadable_input_fails_closed(data: bytes) -> None:
    result = PyMuPDFRedactor().redact(data, (), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_FAILED
    assert result.output is None


def test_a_region_on_a_missing_page_fails() -> None:
    data = cv_pdf()
    box = _word_box(data, TARGET)
    region = RedactionRegion(2, (box,), EntityType.EMAIL, (FindingId(uuid4()),))
    result = PyMuPDFRedactor().redact(data, (region,), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_FAILED


def test_encrypted_input_fails() -> None:
    document = pymupdf.open(stream=cv_pdf(), filetype="pdf")
    buffer = io.BytesIO()
    document.save(buffer, encryption=pymupdf.PDF_ENCRYPT_AES_256, user_pw="synthetic")
    result = PyMuPDFRedactor().redact(buffer.getvalue(), (), remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_FAILED


def test_text_left_under_a_region_fails_the_output_check(monkeypatch: pytest.MonkeyPatch) -> None:
    """If apply_redactions ever stopped removing text, the output check refuses it."""
    data = cv_pdf()
    monkeypatch.setattr(pymupdf.Page, "apply_redactions", lambda *args, **kwargs: True)
    result = PyMuPDFRedactor().redact(data, _detect(data).regions, remove_hidden=False)
    assert result.failure is ErrorCode.REDACT_FAILED
    assert result.output is None


def test_result_requires_exactly_one_outcome() -> None:
    with pytest.raises(InvariantError, match="exactly one"):
        RedactionResult()
    with pytest.raises(InvariantError, match="redaction error code"):
        RedactionResult(failure=ErrorCode.MAP_FAILED)
    with pytest.raises(InvariantError, match="no region counts"):
        RedactionResult(failure=ErrorCode.REDACT_FAILED, solid_regions=1)


def test_redaction_logs_nothing_from_the_document(caplog: pytest.LogCaptureFixture) -> None:
    data = cv_pdf()
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        _redact(data, _detect(data).regions)
    logged = " ".join(record.getMessage() for record in caplog.records)
    for index, value in enumerate((*NAME.split(), EMAIL, PHONE, SALARY)):
        found = value in logged
        assert not found, f"value {index} logged"
