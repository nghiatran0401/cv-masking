"""Every command against every state: only the documented transitions succeed."""

from collections.abc import Callable

import pytest
from domain_builders import (
    BLOCKING_REASON,
    COUNTS,
    DIGEST,
    SIZE_BYTES,
    job_in_state,
    later,
    new_object_ref,
    verification_for,
)

from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import (
    CANCELLABLE_STATES,
    INTERRUPTIBLE_STATES,
    DocumentJob,
    DocumentState,
)
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.policy import MaskingPolicy

S = DocumentState
type Command = Callable[[DocumentJob], DocumentJob]


COMMANDS: dict[str, Command] = {
    "mark_uploaded": lambda j: j.mark_uploaded(
        document_format=DocumentFormat.PDF,
        input_ref=new_object_ref(),
        content_sha256=DIGEST,
        size_bytes=SIZE_BYTES,
        at=later(j),
    ),
    "reject_upload": lambda j: j.reject_upload(ErrorCode.UPLOAD_SPOOFED_TYPE, later(j)),
    "start_validation": lambda j: j.start_validation(later(j)),
    "validation_passed": lambda j: j.validation_passed(later(j)),
    "validation_needs_review": lambda j: j.validation_needs_review(
        {BLOCKING_REASON[j.document_format or DocumentFormat.PDF]}, later(j)
    ),
    "approve_review": lambda j: j.approve_review(later(j)),
    "deny_review": lambda j: j.deny_review(later(j)),
    "start_processing": lambda j: j.start_processing(MaskingPolicy(), later(j)),
    "output_written": lambda j: j.output_written(new_object_ref(), COUNTS, (), later(j)),
    "record_verification": lambda j: j.record_verification(verification_for(j), later(j)),
    "interrupt": lambda j: j.interrupt(later(j)),
    "fail": lambda j: j.fail(ErrorCode.INTERNAL_ERROR, later(j)),
    "cancel": lambda j: j.cancel(later(j)),
}

ALLOWED: dict[tuple[DocumentState, str], DocumentState] = {
    (S.CREATED, "mark_uploaded"): S.UPLOADED,
    (S.CREATED, "reject_upload"): S.FAILED,
    (S.UPLOADED, "start_validation"): S.VALIDATING,
    (S.VALIDATING, "validation_passed"): S.QUEUED,
    (S.VALIDATING, "validation_needs_review"): S.REVIEW_REQUIRED,
    (S.VALIDATING, "fail"): S.FAILED,
    (S.QUEUED, "start_processing"): S.PROCESSING,
    (S.PROCESSING, "output_written"): S.VERIFYING,
    (S.PROCESSING, "fail"): S.FAILED,
    (S.VERIFYING, "record_verification"): S.COMPLETED,
    (S.VERIFYING, "fail"): S.FAILED,
    (S.REVIEW_REQUIRED, "approve_review"): S.COMPLETED,
    (S.REVIEW_REQUIRED, "deny_review"): S.REJECTED,
    **{(state, "cancel"): S.CANCELLED for state in CANCELLABLE_STATES},
    **{(state, "interrupt"): S.FAILED for state in INTERRUPTIBLE_STATES},
}


def test_only_waiting_documents_can_be_cancelled() -> None:
    assert {S.CREATED, S.UPLOADED, S.QUEUED} == CANCELLABLE_STATES


def test_matrix_covers_every_command_method() -> None:
    public = {
        name
        for name in dir(DocumentJob)
        if not name.startswith("_") and callable(getattr(DocumentJob, name))
    }
    assert public - {"create"} == set(COMMANDS)


@pytest.mark.parametrize("state", list(DocumentState))
def test_only_documented_transitions_succeed(state: DocumentState) -> None:
    job = job_in_state(state)
    for name, command in COMMANDS.items():
        expected = ALLOWED.get((state, name))
        if expected is None:
            with pytest.raises(InvalidTransitionError):
                command(job)
            continue
        result = command(job)
        assert result.state is expected, name
        assert result.version == job.version + 1
        assert (result.document_id, result.batch_id) == (job.document_id, job.batch_id)
