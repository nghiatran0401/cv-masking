"""Stage 9: span-to-box mapping and redaction regions on hand-built PDF pages.

Assertions compare coordinates and word counts; failure messages name types only.
"""

from uuid import uuid4

import pytest
from mapping_debug import words_under
from synthetic_mapping import EMAIL, NAME, PHONE, glued, page

from cv_masking.application import DetectionOutcome, DetectionService
from cv_masking.application.mapping import build_regions, map_span
from cv_masking.domain.codes import ErrorCode, ReviewReason, is_retryable
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import (
    MAX_BOXES_PER_FINDING,
    BoundingBox,
    DocxLocation,
    EntityFinding,
    PdfLocation,
    RedactionRegion,
)
from cv_masking.domain.ids import FindingId
from cv_masking.domain.policy import (
    REPLACEMENT_LABELS,
    EntityType,
    MaskingPolicy,
    label_winner,
)
from cv_masking.ports.detection import DetectionResult, TextMatch
from cv_masking.ports.extraction import ExtractedDocument, TextPart, TextSpan

_H = 10.0
_FIRST, _MIDDLE, _LAST = NAME.split()


def _row(
    y: float, *words: tuple[str, float, float]
) -> tuple[tuple[str, float, float, float, float], ...]:
    return tuple((word, x0, y, x1, y + _H) for word, x0, x1 in words)


def _range(document: ExtractedDocument, value: str, occurrence: int = 0) -> tuple[int, int]:
    text = document.parts[0].text
    start = -1
    for _ in range(occurrence + 1):
        start = text.index(value, start + 1)
    return start, start + len(value)


def _covered(document: ExtractedDocument, boxes: tuple[BoundingBox, ...]) -> list[str]:
    return [word for box in boxes for word in words_under(document, 1, box)]


class _Fixed:
    """A detector returning preset matches, to test placement independently of detection."""

    def __init__(self, *matches: TextMatch) -> None:
        self._matches = matches

    def detect(self, document: ExtractedDocument) -> DetectionResult:
        del document
        return DetectionResult(self._matches)


_SIGNALS = {
    EntityType.CANDIDATE_NAME: ("label",),
    EntityType.FAMILY_DETAILS: ("section_heading",),
}


def _match(entity: EntityType, span: tuple[int, int], page_number: int = 1) -> TextMatch:
    signals = _SIGNALS.get(entity, ())
    return TextMatch(
        entity,
        span[0],
        span[1],
        0.95,
        "test.fixed",
        "1.0.0",
        page_number=page_number,
        signals=signals,
    )


def _outcome(document: ExtractedDocument, *matches: TextMatch) -> DetectionOutcome:
    return DetectionService(_Fixed(*matches)).detect(document, MaskingPolicy())


def test_single_word_maps_to_its_own_box() -> None:
    document = page(_row(0, ("Email:", 0, 30), (EMAIL, 35, 140), ("today", 145, 170)))
    mapped = map_span(document.parts[0], *_range(document, EMAIL))
    assert mapped is not None
    assert mapped.boxes == (BoundingBox(35, 0, 140, _H),)
    assert mapped.partial_words == 0
    assert not mapped.ambiguous


def test_words_on_one_line_merge_without_neighbours() -> None:
    document = page(
        _row(
            0,
            ("Tên:", 0, 20),
            (_FIRST, 25, 60),
            (_MIDDLE, 64, 84),
            (_LAST, 88, 110),
            ("Nam", 115, 135),
        )
    )
    mapped = map_span(document.parts[0], *_range(document, NAME))
    assert mapped is not None
    assert mapped.boxes == (BoundingBox(25, 0, 110, _H),)
    same = _covered(document, mapped.boxes) == NAME.split()
    assert same, "merged line box covers exactly the name words"


