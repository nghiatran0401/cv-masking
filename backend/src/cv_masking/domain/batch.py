from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum

from cv_masking.domain._validation import require_bool, require_int, require_utc
from cv_masking.domain.document_job import TERMINAL_STATES, DocumentState
from cv_masking.domain.errors import InvalidTransitionError, InvariantError
from cv_masking.domain.ids import BatchId
from cv_masking.domain.limits import HARD_MAX_FILES_PER_BATCH
from cv_masking.domain.policy import MaskingPolicy


class BatchState(StrEnum):
    OPEN = "open"
    RUNNING = "running"
    FINISHED = "finished"
    PURGED = "purged"


_SETTLED_DOCUMENT_STATES = TERMINAL_STATES | {DocumentState.REVIEW_REQUIRED}


@dataclass(frozen=True, slots=True)
class Batch:
    """A group of documents sharing one masking policy (salary toggle)."""

    batch_id: BatchId
    state: BatchState
    mask_salary: bool
    document_count: int
    created_at: datetime
    updated_at: datetime
    version: int

    def __post_init__(self) -> None:
        if not isinstance(self.batch_id, BatchId):
            raise InvariantError("Batch.batch_id must be a BatchId")
        if not isinstance(self.state, BatchState):
            raise InvariantError("Batch.state must be a BatchState")
        require_bool(self.mask_salary, "Batch.mask_salary")
        require_int(
            self.document_count,
            "Batch.document_count",
            minimum=0,
            maximum=HARD_MAX_FILES_PER_BATCH,
        )
        require_utc(self.created_at, "Batch.created_at")
        require_utc(self.updated_at, "Batch.updated_at")
        if self.updated_at < self.created_at:
            raise InvariantError("Batch.updated_at must not precede created_at")
        require_int(self.version, "Batch.version", minimum=0)
        if self.state in {BatchState.RUNNING, BatchState.FINISHED} and self.document_count < 1:
            raise InvariantError("a started Batch must contain at least one document")

    @classmethod
    def create(cls, batch_id: BatchId, at: datetime, *, mask_salary: bool = True) -> "Batch":
        return cls(
            batch_id=batch_id,
            state=BatchState.OPEN,
            mask_salary=mask_salary,
            document_count=0,
            created_at=at,
            updated_at=at,
            version=0,
        )

    @property
    def policy(self) -> MaskingPolicy:
        return MaskingPolicy(mask_salary=self.mask_salary)

    def add_document(self, at: datetime) -> "Batch":
        self._require_state("add_document", BatchState.OPEN)
        if self.document_count >= HARD_MAX_FILES_PER_BATCH:
            raise InvalidTransitionError("add_document", self.state, "batch file limit reached")
        return self._advance(at, document_count=self.document_count + 1)

    def remove_document(self, at: datetime) -> "Batch":
        self._require_state("remove_document", BatchState.OPEN)
        if self.document_count == 0:
            raise InvalidTransitionError("remove_document", self.state, "batch has no documents")
        return self._advance(at, document_count=self.document_count - 1)

    def set_mask_salary(self, mask_salary: bool, at: datetime) -> "Batch":
        self._require_state("set_mask_salary", BatchState.OPEN)
        return self._advance(at, mask_salary=mask_salary)

    def record_retry(self, at: datetime) -> "Batch":
        """Keep count unchanged; a finished batch returns to RUNNING so the retry can run."""
        if self.state is BatchState.PURGED:
            raise InvalidTransitionError("record_retry", self.state)
        if self.state is BatchState.FINISHED:
            return self._advance(at, state=BatchState.RUNNING)
        self._require_state("record_retry", BatchState.OPEN, BatchState.RUNNING)
        return self._advance(at)

    def start(self, at: datetime) -> "Batch":
        self._require_state("start", BatchState.OPEN)
        if self.document_count < 1:
            raise InvalidTransitionError("start", self.state, "batch has no documents")
        return self._advance(at, state=BatchState.RUNNING)

    def finish(self, document_states: Iterable[DocumentState], at: datetime) -> "Batch":
        self._require_state("finish", BatchState.RUNNING)
        states = list(document_states)
        if len(states) != self.document_count:
            raise InvalidTransitionError("finish", self.state, "document states do not match batch")
        if not all(state in _SETTLED_DOCUMENT_STATES for state in states):
            raise InvalidTransitionError("finish", self.state, "documents are still in progress")
        return self._advance(at, state=BatchState.FINISHED)

    def purge(self, at: datetime) -> "Batch":
        if self.state is BatchState.PURGED:
            raise InvalidTransitionError("purge", self.state)
        return self._advance(at, state=BatchState.PURGED)

    def _require_state(self, command: str, *allowed: BatchState) -> None:
        if self.state not in allowed:
            raise InvalidTransitionError(command, self.state)

    def _advance(self, at: datetime, **changes: object) -> "Batch":
        require_utc(at, "at")
        if at < self.updated_at:
            raise InvariantError("transition time must not be earlier than updated_at")
        return replace(self, updated_at=at, version=self.version + 1, **changes)  # type: ignore[arg-type]
