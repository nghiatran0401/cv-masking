"""Stage 9 end to end: synthetic PDF bytes → PyMuPDF extraction → detection → regions.

Assertions compare booleans and counts so failure output never prints fixture text.
"""

import logging

import pytest
from mapping_debug import debug_rows, render, words_under
from synthetic_mapping import COMPANY, EMAIL, NAME, PHONE, REF_EMAIL, REFEREE, layout_pdf

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.adapters.pdf.extractor import PyMuPDFExtractor
from cv_masking.application import DetectionOutcome, DetectionService
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.ports.extraction import ExtractedDocument


@pytest.fixture(scope="module")
def mapped() -> tuple[ExtractedDocument, DetectionOutcome]:
    result = PyMuPDFExtractor().extract(layout_pdf())
    assert result.document is not None
    document = result.document
    outcome = DetectionService(PresidioDetector()).detect(document, MaskingPolicy())
    return document, outcome


def _region_words(
    document: ExtractedDocument, outcome: DetectionOutcome, entity: EntityType
) -> list[list[str]]:
    return [
        [word for box in region.boxes for word in words_under(document, region.page_number, box)]
        for region in outcome.regions
        if region.entity_type is entity
    ]


def test_layout_maps_every_entity_to_exactly_its_words(
    mapped: tuple[ExtractedDocument, DetectionOutcome],
) -> None:
    document, outcome = mapped
    assert outcome.failure is None
    expected = {
        EntityType.CANDIDATE_NAME: [NAME.split()],
        EntityType.EMAIL: [[f"Email:{EMAIL}"], [REF_EMAIL], [EMAIL]],
        EntityType.PHONE: [[PHONE]],
        EntityType.REFERENCE_NAME: [REFEREE.split()],
    }
    for entity, words in expected.items():
        same = _region_words(document, outcome, entity) == words
        assert same, f"{entity.value} regions cover different words"
    assert {r.entity_type for r in outcome.regions} == set(expected)


def test_nfd_title_is_found_by_font_size(
    mapped: tuple[ExtractedDocument, DetectionOutcome],
) -> None:
    _, outcome = mapped
    names = [m for m in outcome.matches if m.entity_type is EntityType.CANDIDATE_NAME]
    assert len(names) == 1
    assert "largest_font" in names[0].signals
    assert not outcome.findings[0].requires_review


def test_unrelated_words_are_never_covered(
    mapped: tuple[ExtractedDocument, DetectionOutcome],
) -> None:
    document, outcome = mapped
    covered = {
        word
        for region in outcome.regions
        for box in region.boxes
        for word in words_under(document, region.page_number, box)
    }
    for index, word in enumerate(
        (*COMPANY.split(), "Director", "Email:", "Kinh", "Contact:", "today", "|")
    ):
        assert word not in covered, f"unrelated word {index} covered"


def test_regions_are_on_the_page_of_their_finding(
    mapped: tuple[ExtractedDocument, DetectionOutcome],
) -> None:
    _, outcome = mapped
    pages = {f.finding_id: f.location.page_number for f in outcome.findings}  # type: ignore[union-attr]
    for region in outcome.regions:
        assert all(pages[item] == region.page_number for item in region.finding_ids)
    assert sorted({r.page_number for r in outcome.regions}) == [1, 2]


def test_debug_view_has_synthetic_words_and_coordinates(
    mapped: tuple[ExtractedDocument, DetectionOutcome],
) -> None:
    document, outcome = mapped
    rows = debug_rows(document, outcome.regions)
    assert len(rows) == sum(len(region.boxes) for region in outcome.regions)
    rendered = render(rows)
    assert rendered.count("\n") == len(rows) - 1
    for row in rows:
        assert row.words
        x0, y0, x1, y1 = row.box
        assert x0 < x1
        assert y0 < y1


def test_mapping_logs_counts_only(caplog: pytest.LogCaptureFixture) -> None:
    result = PyMuPDFExtractor().extract(layout_pdf())
    assert result.document is not None
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        outcome = DetectionService(PresidioDetector()).detect(result.document, MaskingPolicy())
    logged = " ".join(record.getMessage() for record in caplog.records)
    dumped = repr(outcome.findings) + repr(outcome.regions)
    for index, fragment in enumerate((*NAME.split(), EMAIL, PHONE, *REFEREE.split(), "Nguyen")):
        assert fragment not in logged, f"fragment {index} logged"
        assert fragment not in dumped, f"fragment {index} in findings or regions"
