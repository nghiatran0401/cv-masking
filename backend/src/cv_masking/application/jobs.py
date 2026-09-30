"""Batch and document use cases on top of the metadata and storage ports.

Every change is one metadata transaction: the record is loaded, the domain
command is applied, and the result is saved only if nobody changed it in the
meantime. Files are deleted before the rows that reference them, so a crash
leaves at most rows pointing at missing files (the operation can be repeated)
or unreferenced files, which ``reconcile_storage`` removes.
"""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final
from uuid import UUID, uuid4

from cv_masking.domain.batch import Batch, BatchState
from cv_masking.domain.codes import INSPECTABLE_FAILURE_CODES, ErrorCode
from cv_masking.domain.document_job import TERMINAL_STATES, DocumentJob, DocumentState
from cv_masking.domain.errors import InvalidTransitionError, InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import BatchId, DocumentId, ObjectRef
from cv_masking.domain.limits import READ_CHUNK_BYTES
from cv_masking.ports.clock import Clock
from cv_masking.ports.metadata import (
    ConcurrentUpdateError,
    MetadataStore,
    MetadataTransaction,
    ObjectUse,
    RecordKind,
)
from cv_masking.ports.storage import ObjectStore, StorageError, StoredObject

logger = logging.getLogger("cv_masking.jobs")

ORPHAN_GRACE: Final = timedelta(hours=1)
"""A stored file with no metadata row is kept this long: its upload may still be recording."""

type Transition = Callable[[DocumentJob, datetime], DocumentJob]


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    removed_inputs: int = 0
    removed_outputs: int = 0
    failed: int = 0


@dataclass(frozen=True, slots=True)
class _File:
    store: ObjectStore
    ref: ObjectRef
    document_format: DocumentFormat


