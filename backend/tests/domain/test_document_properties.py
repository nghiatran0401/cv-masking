"""Random command sequences never produce an invalid or unsafe job."""

from collections.abc import Callable
from functools import partial

from domain_builders import (
    BLOCKING_REASON,
    COUNTS,
    DIGEST,
    SIZE_BYTES,
    findings_review,
    job_in_state,
    later,
    new_object_ref,
    validation_review,
    verifier_review,
    verifying,
)
from hypothesis import given, settings
from hypothesis import strategies as st

from cv_masking.domain.codes import ERROR_CODE_GROUPS, CodeGroup, ErrorCode, ReviewReason
from cv_masking.domain.document_job import TERMINAL_STATES, DocumentJob, DocumentState
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.limits import MAX_PROCESSING_ATTEMPTS
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome, VerificationResult

type Op = tuple[str, object]

_VERIFY_CODES = sorted(c for c in ErrorCode if ERROR_CODE_GROUPS[c] is CodeGroup.VERIFICATION)
_reasons = st.frozensets(st.sampled_from(ReviewReason), max_size=3)
_verification = st.one_of(
    st.tuples(
        st.just(VerificationOutcome.FAILED),
        st.frozensets(st.sampled_from(_VERIFY_CODES), min_size=1, max_size=3),
        st.booleans(),
    ),
    st.tuples(
        st.sampled_from([VerificationOutcome.PASSED, VerificationOutcome.REVIEW_REQUIRED]),
        st.just(frozenset[ErrorCode]()),
        st.booleans(),
    ),
)
_ops = st.one_of(
    st.tuples(st.just("mark_uploaded"), st.sampled_from(DocumentFormat)),
    st.tuples(st.just("reject_upload"), st.sampled_from(ErrorCode)),
    st.tuples(st.just("start_validation"), st.none()),
    st.tuples(st.just("validation_passed"), st.none()),
    st.tuples(st.just("validation_needs_review"), _reasons),
    st.tuples(st.just("approve_review"), st.none()),
    st.tuples(st.just("deny_review"), st.none()),
    st.tuples(st.just("start_processing"), st.booleans()),
    st.tuples(st.just("output_written"), _reasons),
    st.tuples(st.just("record_verification"), _verification),
    st.tuples(st.just("requeue_after_interruption"), st.none()),
    st.tuples(st.just("fail"), st.sampled_from(ErrorCode)),
    st.tuples(st.just("cancel"), st.none()),
)


def _apply(job: DocumentJob, op: Op) -> DocumentJob:
    name, arg = op
    at = later(job)
    if name == "mark_uploaded":
        assert isinstance(arg, DocumentFormat)
        return job.mark_uploaded(
            document_format=arg,
            input_ref=new_object_ref(),
            content_sha256=DIGEST,
            size_bytes=SIZE_BYTES,
            at=at,
        )
    if name in {"reject_upload", "fail"}:
        assert isinstance(arg, ErrorCode)
        return job.reject_upload(arg, at) if name == "reject_upload" else job.fail(arg, at)
    if name in {"validation_needs_review", "output_written"}:
        assert isinstance(arg, frozenset)
        if name == "validation_needs_review":
            return job.validation_needs_review(arg, at)
        return job.output_written(new_object_ref(), COUNTS, arg, at)
    if name == "start_processing":
        assert isinstance(arg, bool)
        return job.start_processing(MaskingPolicy(mask_salary=arg), at)
    if name == "record_verification":
        assert isinstance(arg, tuple)
        outcome, codes, same_output = arg
        ref = job.output_ref if same_output and job.output_ref else new_object_ref()
        result = VerificationResult(
            outcome=outcome,
            failure_codes=codes,
            output_ref=ref,
            verifier_id="synthetic-verifier",
            verifier_version="1.0.0",
            verified_at=at,
        )
        return job.record_verification(result, at)
    command = getattr(job, name)
    result_job: DocumentJob = command(at)
    return result_job


_STARTS: list[Callable[[DocumentFormat], DocumentJob]] = [
    *(partial(job_in_state, state) for state in DocumentState),
    findings_review,
    verifier_review,
    lambda fmt: validation_review(fmt, frozenset({BLOCKING_REASON[fmt]})),
    lambda fmt: verifying(fmt, frozenset({ReviewReason.MAP_AMBIGUOUS})),
]


@settings(max_examples=600, deadline=None, derandomize=True, database=None)
@given(st.sampled_from(_STARTS), st.sampled_from(DocumentFormat), st.lists(_ops, max_size=40))
def test_random_command_sequences_preserve_invariants(
    start: Callable[[DocumentFormat], DocumentJob], fmt: DocumentFormat, ops: list[Op]
) -> None:
    job = start(fmt)
    for op in ops:
        try:
            result = _apply(job, op)
        except InvalidTransitionError:
            continue
        assert job.state not in TERMINAL_STATES, "terminal states must be absorbing"
        assert result.version == job.version + 1
        assert result.updated_at >= job.updated_at
        assert result.attempt >= job.attempt
        assert result.attempt <= MAX_PROCESSING_ATTEMPTS
        if result.state is DocumentState.COMPLETED:
            assert result.verification is not None
            assert result.verification.outcome is VerificationOutcome.PASSED
            assert result.verification.output_ref == result.output_ref
            assert result.review_reasons == frozenset()
        if result.state in {DocumentState.FAILED, DocumentState.CANCELLED}:
            assert result.error_code is not None
            assert ERROR_CODE_GROUPS[result.error_code] is not CodeGroup.SECURITY
        else:
            assert result.error_code is None
        job = result
