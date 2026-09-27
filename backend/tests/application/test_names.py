"""Stage 8: candidate/reference names, family sections, contact-block addresses.

Test ids and assertion messages carry entity types and case indexes only.
"""

import logging

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from synthetic_detections import PHONE
from synthetic_names import (
    EN_ADDRESS,
    EN_COMPANY,
    EN_EMAIL,
    EN_NAME,
    EN_REFEREE,
    EN_UNIVERSITY,
    FAMILY_LINE,
    FAMILY_LINE_2,
    UNRELATED_EMAIL,
    VN_ADDRESS,
    VN_COMPANY,
    VN_EMAIL,
    VN_NAME,
    VN_NAME_FOLDED,
    VN_NAME_SHORT,
    VN_NAME_UPPER,
    VN_REFEREE,
    VN_UNIVERSITY,
    body,
    docx,
    docx_parts,
    pdf,
    span_of,
    title,
)

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.application import DetectionOutcome, DetectionService
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import BoundingBox, PdfLocation
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.policy import REDACT_THRESHOLD, EntityType, MaskingPolicy
from cv_masking.ports.detection import PROVENANCE_REQUIRED, TextMatch
from cv_masking.ports.extraction import ExtractedDocument, TextPart, TextSpan

_NAME_TYPES = PROVENANCE_REQUIRED


@pytest.fixture
def service() -> DetectionService:
    return DetectionService(PresidioDetector())


def _run(service: DetectionService, document: ExtractedDocument) -> DetectionOutcome:
    return service.detect(document, MaskingPolicy())


def _spans(
    outcome: DetectionOutcome, entity: EntityType, part: int | str | None = None
) -> set[tuple[int, int]]:
    return {
        (match.start, match.end)
        for match in outcome.matches
        if match.entity_type is entity
        and (part is None or part in (match.page_number, match.part_name))
    }


def _only(outcome: DetectionOutcome, entity: EntityType) -> TextMatch:
    found = [match for match in outcome.matches if match.entity_type is entity]
    assert len(found) == 1, f"expected one {entity.value}, got {len(found)}"
    return found[0]


def _covered(outcome: DetectionOutcome, start: int, end: int) -> bool:
    return any(match.start < end and start < match.end for match in outcome.matches)


def test_labeled_vietnamese_name_is_exact_and_confident(service: DetectionService) -> None:
    document = docx(f"Họ và tên: {VN_NAME}", f"Điện thoại: {PHONE}", "Địa chỉ: 12 Phố Mẫu")
    text = document.parts[0].text
    outcome = _run(service, document)
    name = _only(outcome, EntityType.CANDIDATE_NAME)
    assert (name.start, name.end) == span_of(text, VN_NAME)
    assert name.confidence >= REDACT_THRESHOLD
    assert name.detector_id == "name.label"
    assert name.signals == ("label",)
    assert _spans(outcome, EntityType.POSTAL_ADDRESS) == {span_of(text, "12 Phố Mẫu")}
    assert outcome.review == frozenset()


def test_labeled_english_name_stops_at_separator(service: DetectionService) -> None:
    document = docx(f"Full name: {EN_NAME} | Email: {EN_EMAIL}")
    text = document.parts[0].text
    outcome = _run(service, document)
    assert _spans(outcome, EntityType.CANDIDATE_NAME) == {span_of(text, EN_NAME)}
    assert _spans(outcome, EntityType.EMAIL) == {span_of(text, EN_EMAIL)}


def test_label_with_unusual_casing_requires_review(service: DetectionService) -> None:
    outcome = _run(service, docx(f"Họ tên: {VN_NAME.lower()}"))
    name = _only(outcome, EntityType.CANDIDATE_NAME)
    assert name.confidence < REDACT_THRESHOLD
    assert "shape_mismatch" in name.signals
    assert ReviewReason.DETECT_LOW_CONFIDENCE in outcome.review


