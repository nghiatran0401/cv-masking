import logging
from collections.abc import Callable

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st
from synthetic_detections import (
    CCCD,
    CMND,
    EMAIL,
    LANDLINE,
    PASSPORT,
    PHONE,
    PHONE_PLUS,
    REF_EMAIL,
    URL,
    corpus,
    extracted,
)

from cv_masking.adapters.detection import PresidioDetector
from cv_masking.application import DetectionService
from cv_masking.domain.codes import ReviewReason
from cv_masking.domain.findings import PdfLocation
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.ports.extraction import ExtractedDocument


@pytest.fixture
def service() -> DetectionService:
    return DetectionService(PresidioDetector())


def _types(document: ExtractedDocument, service: DetectionService) -> list[EntityType]:
    return [match.entity_type for match in service.detect(document, MaskingPolicy()).matches]


def _has(service: DetectionService, text: str, entity: EntityType) -> bool:
    return entity in _types(extracted(text), service)


@pytest.mark.parametrize(
    ("builder", "entity"),
    [
        (lambda: f"Email: {EMAIL}", EntityType.EMAIL),
        (lambda: f"Dien thoai {PHONE}", EntityType.PHONE),
        (lambda: f"Mobile {PHONE_PLUS}", EntityType.PHONE),
        (lambda: f"DT {LANDLINE}", EntityType.PHONE),
        (lambda: f"CCCD {CCCD}", EntityType.NATIONAL_ID),
        (lambda: f"CMND: {CMND}", EntityType.NATIONAL_ID),
        (lambda: f"Ho chieu: {PASSPORT}", EntityType.PASSPORT),
        (lambda: "Gioi tinh: Nu", EntityType.GENDER),
        (lambda: "Marital status: Single", EntityType.MARITAL_STATUS),
        (lambda: "Quoc tich: Viet Nam", EntityType.NATIONALITY),
        (lambda: "Ton giao: Khong", EntityType.RELIGION),
        (lambda: "Dan toc: Kinh", EntityType.ETHNICITY),
        (lambda: "Chieu cao: 170 cm", EntityType.HEALTH),
        (lambda: "Dia chi: 12 Pho Mau", EntityType.POSTAL_ADDRESS),
        (lambda: "Ngay sinh: 01/01/1990", EntityType.DATE_OF_BIRTH),
        (lambda: "Tuoi: 34", EntityType.DATE_OF_BIRTH),
        (lambda: "Age: 34", EntityType.DATE_OF_BIRTH),
        (lambda: "Muc luong: 15 trieu", EntityType.SALARY),
    ],
    ids=(
        "email",
        "phone_mobile",
        "phone_plus",
        "phone_landline",
        "cccd",
        "cmnd",
        "passport",
        "gender",
        "marital",
        "nationality",
        "religion",
        "ethnicity",
        "health",
        "address",
        "dob",
        "age",
        "age_en",
        "salary",
    ),
)
def test_detects_each_stage7_type(
    service: DetectionService, builder: Callable[[], str], entity: EntityType
) -> None:
    assert _has(service, builder(), entity)


def test_dob_label_does_not_take_employment_years(service: DetectionService) -> None:
    text = "Ngay sinh: 01/01/1990 Experience Example Bank Ltd 2019-2023"
    outcome = service.detect(extracted(text), MaskingPolicy())
    dobs = [match for match in outcome.matches if match.entity_type is EntityType.DATE_OF_BIRTH]
    assert len(dobs) == 1
    assert text[dobs[0].start : dobs[0].end] == "01/01/1990"


def test_a_redacted_contact_line_is_not_a_new_dob(service: DetectionService) -> None:
    text = "Ngay sinh: [DOB] | LinkedIn: [URL] | Github: [URL]"
    types = set(_types(extracted(text), service))
    assert EntityType.DATE_OF_BIRTH not in types
    assert EntityType.PERSONAL_URL not in types


def test_year_of_birth_after_nam_sinh_is_detected(service: DetectionService) -> None:
    assert _has(service, "Nam sinh: 1990", EntityType.DATE_OF_BIRTH)


@pytest.mark.parametrize(
    ("builder", "forbidden"),
    [
        (lambda: "Kinh nghiem 2019-2023 tai Example Bank Ltd", EntityType.DATE_OF_BIRTH),
        (lambda: f"Ma so {CMND}", EntityType.NATIONAL_ID),
        (lambda: "Thuong 15 trieu khi phu hop", EntityType.SALARY),
        (lambda: "Skills: Python Java SQL", EntityType.CANDIDATE_NAME),
        (lambda: f"So hieu {PASSPORT}", EntityType.PASSPORT),
        (lambda: "Nam tinh nguyen vien", EntityType.GENDER),
        (lambda: "Lam viec tai Ha Noi 2020", EntityType.POSTAL_ADDRESS),
        (lambda: "Built a multi-agent system in Python", EntityType.DATE_OF_BIRTH),
        (lambda: f"Portfolio {URL}", EntityType.PERSONAL_URL),
        (lambda: f"LinkedIn: {URL}", EntityType.PERSONAL_URL),
        (lambda: "Lien he: https://example.test/portfolio", EntityType.PERSONAL_URL),
    ],
    ids=(
        "work_years",
        "unlabeled_cmnd",
        "unlabeled_salary",
        "skills",
        "unlabeled_passport",
        "nam",
        "city_year",
        "agent",
        "portfolio_url",
        "linkedin",
        "contact_http",
    ),
)
def test_false_positives_are_not_detected(
    service: DetectionService, builder: Callable[[], str], forbidden: EntityType
) -> None:
    types = set(_types(extracted(builder()), service))
    assert forbidden not in types
    assert EntityType.CANDIDATE_NAME not in types
    assert EntityType.REFERENCE_NAME not in types
    assert EntityType.FAMILY_DETAILS not in types


