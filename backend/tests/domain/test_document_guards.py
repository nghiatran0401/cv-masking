"""Argument guards and effects of individual DocumentJob commands."""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone

import pytest
from domain_builders import (
    BLOCKING_REASON,
    COUNTS,
    DIGEST,
    HIDDEN_CONTENT_REASON,
    SIZE_BYTES,
    created,
    findings_review,
    later,
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
FORMATS = [PDF, DOCX]

_ANY_STAGE = {E.JOB_TIMEOUT, E.STORAGE_WRITE_FAILED, E.STORAGE_PATH_REJECTED}
_ANY_STAGE |= {E.STORAGE_INTEGRITY_FAILED, E.INTERNAL_ERROR}
_PROCESSING_CODES = {E.DETECT_FAILED, E.MAP_FAILED, E.REDACT_FAILED}
_PROCESSING_CODES |= {E.REDACT_SANITIZE_FAILED, E.REDACT_OUTPUT_WRITE_FAILED}
EXPECTED_FAIL_CODES = {
    (S.VALIDATING, PDF): _ANY_STAGE | {E.PDF_MALFORMED, E.PDF_NO_PAGES, E.PDF_RESOURCE_LIMIT},
    (S.VALIDATING, DOCX): _ANY_STAGE
    | {E.DOCX_MALFORMED, E.DOCX_UNSAFE_ARCHIVE, E.DOCX_RESOURCE_LIMIT},
    (S.PROCESSING, PDF): _ANY_STAGE | _PROCESSING_CODES,
    (S.PROCESSING, DOCX): _ANY_STAGE | _PROCESSING_CODES,
    (S.VERIFYING, PDF): _ANY_STAGE,
    (S.VERIFYING, DOCX): _ANY_STAGE,
}
EXPECTED_REJECT_UPLOAD_CODES = {code for code in E if code.startswith("UPLOAD_")} | {
    E.DOCX_MACRO_OR_TEMPLATE,
    E.STORAGE_WRITE_FAILED,
    E.STORAGE_PATH_REJECTED,
    E.STORAGE_INTEGRITY_FAILED,
    E.INTERNAL_ERROR,
}


def _job(state: DocumentState, fmt: DocumentFormat) -> DocumentJob:
    builders = {S.VALIDATING: validating, S.PROCESSING: processing, S.VERIFYING: verifying}
    return builders[state](fmt)


# ------------------------------------------------------------------ upload


def test_create_starts_at_version_zero() -> None:
    job = created()
    assert (job.state, job.version, job.attempt) == (S.CREATED, 0, 0)
    assert job.created_at == job.updated_at
    assert job.error_code is None


def test_mark_uploaded_records_upload_fields() -> None:
    job = created()
    at = later(job)
    result = job.mark_uploaded(
        document_format=DOCX,
        input_ref=new_object_ref(),
        content_sha256=DIGEST,
        size_bytes=SIZE_BYTES,
        at=at,
    )
    assert result.document_format is DOCX
    assert result.input_ref is not None
    assert result.content_sha256 == DIGEST
    assert result.size_bytes == SIZE_BYTES
    assert result.uploaded_at == at


@pytest.mark.parametrize("size", [0, -1, 20 * 1024 * 1024 + 1])
def test_mark_uploaded_rejects_out_of_range_sizes(size: int) -> None:
    job = created()
    with pytest.raises(InvariantError):
        job.mark_uploaded(
            document_format=PDF,
            input_ref=new_object_ref(),
            content_sha256=DIGEST,
            size_bytes=size,
            at=later(job),
        )


def test_mark_uploaded_accepts_the_hard_size_limit() -> None:
    job = created()
    result = job.mark_uploaded(
        document_format=PDF,
        input_ref=new_object_ref(),
        content_sha256=DIGEST,
        size_bytes=20 * 1024 * 1024,
        at=later(job),
    )
    assert result.size_bytes == 20 * 1024 * 1024


@pytest.mark.parametrize("code", list(E))
def test_reject_upload_accepts_only_upload_stage_codes(code: ErrorCode) -> None:
    job = created()
    if code in EXPECTED_REJECT_UPLOAD_CODES:
        result = job.reject_upload(code, later(job))
        assert (result.state, result.error_code) == (S.FAILED, code)
    else:
        with pytest.raises(InvalidTransitionError):
            job.reject_upload(code, later(job))


# ------------------------------------------------------------------ validation


@pytest.mark.parametrize("fmt", FORMATS)
def test_validation_review_accepts_blocking_and_hidden_reasons(fmt: DocumentFormat) -> None:
    job = validating(fmt)
    reasons = {BLOCKING_REASON[fmt], HIDDEN_CONTENT_REASON[fmt]}
    result = job.validation_needs_review(reasons, later(job))
    assert result.state is S.REVIEW_REQUIRED
    assert result.review_reasons == reasons


@pytest.mark.parametrize(
    "reasons",
    [
        set(),
        {R.DETECT_LOW_CONFIDENCE},
        {R.MAP_AMBIGUOUS},
        {R.VERIFY_REVIEW},
        {R.DOCX_HIDDEN_CONTENT},
        {R.PDF_HIDDEN_CONTENT, R.DOCX_ENCRYPTED},
    ],
    ids=["empty", "low-confidence", "ambiguous", "verifier", "wrong-format", "mixed-format"],
)
def test_validation_review_rejects_other_reasons(reasons: set[ReviewReason]) -> None:
    job = validating(PDF)
    with pytest.raises(InvalidTransitionError):
        job.validation_needs_review(reasons, later(job))


@pytest.mark.parametrize(("state", "fmt"), list(EXPECTED_FAIL_CODES))
def test_fail_accepts_only_codes_for_the_current_stage_and_format(
    state: DocumentState, fmt: DocumentFormat
) -> None:
    job = _job(state, fmt)
    for code in E:
        if code in EXPECTED_FAIL_CODES[(state, fmt)]:
            result = job.fail(code, later(job))
            assert (result.state, result.error_code) == (S.FAILED, code)
            assert result.review_reasons == frozenset()
        else:
            with pytest.raises(InvalidTransitionError):
                job.fail(code, later(job))


# ------------------------------------------------------------------ review


@pytest.mark.parametrize("fmt", FORMATS)
def test_approving_hidden_content_requeues_and_records_approval(fmt: DocumentFormat) -> None:
    job = validation_review(fmt)
    result = job.approve_review(later(job))
    assert result.state is S.QUEUED
    assert result.hidden_content_approved is True
    assert result.review_reasons == frozenset()


@pytest.mark.parametrize("fmt", FORMATS)
def test_blocking_review_cannot_be_approved(fmt: DocumentFormat) -> None:
    for reasons in ({BLOCKING_REASON[fmt]}, {BLOCKING_REASON[fmt], HIDDEN_CONTENT_REASON[fmt]}):
        job = validation_review(fmt, frozenset(reasons))
        with pytest.raises(InvalidTransitionError):
            job.approve_review(later(job))


@pytest.mark.parametrize("fmt", FORMATS)
def test_approving_findings_completes_an_already_verified_output(fmt: DocumentFormat) -> None:
    job = findings_review(fmt)
    assert job.verification is not None
    assert job.verification.passed
    result = job.approve_review(later(job))
    assert result.state is S.COMPLETED
    assert result.findings_review_approved is True
    assert result.review_reasons == frozenset()
    assert result.verification == job.verification


def test_verifier_review_cannot_be_approved() -> None:
    job = verifier_review()
    assert job.review_reasons == {R.VERIFY_REVIEW}
    with pytest.raises(InvalidTransitionError):
        job.approve_review(later(job))


def test_verifier_review_with_findings_reasons_cannot_be_approved() -> None:
    job = verifying(PDF, frozenset({R.MAP_AMBIGUOUS}))
    job = job.record_verification(
        verification_for(job, VerificationOutcome.REVIEW_REQUIRED), later(job)
    )
    assert job.review_reasons == {R.MAP_AMBIGUOUS, R.VERIFY_REVIEW}
    with pytest.raises(InvalidTransitionError):
        job.approve_review(later(job))


@pytest.mark.parametrize(
    "build",
    [validation_review, findings_review, verifier_review],
    ids=["validation", "findings", "verifier"],
)
def test_deny_rejects_any_review_and_clears_reasons(build: Callable[[], DocumentJob]) -> None:
    job = build()
    result = job.deny_review(later(job))
    assert result.state is S.REJECTED
    assert result.review_reasons == frozenset()
    assert result.error_code is None


# ------------------------------------------------------------------ processing


@pytest.mark.parametrize("mask_salary", [True, False])
def test_start_processing_records_policy_and_attempt(mask_salary: bool) -> None:
    job = queued()
    policy = MaskingPolicy(mask_salary=mask_salary)
    result = job.start_processing(policy, later(job))
    assert result.policy == policy
    assert result.attempt == 1


def test_start_processing_refuses_a_job_over_the_attempt_limit() -> None:
    job = queued()
    exhausted = rebuild(job, attempt=MAX_PROCESSING_ATTEMPTS)
    with pytest.raises(InvalidTransitionError):
        exhausted.start_processing(MaskingPolicy(), later(exhausted))


@pytest.mark.parametrize("reason", [R.PDF_HIDDEN_CONTENT, R.PDF_ENCRYPTED, R.VERIFY_REVIEW])
def test_output_written_accepts_only_findings_reasons(reason: ReviewReason) -> None:
    job = processing()
    with pytest.raises(InvalidTransitionError):
        job.output_written(new_object_ref(), COUNTS, {reason}, later(job))


def test_output_written_records_output_and_counts() -> None:
    job = processing()
    ref = new_object_ref()
    result = job.output_written(ref, COUNTS, {R.DETECT_LOW_CONFIDENCE}, later(job))
    assert (result.output_ref, result.finding_counts) == (ref, COUNTS)
    assert result.review_reasons == {R.DETECT_LOW_CONFIDENCE}
    assert result.verification is None


def test_requeue_discards_output_and_keeps_attempt_count() -> None:
    job = verifying(PDF, frozenset({R.MAP_AMBIGUOUS}))
    result = job.requeue_after_interruption(later(job))
    assert result.state is S.QUEUED
    assert (result.output_ref, result.finding_counts, result.policy) == (None, None, None)
    assert result.review_reasons == frozenset()
    assert result.attempt == 1


def test_requeue_fails_the_job_after_the_last_attempt() -> None:
    job = processing()
    for _ in range(MAX_PROCESSING_ATTEMPTS - 1):
        job = job.requeue_after_interruption(later(job))
        job = job.start_processing(MaskingPolicy(), later(job))
    assert job.attempt == MAX_PROCESSING_ATTEMPTS
    result = job.requeue_after_interruption(later(job))
    assert (result.state, result.error_code) == (S.FAILED, E.JOB_INTERRUPTED)


# ------------------------------------------------------------------ verification


def test_passed_verification_without_reasons_completes() -> None:
    job = verifying()
    result = job.record_verification(verification_for(job), later(job))
    assert result.state is S.COMPLETED
    assert result.findings_review_approved is False


def test_passed_verification_with_findings_reasons_requires_review() -> None:
    job = verifying(PDF, frozenset({R.DETECT_LOW_CONFIDENCE}))
    result = job.record_verification(verification_for(job), later(job))
    assert result.state is S.REVIEW_REQUIRED
    assert result.review_reasons == {R.DETECT_LOW_CONFIDENCE}


def test_verification_for_another_output_is_rejected() -> None:
    job = verifying()
    other = verification_for(created())
    with pytest.raises(InvalidTransitionError):
        job.record_verification(other, later(job))


def test_failed_verification_fails_with_the_most_serious_code() -> None:
    job = verifying(PDF, frozenset({R.DETECT_LOW_CONFIDENCE}))
    codes = frozenset({E.VERIFY_OUTPUT_INVALID, E.VERIFY_RESIDUAL_METADATA})
    result = job.record_verification(
        verification_for(job, VerificationOutcome.FAILED, codes), later(job)
    )
    assert (result.state, result.error_code) == (S.FAILED, E.VERIFY_RESIDUAL_METADATA)
    assert result.review_reasons == frozenset()


@pytest.mark.parametrize(
    ("fmt", "code"),
    [(DOCX, E.VERIFY_PAGE_COUNT_MISMATCH), (PDF, E.VERIFY_STRUCTURE_MISMATCH)],
)
def test_failed_verification_code_must_fit_the_format(fmt: DocumentFormat, code: ErrorCode) -> None:
    job = verifying(fmt)
    result = verification_for(job, VerificationOutcome.FAILED, frozenset({code}))
    with pytest.raises(InvalidTransitionError):
        job.record_verification(result, later(job))


# ------------------------------------------------------------------ cancel and time


def test_cancel_carries_job_cancelled_and_clears_reasons() -> None:
    job = verifying(PDF, frozenset({R.DETECT_LOW_CONFIDENCE}))
    result = job.cancel(later(job))
    assert (result.state, result.error_code) == (S.CANCELLED, E.JOB_CANCELLED)
    assert result.review_reasons == frozenset()


def test_transition_time_cannot_go_backwards() -> None:
    job = uploaded()
    with pytest.raises(InvariantError):
        job.start_validation(job.updated_at - timedelta(seconds=1))


def test_transition_at_the_same_instant_is_allowed() -> None:
    job = uploaded()
    assert job.start_validation(job.updated_at).updated_at == job.updated_at


@pytest.mark.parametrize(
    "at",
    [
        datetime(2026, 1, 2, 9, 0),
        datetime(2026, 1, 2, 9, 0, tzinfo=timezone(timedelta(hours=7))),
    ],
    ids=["naive", "utc+7"],
)
def test_transition_time_must_be_utc(at: datetime) -> None:
    job = uploaded()
    with pytest.raises(InvariantError):
        job.start_validation(at)


def test_transition_time_utc_equivalent_zone_is_accepted() -> None:
    job = uploaded()
    at = datetime(2026, 1, 2, 9, 0, tzinfo=UTC)
    assert job.start_validation(at).updated_at == at