def test_pdf_title_uses_font_size_and_repeats_on_later_pages(service: DetectionService) -> None:
    document = pdf(
        [
            title(VN_NAME),
            body(f"Email: {UNRELATED_EMAIL}"),
            body("Kinh nghiệm làm việc"),
            body(EN_COMPANY),
        ],
        [body(f"Signed: {VN_NAME_FOLDED}"), body(f"Ref: {VN_NAME_SHORT}")],
    )
    first, second = (part.text for part in document.parts)
    outcome = _run(service, document)
    header = [m for m in outcome.matches if m.detector_id == "name.header"]
    assert len(header) == 1
    assert (header[0].start, header[0].end) == span_of(first, VN_NAME)
    assert "largest_font" in header[0].signals
    assert header[0].confidence >= REDACT_THRESHOLD
    assert _spans(outcome, EntityType.CANDIDATE_NAME, 2) == {
        span_of(second, VN_NAME_FOLDED),
        span_of(second, VN_NAME_SHORT),
    }
    repeats = [m for m in outcome.matches if m.detector_id == "name.repeat"]
    assert repeats
    assert all("repeat" in m.signals for m in repeats)
    for finding in outcome.findings:
        if finding.entity_type is EntityType.CANDIDATE_NAME:
            assert isinstance(finding.location, PdfLocation)
            assert finding.location.boxes
    assert not _covered(outcome, *span_of(first, EN_COMPANY))
    assert outcome.review == frozenset()


def test_docx_header_without_corroboration_requires_review(service: DetectionService) -> None:
    document = docx(VN_NAME, f"Email: {UNRELATED_EMAIL}", "Kỹ năng", "Python")
    outcome = _run(service, document)
    name = _only(outcome, EntityType.CANDIDATE_NAME)
    assert name.detector_id == "name.header"
    assert name.confidence < REDACT_THRESHOLD
    assert set(name.signals) == {"top_of_page", "first_line", "vn_surname"}
    assert ReviewReason.DETECT_LOW_CONFIDENCE in outcome.review


def test_docx_header_with_matching_email_is_confident(service: DetectionService) -> None:
    outcome = _run(service, docx(VN_NAME, f"Email: {VN_EMAIL}", "Kỹ năng", "Python"))
    name = _only(outcome, EntityType.CANDIDATE_NAME)
    assert "email_match" in name.signals
    assert name.confidence >= REDACT_THRESHOLD
    assert outcome.review == frozenset()


def test_english_header_without_signals_requires_review(service: DetectionService) -> None:
    outcome = _run(service, docx(EN_NAME, f"Email: {UNRELATED_EMAIL}", "Skills", "Python"))
    name = _only(outcome, EntityType.CANDIDATE_NAME)
    assert name.confidence < REDACT_THRESHOLD
    assert "vn_surname" not in name.signals
    assert ReviewReason.DETECT_LOW_CONFIDENCE in outcome.review


def test_header_part_name_repeats_into_body(service: DetectionService) -> None:
    document = docx_parts(
        {
            "word/header1.xml": [VN_NAME_UPPER],
            "word/document.xml": [f"Email: {VN_EMAIL}", "Mục tiêu", f"Tôi là {VN_NAME}."],
        }
    )
    body_text = document.parts[1].text
    outcome = _run(service, document)
    assert _spans(outcome, EntityType.CANDIDATE_NAME, "word/header1.xml") == {
        (0, len(VN_NAME_UPPER))
    }
    assert _spans(outcome, EntityType.CANDIDATE_NAME, "word/document.xml") == {
        span_of(body_text, VN_NAME)
    }


_CONFOUNDERS = (
    VN_COMPANY.upper(),
    EN_COMPANY,
    VN_UNIVERSITY.upper(),
    "Trường Đại Học Ví Dụ",
    EN_UNIVERSITY,
    "Ngân Hàng Ví Dụ",
    "Senior Software Engineer",
    "Chuyên Viên Phân Tích",
    "Thành Phố Hồ Chí Minh",
    "CURRICULUM VITAE",
    "Sơ Yếu Lý Lịch",
    "Kinh Nghiệm Làm Việc",
    "Personal Information",
)


