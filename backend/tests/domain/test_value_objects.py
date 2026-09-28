from uuid import NAMESPACE_DNS, UUID, uuid4, uuid5

import pytest
from domain_builders import T0, new_finding_id, new_object_ref

from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.findings import BoundingBox, DocxLocation, EntityFinding, PdfLocation
from cv_masking.domain.hidden import (
    NO_HIDDEN_CONTENT,
    HiddenContentAlert,
    HiddenContentCategory,
    HiddenContentCounts,
)
from cv_masking.domain.ids import BatchId, DocumentId, FindingId, ObjectRef, Sha256Digest
from cv_masking.domain.policy import REPLACEMENT_LABELS, EntityType
from cv_masking.domain.verification import (
    VERIFY_FAILURE_PRECEDENCE,
    VerificationOutcome,
    VerificationResult,
)

BOX = BoundingBox(10.0, 20.0, 110.0, 32.5)


def test_ids_accept_only_random_uuids() -> None:
    for id_type in (BatchId, DocumentId, FindingId, ObjectRef):
        assert str(id_type(value := uuid4())) == str(value)
        for bad in (NAMESPACE_DNS, uuid5(NAMESPACE_DNS, "synthetic.example"), UUID(int=0), "x"):
            with pytest.raises(InvariantError):
                id_type(bad)  # type: ignore[arg-type]


def test_digest_accepts_only_lowercase_sha256_hex() -> None:
    assert str(Sha256Digest("0f" * 32)) == "0f" * 32
    for bad in ("0F" * 32, "0f" * 31, "g" * 64):
        with pytest.raises(InvariantError):
            Sha256Digest(bad)


def test_docx_location_accepts_only_word_xml_parts() -> None:
    assert DocxLocation("word/header1.xml", 0, 5).part_name == "word/header1.xml"
    for part in ("../word/document.xml", "/word/document.xml", "word/_rels/document.xml.rels"):
        with pytest.raises(InvariantError):
            DocxLocation(part, 0, 5)


def _finding(**changes: object) -> EntityFinding:
    values: dict[str, object] = {
        "finding_id": new_finding_id(),
        "entity_type": EntityType.EMAIL,
        "location": PdfLocation(1, (BOX,)),
        "confidence": 0.9,
        "detector_id": "regex.email",
        "detector_version": "1.0.0",
        "replacement_label": REPLACEMENT_LABELS[EntityType.EMAIL],
        "requires_review": False,
    }
    values.update(changes)
    return EntityFinding(**values)  # type: ignore[arg-type]


def test_finding_refuses_free_text_in_its_string_fields() -> None:
    assert _finding().detector_id == "regex.email"
    for changes in (
        {"detector_id": "Nguyen Van A"},
        {"detector_id": "synthetic@example.test"},
        {"replacement_label": "synthetic.person@example.test"},
        {"replacement_label": "[PHONE]"},
        {"confidence": 1.5},
    ):
        with pytest.raises(InvariantError):
            _finding(**changes)


def _result(**changes: object) -> VerificationResult:
    values: dict[str, object] = {
        "outcome": VerificationOutcome.PASSED,
        "failure_codes": frozenset(),
        "output_ref": new_object_ref(),
        "verifier_id": "pdf-verifier",
        "verifier_version": "1.0.0",
        "verified_at": T0,
    }
    values.update(changes)
    return VerificationResult(**values)  # type: ignore[arg-type]


def test_verification_result_is_consistent() -> None:
    codes = frozenset(VERIFY_FAILURE_PRECEDENCE[1:])
    failed = _result(outcome=VerificationOutcome.FAILED, failure_codes=codes)
    assert failed.primary_failure_code is VERIFY_FAILURE_PRECEDENCE[1]
    for changes in (
        {"outcome": VerificationOutcome.FAILED},
        {"failure_codes": frozenset({ErrorCode.VERIFY_RESIDUAL_FINDING})},
        {"outcome": VerificationOutcome.FAILED, "failure_codes": {ErrorCode.REDACT_FAILED}},
        {"verifier_id": "Verifier For Nguyen"},
    ):
        with pytest.raises(InvariantError):
            _result(**changes)


def test_hidden_content_counts_total_alerts_per_category_in_category_order() -> None:
    alerts = (
        HiddenContentAlert(HiddenContentCategory.COMMENTS, 2, parts=("comments",)),
        HiddenContentAlert(HiddenContentCategory.ANNOTATIONS, 1, pages=(1,)),
        HiddenContentAlert(HiddenContentCategory.COMMENTS, 3, parts=("footnotes",)),
    )
    counts = HiddenContentCounts.from_alerts(alerts)
    assert counts.items == (
        (HiddenContentCategory.ANNOTATIONS, 1),
        (HiddenContentCategory.COMMENTS, 5),
    )
    assert counts.as_dict() == {
        HiddenContentCategory.ANNOTATIONS: 1,
        HiddenContentCategory.COMMENTS: 5,
    }
    assert HiddenContentCounts.from_alerts(()) == NO_HIDDEN_CONTENT


@pytest.mark.parametrize(
    "items",
    [
        [(HiddenContentCategory.COMMENTS, 1)],
        ((HiddenContentCategory.COMMENTS, 0),),
        ((HiddenContentCategory.COMMENTS, True),),
        (("comments", 1),),
        ((HiddenContentCategory.COMMENTS, 1), (HiddenContentCategory.COMMENTS, 1)),
        ((HiddenContentCategory.COMMENTS, 1), (HiddenContentCategory.ANNOTATIONS, 1)),
        ((HiddenContentCategory.COMMENTS,),),
    ],
    ids=["list", "zero", "bool", "plain-string", "repeated", "out-of-order", "not-a-pair"],
)
def test_hidden_content_counts_refuse_malformed_items(items: object) -> None:
    with pytest.raises(InvariantError):
        HiddenContentCounts(items)  # type: ignore[arg-type]
