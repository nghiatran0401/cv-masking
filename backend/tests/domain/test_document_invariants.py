"""A DocumentJob rebuilt from stored fields fails closed on impossible combinations."""

from collections.abc import Callable
from datetime import datetime, timedelta
from uuid import uuid4

import pytest
from domain_builders import (
    COUNTS,
    completed,
    created,
    failed,
    findings_review,
    job_in_state,
    new_object_ref,
    processing,
    queued,
    rebuild,
    uploaded,
    validating,
    validation_review,
    verification_for,
    verifier_review,
    verifying,
)

from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.verification import VerificationOutcome

S = DocumentState
E = ErrorCode
R = ReviewReason
type Case = tuple[Callable[[], DocumentJob], dict[str, object]]


def _failed_verification(job: DocumentJob) -> object:
    return verification_for(job, VerificationOutcome.FAILED, frozenset({E.VERIFY_OUTPUT_INVALID}))


INVALID: dict[str, Case] = {
    # types
    "raw-uuid-document-id": (created, {"document_id": uuid4()}),
    "raw-uuid-batch-id": (created, {"batch_id": uuid4()}),
    "string-state": (created, {"state": "created"}),
    "string-format": (uploaded, {"document_format": "pdf"}),
    "string-digest": (uploaded, {"content_sha256": "ab" * 32}),
    "bool-version": (created, {"version": True}),
    "negative-version": (created, {"version": -1}),
    "set-review-reasons": (validation_review, {"review_reasons": {R.PDF_HIDDEN_CONTENT}}),
    "string-review-reason": (validation_review, {"review_reasons": frozenset({"x"})}),
    "string-error-code": (failed, {"error_code": "PDF_MALFORMED"}),
    "int-approval-flag": (queued, {"hidden_content_approved": 1}),
    # time
    "naive-created-at": (created, {"created_at": datetime(2026, 1, 1)}),
    "updated-before-created": (
        uploaded,
        {"updated_at": datetime.fromisoformat("2025-12-31T00:00:00+00:00")},
    ),
    # upload fields
    "created-with-upload": (
        uploaded,
        {"state": S.CREATED},
    ),
    "partial-upload": (uploaded, {"content_sha256": None}),
    "upload-without-input-ref": (uploaded, {"input_ref": None}),
    "raw-uuid-input-ref": (uploaded, {"input_ref": uuid4()}),
    "zero-size": (uploaded, {"size_bytes": 0}),
    "oversize": (uploaded, {"size_bytes": 20 * 1024 * 1024 + 1}),
    "uploaded-after-updated": (
        uploaded,
        {"uploaded_at": datetime.fromisoformat("2027-01-01T00:00:00+00:00")},
    ),
    # processing fields
    "attempt-over-limit": (processing, {"attempt": 4}),
    "processing-without-policy": (processing, {"policy": None}),
    "processing-without-attempt": (processing, {"attempt": 0}),
    "queued-with-output": (queued, {"output_ref": new_object_ref()}),
    "queued-with-counts": (queued, {"finding_counts": COUNTS}),
    "verifying-without-output": (verifying, {"output_ref": None}),
    "verifying-with-verification": (completed, {"state": S.VERIFYING}),
    "verification-for-other-output": (completed, {"output_ref": new_object_ref()}),
    "hidden-approval-before-validation": (validating, {"hidden_content_approved": True}),
    "findings-approval-not-completed": (queued, {"findings_review_approved": True}),
    # review fields
    "review-without-reasons": (validation_review, {"review_reasons": frozenset()}),
    "validation-review-with-output": (validation_review, {"output_ref": new_object_ref()}),
    "mixed-review-kinds": (
        findings_review,
        {"review_reasons": frozenset({R.PDF_HIDDEN_CONTENT, R.DETECT_LOW_CONFIDENCE})},
    ),
    "findings-review-without-verification": (
        findings_review,
        {"verification": None},
    ),
    "verify-review-with-passed-result": (
        findings_review,
        {"review_reasons": frozenset({R.VERIFY_REVIEW})},
    ),
    "verifier-outcome-without-verify-review": (
        verifier_review,
        {"review_reasons": frozenset({R.DETECT_LOW_CONFIDENCE})},
    ),
    "verifying-with-hidden-reason": (
        verifying,
        {"review_reasons": frozenset({R.PDF_HIDDEN_CONTENT})},
    ),
    "queued-with-reasons": (queued, {"review_reasons": frozenset({R.PDF_HIDDEN_CONTENT})}),
    # outcome fields
    "completed-without-verification": (completed, {"verification": None}),
    "completed-without-counts": (completed, {"finding_counts": None}),
    "failed-without-code": (failed, {"error_code": None}),
    "failed-with-cancelled-code": (failed, {"error_code": E.JOB_CANCELLED}),
    "failed-with-security-code": (failed, {"error_code": E.SECURITY_TOKEN_INVALID}),
    "failed-with-wrong-format-code": (
        failed,
        {"document_format": DocumentFormat.DOCX},
    ),
    "cancelled-without-code": (lambda: job_in_state(S.CANCELLED), {"error_code": None}),
    "cancelled-with-other-code": (
        lambda: job_in_state(S.CANCELLED),
        {"error_code": E.INTERNAL_ERROR},
    ),
    "queued-with-error-code": (queued, {"error_code": E.INTERNAL_ERROR}),
    "completed-with-error-code": (completed, {"error_code": E.INTERNAL_ERROR}),
}


@pytest.mark.parametrize("name", list(INVALID))
def test_impossible_stored_job_is_rejected(name: str) -> None:
    build, changes = INVALID[name]
    job = build()
    with pytest.raises(InvariantError):
        rebuild(job, **changes)


def test_output_cannot_reuse_the_input_ref() -> None:
    job = verifying()
    with pytest.raises(InvariantError):
        rebuild(job, output_ref=job.input_ref)


def test_completed_with_failed_verification_is_rejected() -> None:
    job = completed()
    with pytest.raises(InvariantError):
        rebuild(job, verification=_failed_verification(job))


def test_findings_review_with_failed_verification_is_rejected() -> None:
    job = findings_review()
    with pytest.raises(InvariantError):
        rebuild(job, verification=_failed_verification(job))


def test_completed_with_review_verification_is_rejected() -> None:
    job = completed()
    with pytest.raises(InvariantError):
        rebuild(job, verification=verification_for(job, VerificationOutcome.REVIEW_REQUIRED))


def test_completed_state_cannot_be_forced_onto_an_unverified_job() -> None:
    job = verifying()
    with pytest.raises(InvariantError):
        rebuild(job, state=S.COMPLETED)


@pytest.mark.parametrize("state", list(DocumentState))
def test_valid_stored_job_round_trips(state: DocumentState) -> None:
    job = job_in_state(state)
    assert rebuild(job) == job


def test_every_documented_intermediate_job_round_trips() -> None:
    jobs = [
        findings_review(),
        verifier_review(),
        validation_review(DocumentFormat.DOCX),
        verifying(DocumentFormat.DOCX, frozenset({R.MAP_AMBIGUOUS})),
    ]
    for job in jobs:
        assert rebuild(job) == job


def test_upload_time_must_be_within_the_job_lifetime() -> None:
    job = uploaded()
    with pytest.raises(InvariantError):
        rebuild(job, uploaded_at=job.created_at - timedelta(seconds=1))
    assert rebuild(job, uploaded_at=job.created_at).uploaded_at == job.created_at