def test_overlap_prefers_national_id_and_email(service: DetectionService) -> None:
    twelve = "000000000012"
    outcome = service.detect(extracted(f"ID {twelve} and mailto:{EMAIL}"), MaskingPolicy())
    types = {match.entity_type for match in outcome.matches}
    assert EntityType.NATIONAL_ID in types
    assert EntityType.EMAIL in types
    assert EntityType.PHONE not in types


def test_salary_is_found_when_toggle_is_off(service: DetectionService) -> None:
    document = extracted("Muc luong mong muon: 20.000.000 VND")
    off = service.detect(document, MaskingPolicy(mask_salary=False))
    on = service.detect(document, MaskingPolicy(mask_salary=True))
    assert EntityType.SALARY in {match.entity_type for match in off.matches}
    assert EntityType.SALARY in {match.entity_type for match in on.matches}
    assert len(off.matches) == len(on.matches)


def test_reference_contacts_are_classified(service: DetectionService) -> None:
    text = f"Nguoi tham chieu\nEmail: {REF_EMAIL}\nDT: {PHONE}\nKinh nghiem\nPython"
    outcome = service.detect(extracted(text), MaskingPolicy())
    detectors = {match.detector_id for match in outcome.matches}
    assert "email.reference" in detectors
    assert "phone.reference" in detectors


def test_findings_and_logs_never_include_values(
    service: DetectionService, caplog: pytest.LogCaptureFixture
) -> None:
    document = extracted(f"Email: {EMAIL}\nCCCD {CCCD}")
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        outcome = service.detect(document, MaskingPolicy())
    dumped = repr(outcome.findings) + repr(outcome.matches)
    logged = " ".join(record.getMessage() for record in caplog.records)
    for fragment in (EMAIL, CCCD, "Nguyen", "Mẫu"):
        assert fragment not in dumped
        assert fragment not in logged
    assert outcome.findings
    assert all(
        finding.entity_type is EntityType.EMAIL or finding.entity_type is EntityType.NATIONAL_ID
        for finding in outcome.findings
    )


def test_pdf_part_maps_to_boxes(service: DetectionService) -> None:
    document = extracted(f"Email: {EMAIL}", fmt=DocumentFormat.PDF)
    outcome = service.detect(document, MaskingPolicy())
    assert outcome.findings
    location = outcome.findings[0].location
    assert isinstance(location, PdfLocation)
    assert location.page_number == 1
    assert location.boxes


def test_personal_urls_are_not_detected(service: DetectionService) -> None:
    outcome = service.detect(
        extracted(f"Lien he: {URL}\nGitHub: https://github.com/mau-example"),
        MaskingPolicy(),
    )
    assert EntityType.PERSONAL_URL not in {match.entity_type for match in outcome.matches}
    assert ReviewReason.DETECT_LOW_CONFIDENCE not in outcome.review


def test_corpus_precision_and_recall(service: DetectionService) -> None:
    document, gold = corpus()
    outcome = service.detect(document, MaskingPolicy())
    predicted = [(match.entity_type, match.start, match.end) for match in outcome.matches]
    by_type = {entity for entity, _, _ in gold}
    for entity in by_type:
        gold_spans = {(start, end) for kind, start, end in gold if kind is entity}
        pred_spans = {(start, end) for kind, start, end in predicted if kind is entity}
        true_pos = gold_spans & pred_spans
        precision = len(true_pos) / len(pred_spans) if pred_spans else 0.0
        recall = len(true_pos) / len(gold_spans) if gold_spans else 0.0
        assert (precision, recall) == (1.0, 1.0), entity.value
    assert EntityType.PERSONAL_URL not in {kind for kind, _, _ in predicted}


@settings(deadline=None, derandomize=True, database=None, max_examples=25)
@given(
    st.from_regex(r"[a-z]{3,8}", fullmatch=True),
    st.sampled_from(("example.test", "example.invalid")),
)
def test_generated_emails_are_detected(local: str, domain: str) -> None:
    service = DetectionService(PresidioDetector())
    text = f"Email: {local}@{domain}"
    types = _types(extracted(text), service)
    if EntityType.EMAIL not in types:
        raise AssertionError("generated email was not detected")


@settings(deadline=None, derandomize=True, database=None, max_examples=25)
@given(st.integers(min_value=0, max_value=99))
def test_generated_reserved_mobiles_are_detected(suffix: int) -> None:
    service = DetectionService(PresidioDetector())
    number = f"09000000{suffix:02d}"
    types = _types(extracted(f"DT {number}"), service)
    if EntityType.PHONE not in types:
        raise AssertionError("generated phone was not detected")


def test_text_without_identifiers_has_no_stage7_hits(service: DetectionService) -> None:
    types = set(_types(extracted("Ky nang Python tai Example Bank Ltd"), service))
    assert types == set()
