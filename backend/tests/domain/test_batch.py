from collections.abc import Callable
from dataclasses import replace
from datetime import timedelta

import pytest
from domain_builders import T0, new_batch_id

from cv_masking.domain.batch import Batch, BatchState
from cv_masking.domain.document_job import TERMINAL_STATES, DocumentState
from cv_masking.domain.errors import InvalidTransitionError, InvariantError
from cv_masking.domain.limits import HARD_MAX_FILES_PER_BATCH
from cv_masking.domain.policy import EntityType, MaskingPolicy


def _next(batch: Batch) -> timedelta:
    return batch.updated_at - T0 + timedelta(minutes=1)


def _open(documents: int = 0) -> Batch:
    batch = Batch.create(new_batch_id(), T0)
    for _ in range(documents):
        batch = batch.add_document(T0 + _next(batch))
    return batch


def _running(documents: int = 2) -> Batch:
    batch = _open(documents)
    return batch.start(T0 + _next(batch))


def test_create_defaults_to_masking_salary() -> None:
    batch = Batch.create(new_batch_id(), T0)
    assert (batch.state, batch.document_count, batch.version) == (BatchState.OPEN, 0, 0)
    assert batch.mask_salary is True
    assert batch.policy == MaskingPolicy(mask_salary=True)
    assert EntityType.SALARY in batch.policy.redacted_types


def test_salary_toggle_sets_the_batch_policy() -> None:
    batch = _open()
    toggled = batch.set_mask_salary(False, T0 + _next(batch))
    assert toggled.policy == MaskingPolicy(mask_salary=False)
    assert EntityType.SALARY not in toggled.policy.redacted_types
    assert toggled.version == batch.version + 1


def test_batch_accepts_exactly_the_hard_file_limit() -> None:
    batch = _open(HARD_MAX_FILES_PER_BATCH)
    assert batch.document_count == HARD_MAX_FILES_PER_BATCH
    with pytest.raises(InvalidTransitionError):
        batch.add_document(T0 + _next(batch))


def test_remove_document_needs_a_document() -> None:
    batch = _open(1)
    emptied = batch.remove_document(T0 + _next(batch))
    assert emptied.document_count == 0
    with pytest.raises(InvalidTransitionError):
        emptied.remove_document(T0 + _next(emptied))


def test_empty_batch_cannot_start() -> None:
    batch = _open()
    with pytest.raises(InvalidTransitionError):
        batch.start(T0 + _next(batch))


@pytest.mark.parametrize("state", [BatchState.RUNNING, BatchState.FINISHED, BatchState.PURGED])
def test_started_batch_is_locked(state: BatchState) -> None:
    batch = _running()
    if state is BatchState.FINISHED:
        batch = batch.finish([DocumentState.COMPLETED] * 2, T0 + _next(batch))
    elif state is BatchState.PURGED:
        batch = batch.purge(T0 + _next(batch))
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


def test_finish_accepts_terminal_and_review_documents() -> None:
    settled = [*sorted(TERMINAL_STATES), DocumentState.REVIEW_REQUIRED]
    batch = _running(len(settled))
    finished = batch.finish(settled, T0 + _next(batch))
    assert finished.state is BatchState.FINISHED


@pytest.mark.parametrize(
    "state",
    sorted(set(DocumentState) - TERMINAL_STATES - {DocumentState.REVIEW_REQUIRED}),
)
def test_finish_refuses_documents_in_progress(state: DocumentState) -> None:
    batch = _running(2)
    with pytest.raises(InvalidTransitionError):
        batch.finish([DocumentState.COMPLETED, state], T0 + _next(batch))


@pytest.mark.parametrize("count", [1, 3])
def test_finish_needs_every_document_state(count: int) -> None:
    batch = _running(2)
    with pytest.raises(InvalidTransitionError):
        batch.finish([DocumentState.COMPLETED] * count, T0 + _next(batch))


def test_finish_only_from_running() -> None:
    batch = _open(1)
    with pytest.raises(InvalidTransitionError):
        batch.finish([DocumentState.COMPLETED], T0 + _next(batch))


@pytest.mark.parametrize("build", [_open, _running], ids=["open", "running"])
def test_purge_is_allowed_once_from_any_state(build: Callable[[], Batch]) -> None:
    batch = build()
    purged = batch.purge(T0 + _next(batch))
    assert purged.state is BatchState.PURGED
    with pytest.raises(InvalidTransitionError):
        purged.purge(T0 + _next(purged))


def test_batch_time_cannot_go_backwards() -> None:
    batch = _open(1)
    with pytest.raises(InvariantError):
        batch.add_document(batch.updated_at - timedelta(seconds=1))


@pytest.mark.parametrize(
    "changes",
    [
        {"state": BatchState.RUNNING},
        {"document_count": HARD_MAX_FILES_PER_BATCH + 1},
        {"document_count": -1},
        {"document_count": True},
        {"mask_salary": 1},
        {"state": "open"},
        {"version": -1},
        {"updated_at": T0 - timedelta(seconds=1)},
    ],
    ids=[
        "running-empty",
        "over-limit",
        "negative-count",
        "bool-count",
        "int-toggle",
        "string-state",
        "negative-version",
        "updated-before-created",
    ],
)
def test_impossible_stored_batch_is_rejected(changes: dict[str, object]) -> None:
    batch = _open()
    with pytest.raises(InvariantError):
        replace(batch, **changes)  # type: ignore[arg-type]
