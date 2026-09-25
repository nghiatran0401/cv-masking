"""Every command against every state: only the documented transitions succeed."""

from collections.abc import Callable

import pytest
from domain_builders import (
    COUNTS,
    DIGEST,
    HIDDEN_CONTENT_REASON,
    SIZE_BYTES,
    job_in_state,
    later,
    new_object_ref,
    verification_for,
)

from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import (
    CANCELLABLE_STATES,
    TERMINAL_STATES,
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
        {HIDDEN_CONTENT_REASON[j.document_format or DocumentFormat.PDF]}, later(j)
    ),
    "approve_review": lambda j: j.approve_review(later(j)),
    "deny_review": lambda j: j.deny_review(later(j)),
    "start_processing": lambda j: j.start_processing(MaskingPolicy(), later(j)),
    "output_written": lambda j: j.output_written(new_object_ref(), COUNTS, (), later(j)),
    "record_verification": lambda j: j.record_verification(verification_for(j), later(j)),
    "requeue_after_interruption": lambda j: j.requeue_after_interruption(later(j)),
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
    (S.PROCESSING, "requeue_after_interruption"): S.QUEUED,
    (S.PROCESSING, "fail"): S.FAILED,
    (S.VERIFYING, "record_verification"): S.COMPLETED,
    (S.VERIFYING, "requeue_after_interruption"): S.QUEUED,
    (S.VERIFYING, "fail"): S.FAILED,
    (S.REVIEW_REQUIRED, "approve_review"): S.QUEUED,
    (S.REVIEW_REQUIRED, "deny_review"): S.REJECTED,
    **{(state, "cancel"): S.CANCELLED for state in CANCELLABLE_STATES},
}

MATRIX = [(state, name) for state in DocumentState for name in COMMANDS]


def test_matrix_covers_every_command_method() -> None:
    public = {
        name
        for name in dir(DocumentJob)
        if not name.startswith("_") and callable(getattr(DocumentJob, name))
    }
    assert public - {"create"} == set(COMMANDS)


def test_cancellable_states_are_exactly_the_non_terminal_non_review_states() -> None:
    assert set(DocumentState) - TERMINAL_STATES - {S.REVIEW_REQUIRED} == CANCELLABLE_STATES


@pytest.mark.parametrize(("state", "command"), MATRIX, ids=[f"{s}-{c}" for s, c in MATRIX])
def test_transition_matrix(state: DocumentState, command: str) -> None:
    job = job_in_state(state)
    assert job.state is state
    expected = ALLOWED.get((state, command))
    if expected is None:
        with pytest.raises(InvalidTransitionError):
            COMMANDS[command](job)
        return
    result = COMMANDS[command](job)
    assert result.state is expected
    assert result.version == job.version + 1
    assert result.updated_at > job.updated_at
    assert result.document_id == job.document_id
    assert result.batch_id == job.batch_id
    assert result.created_at == job.created_at


@pytest.mark.parametrize("state", sorted(TERMINAL_STATES))
def test_terminal_states_reject_every_command(state: DocumentState) -> None:
    job = job_in_state(state)
    for command in COMMANDS.values():
        with pytest.raises(InvalidTransitionError):
            command(job)


def test_rejected_transition_leaves_job_unchanged() -> None:
    job = job_in_state(S.QUEUED)
    snapshot = job
    with pytest.raises(InvalidTransitionError):
        job.deny_review(later(job))
    assert job == snapshot
    assert job.state is S.QUEUED
