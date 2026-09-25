"""Metadata port: batches and document jobs, persisted as safe fields only.

A transaction is all-or-nothing. Updates are optimistic: they name the version
the caller read, and fail with ConcurrentUpdateError if the record changed since.
Failures raise StorageError with a safe code; nothing about the stored values
appears in any exception.
"""

from contextlib import AbstractContextManager
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from cv_masking.domain.batch import Batch
from cv_masking.domain.document_job import DocumentJob
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import BatchId, DocumentId, ObjectRef


class RecordKind(StrEnum):
    BATCH = "batch"
    DOCUMENT = "document"


class RecordNotFoundError(Exception):
    """The batch or document does not exist (or was purged)."""

    def __init__(self, kind: RecordKind) -> None:
        super().__init__(f"{kind} not found")
        self.kind = kind


class ConcurrentUpdateError(Exception):
    """The record changed after it was read; reload it and decide again."""

    def __init__(self, kind: RecordKind) -> None:
        super().__init__(f"{kind} was changed concurrently")
        self.kind = kind


@dataclass(frozen=True, slots=True)
class ObjectUse:
    """How a stored object is referenced by a document."""

    ref: ObjectRef
    document_format: DocumentFormat
    needed: bool
    """False once the document no longer needs the file (e.g. an input after a terminal state)."""


class MetadataReader(Protocol):
    def get_batch(self, batch_id: BatchId) -> Batch: ...

    def list_batches(self) -> tuple[Batch, ...]: ...

    def get_document(self, document_id: DocumentId) -> DocumentJob: ...

    def list_documents(self, batch_id: BatchId) -> tuple[DocumentJob, ...]: ...

    def input_uses(self) -> tuple[ObjectUse, ...]: ...

    def output_uses(self) -> tuple[ObjectUse, ...]: ...


class MetadataTransaction(MetadataReader, Protocol):
    def add_batch(self, batch: Batch) -> None: ...

    def update_batch(self, batch: Batch, *, expected_version: int) -> None: ...

    def delete_batch(self, batch_id: BatchId) -> None:
        """Delete the batch and every document row that belongs to it."""
        ...

    def add_document(self, job: DocumentJob) -> None: ...

    def update_document(self, job: DocumentJob, *, expected_version: int) -> None: ...

    def delete_document(self, document_id: DocumentId) -> None: ...


class MetadataStore(Protocol):
    def read(self) -> AbstractContextManager[MetadataReader]:
        """A consistent read-only snapshot."""
        ...

    def transaction(self) -> AbstractContextManager[MetadataTransaction]:
        """Commit when the block exits normally; roll back everything otherwise."""
        ...

    def compact(self) -> None:
        """Flush deleted data out of any journal so it does not linger on disk."""
        ...