def test_line_break_gives_one_box_per_line() -> None:
    document = page(
        _row(0, ("Ref", 0, 20), (_FIRST, 25, 60), (_MIDDLE, 64, 84)),
        _row(8, (_LAST, 0, 22), ("Director", 26, 70)),
    )
    part = document.parts[0]
    start = part.text.index(_FIRST)
    end = part.text.index(_LAST) + len(_LAST)
    mapped = map_span(part, start, end)
    assert mapped is not None
    assert mapped.boxes == (BoundingBox(25, 0, 84, _H), BoundingBox(0, 8, 22, 8 + _H))
    same = _covered(document, mapped.boxes) == NAME.split()
    assert same, "wrapped name covers its words on both lines only"


@pytest.mark.parametrize("index", range(2), ids=("trailing_comma", "glued_label"))
def test_partial_word_is_redacted_whole(index: int) -> None:
    word, value = ((f"{PHONE},", PHONE), (f"Email:{EMAIL}", EMAIL))[index]
    document = page(_row(0, ("Contact", 0, 40), (word, 45, 160), ("next", 165, 185)))
    mapped = map_span(document.parts[0], *_range(document, value))
    assert mapped is not None
    assert mapped.boxes == (BoundingBox(45, 0, 160, _H),)
    assert mapped.partial_words == 1


def test_split_token_fragments_merge_into_one_box() -> None:
    document = glued((PHONE[:4], 0, 0, 20, _H), (PHONE[4:], 20, 0, 50, _H))
    mapped = map_span(document.parts[0], 0, len(PHONE))
    assert mapped is not None
    assert mapped.boxes == (BoundingBox(0, 0, 50, _H),)


def test_table_cells_are_not_bridged() -> None:
    document = page(
        _row(
            0,
            ("Tên", 0, 20),
            ("Jane", 150, 175),
            ("Example", 178, 215),
            ("Example", 300, 340),
            ("Bank", 343, 365),
        )
    )
    part = document.parts[0]
    start = part.text.index("Jane")
    mapped = map_span(part, start, start + len("Jane Example"))
    assert mapped is not None
    assert mapped.boxes == (BoundingBox(150, 0, 215, _H),)


def test_column_gap_splits_boxes() -> None:
    document = page(_row(0, ("Jane", 0, 25), ("Example", 200, 240)))
    mapped = map_span(document.parts[0], 0, len("Jane Example"))
    assert mapped is not None
    assert len(mapped.boxes) == 2


def test_merge_refused_when_an_unrelated_word_sits_between() -> None:
    rows = (
        _row(0, ("Jane", 0, 20), ("Example", 42, 62)),
        _row(20, ("Other", 22, 40)),
    )
    document = page(*rows)
    part = document.parts[0]
    other = part.spans[2]
    moved = TextSpan(other.start, other.end, (BoundingBox(22, 0, 40, _H),))
    document = ExtractedDocument(
        document.document_format,
        (TextPart(part.text, (*part.spans[:2], moved), page_number=1),),
    )
    mapped = map_span(document.parts[0], 0, len("Jane Example"))
    assert mapped is not None
    assert mapped.boxes == (BoundingBox(0, 0, 20, _H), BoundingBox(42, 0, 62, _H))
    assert "Other" not in _covered(document, mapped.boxes)


def test_neighbouring_line_overlap_is_not_ambiguous() -> None:
    document = page(
        _row(0, (_FIRST, 0, 40), (_MIDDLE, 44, 64)),
        _row(7, ("Email:", 0, 30), (EMAIL, 34, 140)),
    )
    mapped = map_span(document.parts[0], *_range(document, f"{_FIRST} {_MIDDLE}"))
    assert mapped is not None
    assert not mapped.ambiguous
    assert mapped.boxes == (BoundingBox(0, 0, 64, _H),)


def test_overprinted_word_is_ambiguous_and_both_boxes_redacted() -> None:
    document = page(((_LAST, 0, 0, 30, _H), (_LAST, 0.5, 0.2, 30.5, _H)))
    mapped = map_span(document.parts[0], 0, len(_LAST))
    assert mapped is not None
    assert mapped.ambiguous
    assert set(mapped.boxes) == {BoundingBox(0, 0, 30, _H), BoundingBox(0.5, 0.2, 30.5, _H)}
    outcome = _outcome(document, _match(EntityType.CANDIDATE_NAME, (0, len(_LAST))))
    assert ReviewReason.MAP_AMBIGUOUS in outcome.review
    assert outcome.failure is None


