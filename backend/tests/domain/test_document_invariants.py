"""A DocumentJob rebuilt from stored fields fails closed on impossible combinations."""

from collections.abc import Callable
from datetime import datetime

import pytest
from domain_builders import (
    completed,
    created,
    failed,
    job_in_state,
    new_object_ref,
    rebuild,
    uploaded,
    verification_for,
    verifying,
)

from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.verification import VerificationOutcome

S = DocumentState
type Case = tuple[Callable[[], DocumentJob], dict[str, object]]

INVALID: dict[str, Case] = {
    "string-state": (created, {"state": "created"}),
    "updated-before-created": (
        uploaded,
        {"updated_at": datetime.fromisoformat("2025-12-31T00:00:00+00:00")},
    ),
    "completed-without-verification": (completed, {"verification": None}),
    "completed-forced-onto-unverified": (verifying, {"state": S.COMPLETED}),
    "verification-for-other-output": (completed, {"output_ref": new_object_ref()}),
    "failed-with-security-code": (failed, {"error_code": ErrorCode.SECURITY_TOKEN_INVALID}),
}


@pytest.mark.parametrize("name", list(INVALID))
def test_impossible_stored_job_is_rejected(name: str) -> None:
    build, changes = INVALID[name]
    with pytest.raises(InvariantError):
        rebuild(build(), **changes)


def test_output_cannot_reuse_the_input_ref() -> None:
    job = verifying()
    with pytest.raises(InvariantError):
        rebuild(job, output_ref=job.input_ref)


def test_completed_needs_a_passed_verification() -> None:
    job = completed()
    for outcome, codes in (
        (VerificationOutcome.FAILED, frozenset({ErrorCode.VERIFY_OUTPUT_INVALID})),
        (VerificationOutcome.REVIEW_REQUIRED, frozenset[ErrorCode]()),
    ):
        with pytest.raises(InvariantError):
            rebuild(job, verification=verification_for(job, outcome, codes))


def test_every_valid_state_round_trips() -> None:
    for state in DocumentState:
        job = job_in_state(state)
        assert rebuild(job) == job