@pytest.mark.parametrize("index", range(len(_CONFOUNDERS)), ids=lambda i: f"confounder_{i}")
def test_confounder_header_is_not_a_name(service: DetectionService, index: int) -> None:
    outcome = _run(service, docx(_CONFOUNDERS[index], f"Email: {UNRELATED_EMAIL}"))
    assert not _spans(outcome, EntityType.CANDIDATE_NAME), f"confounder {index}"
    assert ReviewReason.DETECT_NO_CANDIDATE_NAME in outcome.review


def test_company_and_education_lines_after_headings_are_not_names(
    service: DetectionService,
) -> None:
    lines = (
        f"Họ và tên: {VN_NAME}",
        "Kinh nghiệm làm việc",
        "Example Bank Ltd",
        "Chuyên Viên Phân Tích",
        "Học vấn",
        "Trường Đại Học Ví Dụ",
        EN_UNIVERSITY,
        "Education",
        "Example Institute Of Technology",
    )
    outcome = _run(service, docx(*lines))
    names = [m for m in outcome.matches if m.entity_type in _NAME_TYPES]
    assert len(names) == 1
    assert names[0].detector_id == "name.label"


def test_reference_section_names_and_companies(service: DetectionService) -> None:
    lines = (
        f"Họ và tên: {VN_NAME}",
        "Người tham chiếu",
        f"Bà {VN_REFEREE} - Trưởng phòng, {VN_COMPANY}",
        f"{EN_REFEREE} | {EN_COMPANY} | Email: {EN_EMAIL}",
        "Kỹ năng",
        "Excel",
    )
    document = docx(*lines)
    text = document.parts[0].text
    outcome = _run(service, document)
    referees = {
        (m.start, m.end): m for m in outcome.matches if m.entity_type is EntityType.REFERENCE_NAME
    }
    assert set(referees) == {span_of(text, VN_REFEREE), span_of(text, EN_REFEREE)}
    honorific = referees[span_of(text, VN_REFEREE)]
    assert honorific.signals == ("reference_section", "honorific")
    assert honorific.confidence >= REDACT_THRESHOLD
    line_start = referees[span_of(text, EN_REFEREE)]
    assert line_start.signals == ("reference_section", "line_start")
    assert line_start.confidence < REDACT_THRESHOLD
    assert not _covered(outcome, *span_of(text, VN_COMPANY))
    assert not _covered(outcome, *span_of(text, EN_COMPANY))
    email = _only(outcome, EntityType.EMAIL)
    assert email.detector_id == "email.reference"
    assert ReviewReason.DETECT_LOW_CONFIDENCE in outcome.review


def test_labeled_referee_inside_reference_section(service: DetectionService) -> None:
    lines = (f"Họ và tên: {VN_NAME}", "References", f"Name: {EN_REFEREE}", "Skills", "Excel")
    document = docx(*lines)
    text = document.parts[0].text
    outcome = _run(service, document)
    referee = _only(outcome, EntityType.REFERENCE_NAME)
    assert (referee.start, referee.end) == span_of(text, EN_REFEREE)
    assert referee.detector_id == "reference_name.label"
    assert _spans(outcome, EntityType.CANDIDATE_NAME) == {span_of(text, VN_NAME)}


def test_family_section_covers_whole_block(service: DetectionService) -> None:
    lines = (
        f"Họ và tên: {VN_NAME}",
        "Thông tin gia đình",
        FAMILY_LINE,
        FAMILY_LINE_2,
        "Sở thích",
        "Đọc sách",
    )
    document = docx(*lines)
    text = document.parts[0].text
    outcome = _run(service, document)
    family = _only(outcome, EntityType.FAMILY_DETAILS)
    start = span_of(text, FAMILY_LINE)[0]
    end = span_of(text, FAMILY_LINE_2)[1]
    assert (family.start, family.end) == (start, end)
    assert family.signals == ("section_heading",)
    assert family.confidence >= REDACT_THRESHOLD
    inside = [m for m in outcome.matches if start <= m.start and m.end <= end]
    assert [m.entity_type for m in inside] == [EntityType.FAMILY_DETAILS]
    assert not _covered(outcome, *span_of(text, "Đọc sách"))