def test_overprinted_salary_is_not_ambiguous_when_salary_is_not_redacted() -> None:
    document = page((("20tr", 0, 0, 30, _H), ("20tr", 0.5, 0.2, 30.5, _H)))
    salary = _match(EntityType.SALARY, (0, 4))
    unmasked = DetectionService(_Fixed(salary)).detect(document, MaskingPolicy(mask_salary=False))
    masked = DetectionService(_Fixed(salary)).detect(document, MaskingPolicy(mask_salary=True))
    assert ReviewReason.MAP_AMBIGUOUS not in unmasked.review
    assert ReviewReason.MAP_AMBIGUOUS in masked.review


def test_duplicate_occurrences_map_to_their_own_boxes() -> None:
    document = page(
        _row(0, ("Email:", 0, 30), (EMAIL, 35, 140)),
        _row(40, ("Again", 0, 30), (EMAIL, 35, 140)),
    )
    first = _match(EntityType.EMAIL, _range(document, EMAIL, 0))
    second = _match(EntityType.EMAIL, _range(document, EMAIL, 1))
    outcome = _outcome(document, first, second)
    boxes = [f.location.boxes for f in outcome.findings if isinstance(f.location, PdfLocation)]
    assert boxes == [(BoundingBox(35, 0, 140, _H),), (BoundingBox(35, 40, 140, 40 + _H),)]
    assert len(outcome.regions) == 2


def test_uncovered_visible_character_fails_mapping() -> None:
    text = f"Email: {EMAIL}"
    part = TextPart(text, (TextSpan(0, 6, (BoundingBox(0, 0, 30, _H),)),), page_number=1)
    assert map_span(part, 7, len(text)) is None
    document = ExtractedDocument(page(_row(0, ("x", 0, 5))).document_format, (part,))
    outcome = _outcome(document, _match(EntityType.EMAIL, (7, len(text))))
    assert outcome.failure is ErrorCode.MAP_FAILED
    assert not is_retryable(ErrorCode.MAP_FAILED)
    assert outcome.findings == ()
    assert outcome.regions == ()
    assert outcome.counts.total == 0


def test_whitespace_between_words_needs_no_box() -> None:
    document = page(_row(0, ("Jane", 0, 20), ("Example", 24, 60)))
    assert map_span(document.parts[0], 0, len("Jane Example")) is not None


@pytest.mark.parametrize(
    "bounds", [(-1, 3), (3, 3), (0, 10_000)], ids=("negative", "empty", "past_end")
)
def test_out_of_range_spans_fail(bounds: tuple[int, int]) -> None:
    document = page(_row(0, ("Jane", 0, 20)))
    assert map_span(document.parts[0], *bounds) is None


def test_long_findings_are_chunked() -> None:
    rows = [
        _row(index * 12.0, (f"w{index:03d}", 0, 20)) for index in range(MAX_BOXES_PER_FINDING + 6)
    ]
    document = page(*rows)
    end = len(document.parts[0].text)
    outcome = _outcome(document, _match(EntityType.FAMILY_DETAILS, (0, end)))
    sizes = [len(f.location.boxes) for f in outcome.findings if isinstance(f.location, PdfLocation)]
    assert sizes == [MAX_BOXES_PER_FINDING, 6]
    assert outcome.counts.as_dict() == {EntityType.FAMILY_DETAILS: 1}


def test_same_word_findings_form_one_region_with_winning_label() -> None:
    document = page(_row(0, ("ID", 0, 12), (PHONE, 16, 80)))
    span = _range(document, PHONE)
    outcome = _outcome(
        document, _match(EntityType.PHONE, span), _match(EntityType.NATIONAL_ID, span)
    )
    assert len(outcome.regions) == 1
    region = outcome.regions[0]
    assert region.entity_type is EntityType.NATIONAL_ID
    assert region.replacement_label == REPLACEMENT_LABELS[EntityType.NATIONAL_ID]
    assert region.boxes == (BoundingBox(16, 0, 80, _H),)
    assert set(region.finding_ids) == {f.finding_id for f in outcome.findings}