class JobService:
    __slots__ = ("_clock", "_inputs", "_metadata", "_new_uuid", "_outputs")

    def __init__(
        self,
        metadata: MetadataStore,
        inputs: ObjectStore,
        outputs: ObjectStore,
        clock: Clock,
        new_uuid: Callable[[], UUID] = uuid4,
    ) -> None:
        self._metadata = metadata
        self._inputs = inputs
        self._outputs = outputs
        self._clock = clock
        self._new_uuid = new_uuid

    # ------------------------------------------------------------------ queries

    def get_batch(self, batch_id: BatchId) -> Batch:
        with self._metadata.read() as reader:
            return reader.get_batch(batch_id)

    def list_batches(self) -> tuple[Batch, ...]:
        with self._metadata.read() as reader:
            return reader.list_batches()

    def get_document(self, document_id: DocumentId) -> DocumentJob:
        with self._metadata.read() as reader:
            return reader.get_document(document_id)

    def list_documents(self, batch_id: BatchId) -> tuple[DocumentJob, ...]:
        with self._metadata.read() as reader:
            reader.get_batch(batch_id)
            return reader.list_documents(batch_id)

    # ------------------------------------------------------------------ batches

    def create_batch(self, *, mask_salary: bool = True) -> Batch:
        batch = Batch.create(BatchId(self._new_uuid()), self._now(), mask_salary=mask_salary)
        with self._metadata.transaction() as tx:
            tx.add_batch(batch)
        logger.info("batch %s created", batch.batch_id)
        return batch

    def set_mask_salary(
        self, batch_id: BatchId, mask_salary: bool, *, expected_version: int
    ) -> Batch:
        return self._change_batch(
            batch_id, lambda b, at: b.set_mask_salary(mask_salary, at), expected_version
        )

    def start_batch(self, batch_id: BatchId, *, expected_version: int) -> Batch:
        with self._metadata.transaction() as tx:
            batch = self._checked_batch(tx, batch_id, expected_version)
            started = batch.start(self._now(batch.updated_at))
            tx.update_batch(started, expected_version=batch.version)
            self._settle_batch(tx, batch_id)
        logger.info("batch %s started", batch_id)
        return started

    def purge_batch(self, batch_id: BatchId) -> None:
        """Delete the batch's files, then every row about it. Safe to repeat after a crash."""
        with self._metadata.read() as reader:
            reader.get_batch(batch_id)
            documents = reader.list_documents(batch_id)
        deleted = self._delete_files(self._files_of(documents))
        with self._metadata.transaction() as tx:
            remaining = tx.list_documents(batch_id)
            tx.delete_batch(batch_id)
        self._delete_files_quietly([f for f in self._files_of(remaining) if f.ref not in deleted])
        self._metadata.compact()
        logger.info("batch %s purged documents=%d", batch_id, len(remaining))

    # ------------------------------------------------------------------ documents

    def add_document(self, batch_id: BatchId) -> DocumentJob:
        with self._metadata.transaction() as tx:
            batch = tx.get_batch(batch_id)
            at = self._now(batch.updated_at)
            grown = batch.add_document(at)
            job = DocumentJob.create(DocumentId(self._new_uuid()), batch_id, at)
            tx.update_batch(grown, expected_version=batch.version)
            tx.add_document(job)
        logger.info("document %s added to batch %s", job.document_id, batch_id)
        return job

    def replace_failed_with_upload(
        self, failed_id: DocumentId, stored: StoredObject
    ) -> DocumentJob:
        """Swap a FAILED row for a fresh upload (new ids) and reopen a finished batch."""
        if not isinstance(stored, StoredObject):
            raise InvariantError("replace_failed_with_upload needs a StoredObject")
        with self._metadata.read() as reader:
            old = reader.get_document(failed_id)
            if old.state is not DocumentState.FAILED:
                raise InvalidTransitionError("replace_failed", old.state)
        deleted = self._delete_files(self._files_of((old,)))
        with self._metadata.transaction() as tx:
            current = tx.get_document(failed_id)
            if current.state is not DocumentState.FAILED:
                raise InvalidTransitionError("replace_failed", current.state)
            batch = tx.get_batch(current.batch_id)
            retried = batch.record_retry(self._now(batch.updated_at))
            at = retried.updated_at
            job = DocumentJob.create(DocumentId(self._new_uuid()), current.batch_id, at)
            job = job.mark_uploaded(
                document_format=stored.document_format,
                input_ref=stored.ref,
                content_sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                at=at,
            )
            tx.delete_document(failed_id)
            tx.add_document(job)
            tx.update_batch(retried, expected_version=batch.version)
        self._delete_files_quietly([f for f in self._files_of((current,)) if f.ref not in deleted])
        self._metadata.compact()
        logger.info(
            "document %s replaced failed %s in batch %s",
            job.document_id,
            failed_id,
            job.batch_id,
        )
        return job

    def remove_document(self, document_id: DocumentId) -> None:
        """Remove a document from an OPEN batch, deleting its files first."""
        with self._metadata.read() as reader:
            job = reader.get_document(document_id)
            batch = reader.get_batch(job.batch_id)
            batch.remove_document(self._now(batch.updated_at))
        deleted = self._delete_files(self._files_of((job,)))
        with self._metadata.transaction() as tx:
            current = tx.get_document(document_id)
            batch = tx.get_batch(current.batch_id)
            shrunk = batch.remove_document(self._now(batch.updated_at))
            tx.delete_document(document_id)
            tx.update_batch(shrunk, expected_version=batch.version)
        self._delete_files_quietly([f for f in self._files_of((current,)) if f.ref not in deleted])
        self._metadata.compact()
        logger.info("document %s removed", document_id)

    def record_upload(self, document_id: DocumentId, stored: StoredObject) -> DocumentJob:
        if not isinstance(stored, StoredObject):
            raise InvariantError("record_upload needs a StoredObject")
        return self._change_document(
            document_id,
            lambda job, at: job.mark_uploaded(
                document_format=stored.document_format,
                input_ref=stored.ref,
                content_sha256=stored.sha256,
                size_bytes=stored.size_bytes,
                at=at,
            ),
        )

    def reject_upload(self, document_id: DocumentId, code: ErrorCode) -> DocumentJob:
        return self._change_document(document_id, lambda job, at: job.reject_upload(code, at))

    def cancel_document(
        self, document_id: DocumentId, *, expected_version: int | None = None
    ) -> DocumentJob:
        return self._change_document(document_id, lambda job, at: job.cancel(at), expected_version)

    def approve_review(self, document_id: DocumentId, *, expected_version: int) -> DocumentJob:
        return self._change_document(
            document_id, lambda job, at: job.approve_review(at), expected_version
        )

    def deny_review(self, document_id: DocumentId, *, expected_version: int) -> DocumentJob:
        return self._change_document(
            document_id, lambda job, at: job.deny_review(at), expected_version
        )

    def apply(
        self,
        document_id: DocumentId,
        transition: Transition,
        *,
        expected_version: int | None = None,
    ) -> DocumentJob:
        """Apply any domain transition (used by the processing stages)."""
        return self._change_document(document_id, transition, expected_version)

    # ------------------------------------------------------------------ storage hygiene

    def reconcile_storage(self) -> ReconcileReport:
        """Delete stored files that no document needs any more, and old unreferenced files."""
        with self._metadata.read() as reader:
            inputs = reader.input_uses()
            outputs = reader.output_uses()
        now = self._now()
        removed_inputs, failed_inputs = self._reconcile(self._inputs, inputs, now)
        removed_outputs, failed_outputs = self._reconcile(self._outputs, outputs, now)
        report = ReconcileReport(removed_inputs, removed_outputs, failed_inputs + failed_outputs)
        logger.info(
            "storage reconciled inputs=%d outputs=%d failed=%d",
            report.removed_inputs,
            report.removed_outputs,
            report.failed,
        )
        return report

    def _reconcile(
        self, store: ObjectStore, uses: tuple[ObjectUse, ...], now: datetime
    ) -> tuple[int, int]:
        by_ref = {(use.ref, use.document_format): use for use in uses}
        removed = failed = 0
        for listing in store.list_objects():
            use = by_ref.get((listing.ref, listing.document_format))
            if use is None:
                if now - listing.modified_at < ORPHAN_GRACE:
                    continue
            elif use.needed:
                continue
            try:
                store.delete(listing.ref, listing.document_format)
            except StorageError as error:
                failed += 1
                logger.warning("storage reconcile could not delete an object code=%s", error.code)
            else:
                removed += 1
        return removed, failed

    # ------------------------------------------------------------------ helpers

    def _now(self, *not_before: datetime) -> datetime:
        """The clock's time, never earlier than the records being changed."""
        now = self._clock.now()
        if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
            raise InvariantError("the clock must return a UTC datetime")
        return max((now, *not_before))

    def _checked_batch(
        self, tx: MetadataTransaction, batch_id: BatchId, expected_version: int | None
    ) -> Batch:
        batch = tx.get_batch(batch_id)
        if expected_version is not None and batch.version != expected_version:
            raise ConcurrentUpdateError(RecordKind.BATCH)
        return batch

    def _change_batch(
        self,
        batch_id: BatchId,
        change: Callable[[Batch, datetime], Batch],
        expected_version: int | None,
    ) -> Batch:
        with self._metadata.transaction() as tx:
            batch = self._checked_batch(tx, batch_id, expected_version)
            changed = change(batch, self._now(batch.updated_at))
            tx.update_batch(changed, expected_version=batch.version)
        return changed

    def _change_document(
        self,
        document_id: DocumentId,
        transition: Transition,
        expected_version: int | None = None,
    ) -> DocumentJob:
        with self._metadata.transaction() as tx:
            job = tx.get_document(document_id)
            if expected_version is not None and job.version != expected_version:
                raise ConcurrentUpdateError(RecordKind.DOCUMENT)
            changed = transition(job, self._now(job.updated_at))
            if not isinstance(changed, DocumentJob) or (
                changed.document_id,
                changed.batch_id,
            ) != (job.document_id, job.batch_id):
                raise InvariantError("a transition must return the same document")
            tx.update_document(changed, expected_version=job.version)
            self._settle_batch(tx, job.batch_id)
        logger.info(
            "document %s %s -> %s version=%d",
            document_id,
            job.state,
            changed.state,
            changed.version,
        )
        self._delete_files_quietly(self._released_files(job, changed))
        return changed

    def require_input(self, job: DocumentJob) -> None:
        """Refuse a missing or already-released input before any response bytes are sent."""
        if job.state in TERMINAL_STATES or job.input_ref is None or job.document_format is None:
            raise InvalidTransitionError("input", job.state, "document has no input")

    def iter_input(self, job: DocumentJob) -> Iterator[bytes]:
        """The stored input. Call ``require_input`` first so a refusal is not mid-stream."""
        if job.input_ref is None or job.document_format is None:
            raise InvariantError("input download requires a stored input")
        with self._inputs.open(job.input_ref, job.document_format) as handle:
            while chunk := handle.read(READ_CHUNK_BYTES):
                yield chunk

    def _settle_batch(self, tx: MetadataTransaction, batch_id: BatchId) -> None:
        """Mark a RUNNING batch FINISHED once none of its documents can progress unaided."""
        batch = tx.get_batch(batch_id)
        if batch.state is not BatchState.RUNNING:
            return
        states = [job.state for job in tx.list_documents(batch_id)]
        settled = TERMINAL_STATES | {DocumentState.REVIEW_REQUIRED}
        if all(state in settled for state in states):
            finished = batch.finish(states, self._now(batch.updated_at))
            tx.update_batch(finished, expected_version=batch.version)
            logger.info("batch %s finished", batch_id)

    def _released_files(self, before: DocumentJob, after: DocumentJob) -> list[_File]:
        """Files the document stopped needing with this change."""
        released: list[_File] = []
        fmt = before.document_format
        if fmt is None:
            return released
        if before.input_ref is not None and after.state in TERMINAL_STATES:
            released.append(_File(self._inputs, before.input_ref, fmt))
        if before.output_ref is not None and (
            after.output_ref != before.output_ref or _output_discarded(after)
        ):
            released.append(_File(self._outputs, before.output_ref, fmt))
        return released

    def _files_of(self, documents: tuple[DocumentJob, ...]) -> list[_File]:
        files: list[_File] = []
        for job in documents:
            if job.document_format is None:
                continue
            if job.input_ref is not None:
                files.append(_File(self._inputs, job.input_ref, job.document_format))
            if job.output_ref is not None:
                files.append(_File(self._outputs, job.output_ref, job.document_format))
        return files

    @staticmethod
    def _delete_files(files: list[_File]) -> set[ObjectRef]:
        """Delete files, failing closed: a StorageError stops before any row is removed."""
        for file in files:
            file.store.delete(file.ref, file.document_format)
        return {file.ref for file in files}

    @staticmethod
    def _delete_files_quietly(files: list[_File]) -> None:
        """Best-effort deletion after a commit; reconcile_storage removes anything left."""
        for file in files:
            try:
                file.store.delete(file.ref, file.document_format)
            except StorageError as error:
                logger.warning("file deletion deferred to reconcile code=%s", error.code)


def _output_discarded(job: DocumentJob) -> bool:
    if job.state in {DocumentState.REJECTED, DocumentState.CANCELLED}:
        return True
    if job.state is DocumentState.FAILED:
        return job.error_code not in INSPECTABLE_FAILURE_CODES
    return False