def test_inline_family_heading(service: DetectionService) -> None:
    document = docx(f"Họ và tên: {VN_NAME}", f"Family: {FAMILY_LINE_2}", "Skills", "Excel")
    text = document.parts[0].text
    outcome = _run(service, document)
    assert _spans(outcome, EntityType.FAMILY_DETAILS) == {span_of(text, FAMILY_LINE_2)}


@pytest.mark.parametrize("index", range(2), ids=("vn_address", "en_address"))
def test_unlabeled_contact_block_address(service: DetectionService, index: int) -> None:
    address = (VN_ADDRESS, EN_ADDRESS)[index]
    lines = (
        VN_NAME,
        f"{address} | {PHONE}",
        f"Email: {VN_EMAIL}",
        "Kinh nghiệm",
        f"{EN_COMPANY}, 2 Example Street, Sample Ward",
    )
    document = docx(*lines)
    text = document.parts[0].text
    outcome = _run(service, document)
    found = _only(outcome, EntityType.POSTAL_ADDRESS)
    assert (found.start, found.end) == span_of(text, address)
    assert found.detector_id == "address.contact_block"
    assert found.confidence >= REDACT_THRESHOLD
    assert _spans(outcome, EntityType.PHONE) == {span_of(text, PHONE)}


def test_weak_contact_block_address_requires_review(service: DetectionService) -> None:
    outcome = _run(service, docx(f"Họ và tên: {VN_NAME}", "Quận Mẫu, Thành phố Thử"))
    found = _only(outcome, EntityType.POSTAL_ADDRESS)
    assert found.confidence < REDACT_THRESHOLD
    assert outcome.review == frozenset({ReviewReason.DETECT_LOW_CONFIDENCE})


def test_city_alone_is_not_an_address(service: DetectionService) -> None:
    outcome = _run(service, docx(f"Họ và tên: {VN_NAME}", "Thành phố Hồ Chí Minh"))
    assert not _spans(outcome, EntityType.POSTAL_ADDRESS)


def test_document_without_candidate_name_requires_review(service: DetectionService) -> None:
    outcome = _run(service, docx(f"Email: {UNRELATED_EMAIL}", "Skills", "Python"))
    assert not _spans(outcome, EntityType.CANDIDATE_NAME)
    assert outcome.review == frozenset({ReviewReason.DETECT_NO_CANDIDATE_NAME})


def test_pdf_match_without_boxes_fails_mapping(service: DetectionService) -> None:
    text = f"Email: {UNRELATED_EMAIL}"
    part = TextPart(text, (TextSpan(0, 5, (BoundingBox(0.0, 0.0, 5.0, 10.0),)),), page_number=1)
    outcome = _run(service, ExtractedDocument(DocumentFormat.PDF, (part,)))
    assert outcome.failure is ErrorCode.MAP_FAILED
    assert outcome.findings == ()


@pytest.mark.parametrize("entity", sorted(_NAME_TYPES), ids=lambda e: e.value.lower())
def test_heuristic_types_require_signals(entity: EntityType) -> None:
    with pytest.raises(InvariantError):
        TextMatch(entity, 0, 4, 0.9, "name.label", "1.1.0", part_name="word/document.xml")


def test_unknown_signal_is_rejected() -> None:
    with pytest.raises(InvariantError):
        TextMatch(
            EntityType.CANDIDATE_NAME,
            0,
            4,
            0.9,
            "name.label",
            "1.1.0",
            part_name="word/document.xml",
            signals=(VN_NAME_FOLDED.split()[0].lower(),),
        )


