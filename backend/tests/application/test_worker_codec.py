"""Stage 12: worker messages round-trip exactly and malformed replies are refused."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from cv_masking.adapters.worker import codec
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.findings import FindingCounts
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory, HiddenContentCounts
from cv_masking.domain.ids import ObjectRef, Sha256Digest
from cv_masking.domain.policy import EntityType, MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult
from cv_masking.ports.processing import ProcessingReport, ValidationReport, VerificationReport
from cv_masking.ports.storage import StoredObject

_STORED = StoredObject(ObjectRef(uuid4()), DocumentFormat.DOCX, Sha256Digest("b" * 64), 42)
_RESULT = VerificationResult(
    outcome=VerificationOutcome.FAILED,
    failure_codes=frozenset({ErrorCode.VERIFY_RESIDUAL_FINDING}),
    output_ref=ObjectRef(uuid4()),
    verifier_id="stub-verifier",
    verifier_version="1.2.3",
    verified_at=datetime(2026, 1, 2, 3, 4, 5, 6, tzinfo=UTC),
)


def _wire(message: codec.Json) -> codec.Json:
    return codec.decode(codec.encode(message))


def test_requests_round_trip() -> None:
    assert codec.stored_from_json(_wire(codec.stored_to_json(_STORED))) == _STORED
    policy = MaskingPolicy(mask_salary=False)
    assert codec.policy_from_json(_wire(codec.policy_to_json(policy))) == policy


@pytest.mark.parametrize(
    "report",
    [
        ValidationReport(),
        ValidationReport(failure=ErrorCode.DOCX_MALFORMED),
        ValidationReport(review=frozenset({ReviewReason.DOCX_ENCRYPTED})),
        ValidationReport(
            hidden_removed=HiddenContentCounts(
                ((HiddenContentCategory.TRACKED_CHANGES, 1), (HiddenContentCategory.COMMENTS, 3))
            )
        ),
    ],
    ids=["passed", "failed", "review", "hidden"],
)
def test_validation_reports_round_trip(report: ValidationReport) -> None:
    assert codec.validation_from_json(_wire(codec.validation_to_json(report))) == report


@pytest.mark.parametrize(
    "report",
    [
        ProcessingReport(
            output=b"%PDF-synthetic output\n",
            finding_counts=FindingCounts(((EntityType.EMAIL, 2),)),
            review=frozenset({ReviewReason.MAP_AMBIGUOUS}),
        ),
        ProcessingReport(failure=ErrorCode.REDACT_FAILED),
    ],
    ids=["output", "failed"],
)
def test_processing_reports_round_trip(report: ProcessingReport) -> None:
    message = _wire(codec.processing_to_json(report))
    assert codec.processing_from_json(message, report.output) == report
    assert b"synthetic output" not in codec.encode(message)


@pytest.mark.parametrize(
    "report",
    [
        VerificationReport(result=_RESULT),
        VerificationReport(failure=ErrorCode.STORAGE_WRITE_FAILED),
    ],
    ids=["result", "failed"],
)
def test_verification_reports_round_trip(report: VerificationReport) -> None:
    assert codec.verification_from_json(_wire(codec.verification_to_json(report))) == report


@pytest.mark.parametrize(
    "raw", [b"", b"\xff", b"[1]", b'"text"', b"{"], ids=["empty", "utf8", "list", "str", "cut"]
)
def test_undecodable_messages_are_refused(raw: bytes) -> None:
    with pytest.raises(codec.CodecError):
        codec.decode(raw)


@pytest.mark.parametrize(
    "change",
    [
        {"failure": "NOT_A_CODE"},
        {"failure": "VERIFY_REVIEW"},
        {"failure": ErrorCode.REDACT_FAILED.value},
        {"review": ["DETECT_LOW_CONFIDENCE"]},
        {"review": "PDF_ENCRYPTED"},
        {"hidden": [["annotations", True]]},
        {"hidden": [["annotations", 0]]},
        {"hidden": [["not_a_category", 1]]},
        {"hidden": [["annotations", 1], ["annotations", 1]]},
        {"hidden": {"annotations": 1}},
    ],
    ids=[
        "unknown-code",
        "reason-as-code",
        "wrong-stage-code",
        "findings-reason",
        "reasons-not-list",
        "bool-count",
        "zero-count",
        "unknown-category",
        "repeated-category",
        "hidden-not-list",
    ],
)
def test_malformed_validation_replies_are_refused(change: codec.Json) -> None:
    message = {**codec.validation_to_json(ValidationReport()), **change}
    with pytest.raises(codec.CodecError):
        codec.validation_from_json(message)


@pytest.mark.parametrize(
    ("change", "output"),
    [
        ({}, None),
        ({"counts": None}, b"%PDF-synthetic\n"),
        ({"counts": [["email", -1]]}, b"%PDF-synthetic\n"),
        ({"counts": [["salary_text", 1]]}, b"%PDF-synthetic\n"),
        ({"failure": "REDACT_FAILED"}, b"%PDF-synthetic\n"),
        ({}, b""),
    ],
    ids=["no-output", "no-counts", "negative", "unknown-type", "both", "empty-output"],
)
def test_malformed_processing_replies_are_refused(change: codec.Json, output: bytes | None) -> None:
    valid = ProcessingReport(output=b"%PDF-synthetic\n", finding_counts=FindingCounts(()))
    message = {**codec.processing_to_json(valid), **change}
    with pytest.raises(codec.CodecError):
        codec.processing_from_json(message, output)


@pytest.mark.parametrize(
    "change",
    [
        {"outcome": "passed"},
        {"verified_at": "2026-01-02T03:04:05"},
        {"verified_at": 5},
        {"output_ref": "not-a-uuid"},
        {"codes": ["INTERNAL_ERROR"]},
        {"verifier_id": "Bad Id With Spaces"},
    ],
    ids=["passed-with-codes", "naive-time", "time-type", "bad-ref", "non-verify-code", "bad-id"],
)
def test_malformed_verification_replies_are_refused(change: codec.Json) -> None:
    message = codec.verification_to_json(VerificationReport(result=_RESULT))
    result = message["result"]
    assert isinstance(result, dict)
    with pytest.raises(codec.CodecError):
        codec.verification_from_json({**message, "result": {**result, **change}})


def test_a_stored_object_with_a_wrong_shape_is_refused() -> None:
    message = codec.stored_to_json(_STORED)
    for change in ({"size": True}, {"size": "42"}, {"sha256": "x"}, {"format": "doc"}):
        with pytest.raises(codec.CodecError):
            codec.stored_from_json({**message, **change})
