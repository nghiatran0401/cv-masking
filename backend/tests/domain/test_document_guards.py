"""Argument guards and effects of the DocumentJob commands that carry safety rules."""

from datetime import datetime, timedelta, timezone

import pytest
from domain_builders import (
    BLOCKING_REASON,
    HIDDEN_CONTENT_REASON,
    created,
    findings_review,
    later,
    processing,
    uploaded,
    validating,
    validation_review,
    verification_for,
    verifier_review,
    verifying,
)

from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.errors import InvalidTransitionError, InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import MAX_PROCESSING_ATTEMPTS
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome

S = DocumentState
E = ErrorCode
R = ReviewReason
PDF = DocumentFormat.PDF
DOCX = DocumentFormat.DOCX


def test_reject_upload_refuses_codes_from_later_stages() -> None:
    job = created()
    assert job.reject_upload(E.UPLOAD_SPOOFED_TYPE, later(job)).state is S.FAILED
    for code in (E.PDF_MALFORMED, E.VERIFY_RESIDUAL_FINDING, E.SECURITY_TOKEN_INVALID):
        with pytest.raises(InvalidTransitionError):
            job.reject_upload(code, later(job))


def test_fail_refuses_codes_for_another_stage_or_format() -> None:
    job = validating(PDF)
    assert job.fail(E.PDF_MALFORMED, later(job)).error_code is E.PDF_MALFORMED
    for code in (E.DOCX_MALFORMED, E.REDACT_FAILED, E.JOB_CANCELLED, E.SECURITY_TOKEN_INVALID):
        with pytest.raises(InvalidTransitionError):
            job.fail(code, later(job))


def test_validation_review_refuses_findings_or_other_format_reasons() -> None:
    job = validating(PDF)
    for reasons in (set(), {R.DETECT_LOW_CONFIDENCE}, {R.DOCX_HIDDEN_CONTENT}):
        with pytest.raises(InvalidTransitionError):
            job.validation_needs_review(reasons, later(job))


@pytest.mark.parametrize("fmt", [PDF, DOCX])
def test_hidden_content_can_be_approved_but_blocking_reasons_cannot(fmt: DocumentFormat) -> None:
    job = validation_review(fmt)
    approved = job.approve_review(later(job))
    assert (approved.state, approved.hidden_content_approved) == (S.QUEUED, True)
    blocked = validation_review(fmt, frozenset({BLOCKING_REASON[fmt], HIDDEN_CONTENT_REASON[fmt]}))
    with pytest.raises(InvalidTransitionError):
        blocked.approve_review(later(blocked))


def test_approving_findings_completes_the_verified_output() -> None:
    job = findings_review()
    result = job.approve_review(later(job))
    assert (result.state, result.findings_review_approved) == (S.COMPLETED, True)
    assert result.verification == job.verification


def test_verifier_review_cannot_be_approved() -> None:
    job = verifier_review()
    with pytest.raises(InvalidTransitionError):
        job.approve_review(later(job))


def test_requeue_fails_the_job_after_the_last_attempt() -> None:
    job = processing()
    for _ in range(MAX_PROCESSING_ATTEMPTS - 1):
        job = job.requeue_after_interruption(later(job))
        job = job.start_processing(MaskingPolicy(), later(job))
    result = job.requeue_after_interruption(later(job))
    assert (result.state, result.error_code) == (S.FAILED, E.JOB_INTERRUPTED)


def test_passed_verification_with_findings_reasons_requires_review() -> None:
    job = verifying(PDF, frozenset({R.DETECT_LOW_CONFIDENCE}))
    result = job.record_verification(verification_for(job), later(job))
    assert result.state is S.REVIEW_REQUIRED


def test_verification_for_another_output_is_rejected() -> None:
    job = verifying()
    with pytest.raises(InvalidTransitionError):
        job.record_verification(verification_for(created()), later(job))


def test_failed_verification_fails_with_the_most_serious_code() -> None:
    job = verifying()
    codes = frozenset({E.VERIFY_OUTPUT_INVALID, E.VERIFY_RESIDUAL_METADATA})
    result = job.record_verification(
        verification_for(job, VerificationOutcome.FAILED, codes), later(job)
    )
    assert (result.state, result.error_code) == (S.FAILED, E.VERIFY_RESIDUAL_METADATA)


def test_transition_time_must_be_utc_and_not_go_backwards() -> None:
    job = uploaded()
    for at in (
        job.updated_at - timedelta(seconds=1),
        datetime(2026, 1, 2, 9, 0),
        datetime(2026, 1, 2, 9, 0, tzinfo=timezone(timedelta(hours=7))),
    ):
        with pytest.raises(InvariantError):
            job.start_validation(at)
