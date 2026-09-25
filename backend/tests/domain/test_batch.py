from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest
from domain_builders import T0, new_batch_id

from cv_masking.domain.batch import Batch, BatchState
from cv_masking.domain.document_job import TERMINAL_STATES, DocumentState
from cv_masking.domain.errors import InvalidTransitionError, InvariantError
from cv_masking.domain.limits import HARD_MAX_FILES_PER_BATCH
from cv_masking.domain.policy import EntityType


def _next(batch: Batch) -> timedelta:
    return batch.updated_at - T0 + timedelta(minutes=1)


def _open(documents: int = 0) -> Batch:
    batch = Batch.create(new_batch_id(), T0)
    for _ in range(documents):
        batch = batch.add_document(T0 + _next(batch))
    return batch


def test_salary_is_masked_by_default_and_can_be_toggled() -> None:
    batch = _open()
    assert EntityType.SALARY in batch.policy.redacted_types
    toggled = batch.set_mask_salary(False, T0 + _next(batch))
    assert EntityType.SALARY not in toggled.policy.redacted_types


def test_batch_accepts_exactly_the_hard_file_limit() -> None:
    batch = _open(HARD_MAX_FILES_PER_BATCH)
    with pytest.raises(InvalidTransitionError):
        batch.add_document(T0 + _next(batch))


def test_empty_batch_cannot_start() -> None:
    batch = _open()
    with pytest.raises(InvalidTransitionError):
        batch.start(T0 + _next(batch))


def test_started_batch_is_locked() -> None:
    batch = _open(2)
    batch = batch.start(T0 + _next(batch))
    at = T0 + _next(batch)
    commands: tuple[Callable[[], Batch], ...] = (
        lambda: batch.add_document(at),
        lambda: batch.remove_document(at),
        lambda: batch.set_mask_salary(False, at),
        lambda: batch.start(at),
    )
    for command in commands:
        with pytest.raises(InvalidTransitionError):
            command()


def test_finish_needs_every_document_settled() -> None:
    settled = [*sorted(TERMINAL_STATES), DocumentState.REVIEW_REQUIRED]
    batch = _open(len(settled))
    batch = batch.start(T0 + _next(batch))
    assert batch.finish(settled, T0 + _next(batch)).state is BatchState.FINISHED
    with pytest.raises(InvalidTransitionError):
        batch.finish([*settled[:-1], DocumentState.PROCESSING], T0 + _next(batch))


@pytest.mark.parametrize(
    "changes",
    [
        {"state": BatchState.RUNNING},
        {"document_count": HARD_MAX_FILES_PER_BATCH + 1},
        {"updated_at": T0 - timedelta(seconds=1)},
    ],
    ids=["running-empty", "over-limit", "updated-before-created"],
)
def test_impossible_stored_batch_is_rejected(changes: dict[str, object]) -> None:
    with pytest.raises(InvariantError):
        replace(_open(), **changes)  # type: ignore[arg-type]