def test_partial_overlap_merges_into_one_box() -> None:
    document = page(_row(0, ("a", 0, 10), ("b", 14, 24), ("c", 28, 38), ("d", 42, 52)))
    outcome = _outcome(
        document,
        _match(EntityType.EMAIL, (0, 3)),
        _match(EntityType.PERSONAL_URL, (2, 5)),
    )
    assert len(outcome.regions) == 1
    region = outcome.regions[0]
    assert region.entity_type is EntityType.EMAIL
    assert region.boxes == (BoundingBox(0, 0, 38, _H),)
    same = _covered(document, region.boxes) == ["a", "b", "c"]
    assert same, "region covers the union of both findings and nothing else"


def test_findings_on_neighbouring_lines_stay_separate() -> None:
    document = page(
        _row(0, (_FIRST, 0, 40), (_MIDDLE, 44, 64)),
        _row(7, (EMAIL, 0, 110)),
    )
    outcome = _outcome(
        document,
        _match(EntityType.CANDIDATE_NAME, _range(document, f"{_FIRST} {_MIDDLE}")),
        _match(EntityType.EMAIL, _range(document, EMAIL)),
    )
    assert sorted(r.entity_type.value for r in outcome.regions) == ["candidate_name", "email"]


def test_docx_findings_have_no_regions() -> None:
    text = f"Email: {EMAIL}"
    part = TextPart(text, (TextSpan(0, len(text), ()),), part_name="word/document.xml")
    document = ExtractedDocument(page(_row(0, ("x", 0, 5))).document_format, (part,))
    match = TextMatch(
        EntityType.EMAIL, 7, len(text), 0.95, "test.fixed", "1.0.0", part_name="word/document.xml"
    )
    outcome = DetectionService(_Fixed(match)).detect(document, MaskingPolicy())
    assert isinstance(outcome.findings[0].location, DocxLocation)
    assert outcome.regions == ()


def test_build_regions_only_merges_on_the_same_page() -> None:
    box = BoundingBox(0, 0, 10, _H)
    findings = [
        EntityFinding(
            FindingId(uuid4()),
            EntityType.EMAIL,
            PdfLocation(index + 1, (box,)),
            0.9,
            "test.fixed",
            "1.0.0",
            REPLACEMENT_LABELS[EntityType.EMAIL],
            False,
        )
        for index in range(2)
    ]
    assert [r.page_number for r in build_regions(findings)] == [1, 2]


@pytest.mark.parametrize(
    ("types", "winner"),
    [
        ((EntityType.PHONE, EntityType.NATIONAL_ID), EntityType.NATIONAL_ID),
        ((EntityType.PERSONAL_URL, EntityType.EMAIL), EntityType.EMAIL),
        ((EntityType.RELIGION, EntityType.GENDER), EntityType.GENDER),
    ],
    ids=("id_over_phone", "email_over_url", "tie_uses_enum_order"),
)
def test_label_winner(types: tuple[EntityType, ...], winner: EntityType) -> None:
    assert label_winner(types) is winner


def test_label_winner_needs_types() -> None:
    with pytest.raises(InvariantError):
        label_winner(())


def test_region_invariants() -> None:
    box = BoundingBox(0, 0, 1, 1)
    ident = FindingId(uuid4())
    with pytest.raises(InvariantError):
        RedactionRegion(1, (), EntityType.EMAIL, (ident,))
    with pytest.raises(InvariantError):
        RedactionRegion(1, (box,), EntityType.EMAIL, (ident, ident))
    with pytest.raises(InvariantError):
        RedactionRegion(0, (box,), EntityType.EMAIL, (ident,))
    with pytest.raises(InvariantError):
        RedactionRegion(1, (box,), EntityType.EMAIL, ())