def _bilingual() -> tuple[ExtractedDocument, list[tuple[EntityType, int, int]]]:
    lines = (
        VN_NAME,
        f"{VN_ADDRESS} | {PHONE}",
        f"Email: {VN_EMAIL}",
        "Kinh nghiệm làm việc / Work experience",
        f"{EN_COMPANY} - Senior Analyst",
        VN_COMPANY.upper(),
        "Học vấn / Education",
        EN_UNIVERSITY,
        "Thông tin gia đình",
        FAMILY_LINE,
        "Người tham chiếu / References",
        f"Ông {EN_REFEREE} - {EN_COMPANY}",
        "Kỹ năng",
        f"Cam đoan: {VN_NAME_FOLDED}",
    )
    document = docx(*lines)
    text = document.parts[0].text
    gold = [
        (EntityType.CANDIDATE_NAME, *span_of(text, VN_NAME)),
        (EntityType.CANDIDATE_NAME, *span_of(text, VN_NAME_FOLDED)),
        (EntityType.POSTAL_ADDRESS, *span_of(text, VN_ADDRESS)),
        (EntityType.FAMILY_DETAILS, *span_of(text, FAMILY_LINE)),
        (EntityType.REFERENCE_NAME, *span_of(text, EN_REFEREE)),
    ]
    return document, gold


def test_bilingual_corpus_precision_and_recall(service: DetectionService) -> None:
    document, gold = _bilingual()
    outcome = _run(service, document)
    for entity in {kind for kind, _, _ in gold}:
        expected = {(s, e) for kind, s, e in gold if kind is entity}
        predicted = _spans(outcome, entity)
        assert predicted == expected, f"{entity.value} spans differ"
    assert not _covered(outcome, *span_of(document.parts[0].text, EN_UNIVERSITY))


def test_every_heuristic_result_has_provenance(service: DetectionService) -> None:
    document, _ = _bilingual()
    outcome = _run(service, document)
    heuristic = [m for m in outcome.matches if m.entity_type in _NAME_TYPES]
    assert len(heuristic) >= 4
    for match in heuristic:
        assert match.signals
        assert match.detector_version == "1.1.0"
    for finding in outcome.findings:
        assert finding.requires_review == (finding.confidence < REDACT_THRESHOLD)


def test_results_and_logs_never_include_values(
    service: DetectionService, caplog: pytest.LogCaptureFixture
) -> None:
    document, _ = _bilingual()
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        outcome = _run(service, document)
    dumped = repr(outcome.findings) + repr(outcome.matches)
    logged = " ".join(record.getMessage() for record in caplog.records)
    for fragment in (
        VN_NAME,
        VN_NAME_FOLDED,
        EN_REFEREE,
        VN_ADDRESS,
        "Nguyen",
        "nguyen",
        "Mẫu",
        "mau",
        "Sample",
    ):
        assert fragment not in dumped
        assert fragment not in logged


_SURNAMES = ("Nguyễn", "Trần")
_MIDDLES = ("Văn", "Thị")
_GIVEN = ("Mẫu", "Thử")
_LABELS = ("Họ và tên", "Họ tên", "Tên", "Full name", "Name", "HỌ VÀ TÊN")


@settings(max_examples=60, deadline=None)
@given(
    surname=st.sampled_from(_SURNAMES),
    middle=st.sampled_from(_MIDDLES),
    given_name=st.sampled_from(_GIVEN),
    label=st.sampled_from(_LABELS),
    upper=st.booleans(),
    spacing=st.sampled_from((":", " :", ": ", "\uff1a")),
)
def test_labeled_synthetic_names_property(
    surname: str, middle: str, given_name: str, label: str, upper: bool, spacing: str
) -> None:
    name = f"{surname} {middle} {given_name}"
    if upper:
        name = name.upper()
    line = f"{label}{spacing} {name}"
    outcome = DetectionService(PresidioDetector()).detect(docx(line), MaskingPolicy())
    assert _spans(outcome, EntityType.CANDIDATE_NAME) == {span_of(line, name)}
    assert _only(outcome, EntityType.CANDIDATE_NAME).confidence >= REDACT_THRESHOLD
