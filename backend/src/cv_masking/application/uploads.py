"""Receive one uploaded file into a batch, without parsing document content."""

import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from cv_masking.application.identify import IdentifiedKind, declared_disagrees, identify_file
from cv_masking.application.jobs import JobService
from cv_masking.domain.batch import BatchState
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.domain.ids import BatchId, DocumentId
from cv_masking.domain.limits import READ_CHUNK_BYTES
from cv_masking.ports.clock import Clock
from cv_masking.ports.metadata import ConcurrentUpdateError, RecordKind
from cv_masking.ports.storage import InputStore, StorageError, StoredObject, WorkArea

logger = logging.getLogger("cv_masking.uploads")

_ADD_RETRIES = 8


@dataclass(frozen=True, slots=True)
class UploadLimits:
    max_file_bytes: int
    max_files_per_batch: int
    max_batch_bytes: int
    timeout_seconds: int


class UploadError(Exception):
    """The upload was refused; ``code`` is safe to return to the client."""

    def __init__(
        self,
        code: ErrorCode,
        *,
        limit: int | None = None,
        document_id: str | None = None,
        batch_id: str | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.limit = limit
        self.document_id = document_id
        self.batch_id = batch_id


class UploadService:
    __slots__ = ("_clock", "_inputs", "_jobs", "_limits", "_work")

    def __init__(
        self,
        jobs: JobService,
        inputs: InputStore,
        work: WorkArea,
        clock: Clock,
        limits: UploadLimits,
    ) -> None:
        self._jobs = jobs
        self._inputs = inputs
        self._work = work
        self._clock = clock
        self._limits = limits

    def upload(
        self,
        batch_id: BatchId,
        chunks: Iterable[bytes],
        *,
        filename: str | None,
        content_type: str | None,
        replaces: DocumentId | None = None,
    ) -> DocumentJob:
        """Store one file. ``filename`` is used only to detect spoofing and is then discarded.

        ``replaces`` swaps a FAILED document in this batch (including after start).
        """
        batch = self._jobs.get_batch(batch_id)
        jobs = self._jobs.list_documents(batch_id)
        replacing = None
        if replaces is not None:
            replacing = next((job for job in jobs if job.document_id == replaces), None)
            if replacing is None or replacing.state is not DocumentState.FAILED:
                state = "missing" if replacing is None else replacing.state
                raise InvalidTransitionError("replace_failed", state)
        elif batch.state is not BatchState.OPEN:
            raise UploadError(ErrorCode.UPLOAD_BATCH_CLOSED, batch_id=str(batch_id))
        if replacing is None and batch.document_count >= self._limits.max_files_per_batch:
            raise UploadError(
                ErrorCode.UPLOAD_BATCH_FILE_LIMIT,
                limit=self._limits.max_files_per_batch,
                batch_id=str(batch_id),
            )
        used = sum(
            job.size_bytes or 0
            for job in jobs
            if replacing is None or job.document_id != replacing.document_id
        )
        remaining = self._limits.max_batch_bytes - used
        if remaining < 1:
            raise UploadError(
                ErrorCode.UPLOAD_BATCH_SIZE_LIMIT,
                limit=self._limits.max_batch_bytes,
                batch_id=str(batch_id),
            )
        max_bytes = min(self._limits.max_file_bytes, remaining)
        oversize_code = (
            ErrorCode.UPLOAD_FILE_TOO_LARGE
            if max_bytes == self._limits.max_file_bytes
            else ErrorCode.UPLOAD_BATCH_SIZE_LIMIT
        )
        oversize_limit = (
            self._limits.max_file_bytes
            if oversize_code is ErrorCode.UPLOAD_FILE_TOO_LARGE
            else self._limits.max_batch_bytes
        )
        deadline = self._clock.now() + timedelta(seconds=self._limits.timeout_seconds)
        try:
            stored = self._accept(
                chunks,
                filename=filename,
                content_type=content_type,
                max_bytes=max_bytes,
                oversize_code=oversize_code,
                deadline=deadline,
            )
        except UploadError as refusal:
            if replacing is not None:
                raise UploadError(
                    refusal.code,
                    limit=oversize_limit if refusal.code is oversize_code else refusal.limit,
                    document_id=str(replacing.document_id),
                    batch_id=str(batch_id),
                ) from None
            job = self._add_document(batch_id)
            failed = self._jobs.reject_upload(job.document_id, refusal.code)
            logger.info("document %s upload refused code=%s", failed.document_id, refusal.code)
            raise UploadError(
                refusal.code,
                limit=oversize_limit if refusal.code is oversize_code else refusal.limit,
                document_id=str(failed.document_id),
                batch_id=str(batch_id),
            ) from None
        except StorageError as error:
            if replacing is not None:
                raise UploadError(
                    error.code, document_id=str(replacing.document_id), batch_id=str(batch_id)
                ) from None
            job = self._add_document(batch_id)
            failed = self._jobs.reject_upload(job.document_id, error.code)
            logger.info("document %s upload refused code=%s", failed.document_id, error.code)
            raise UploadError(
                error.code, document_id=str(failed.document_id), batch_id=str(batch_id)
            ) from None
        skip = {replacing.document_id} if replacing is not None else set()
        for existing in self._jobs.list_documents(batch_id):
            if existing.document_id in skip:
                continue
            if existing.content_sha256 == stored.sha256:
                self._inputs.delete(stored.ref, stored.document_format)
                if replacing is not None:
                    raise UploadError(
                        ErrorCode.UPLOAD_DUPLICATE,
                        document_id=str(replacing.document_id),
                        batch_id=str(batch_id),
                    )
                job = self._add_document(batch_id)
                failed = self._jobs.reject_upload(job.document_id, ErrorCode.UPLOAD_DUPLICATE)
                logger.info(
                    "document %s upload refused code=%s",
                    failed.document_id,
                    ErrorCode.UPLOAD_DUPLICATE,
                )
                raise UploadError(
                    ErrorCode.UPLOAD_DUPLICATE,
                    document_id=str(failed.document_id),
                    batch_id=str(batch_id),
                )
        if replacing is not None:
            recorded = self._jobs.replace_failed_with_upload(replacing.document_id, stored)
        else:
            job = self._add_document(batch_id)
            recorded = self._jobs.record_upload(job.document_id, stored)
        logger.info(
            "document %s uploaded format=%s bytes=%d",
            recorded.document_id,
            recorded.document_format,
            recorded.size_bytes or 0,
        )
        return recorded

    def _add_document(self, batch_id: BatchId) -> DocumentJob:
        last: ConcurrentUpdateError | None = None
        for _ in range(_ADD_RETRIES):
            try:
                return self._jobs.add_document(batch_id)
            except ConcurrentUpdateError as error:
                last = error
            except InvalidTransitionError:
                current = self._jobs.get_batch(batch_id)
                if current.state is BatchState.OPEN:
                    raise UploadError(
                        ErrorCode.UPLOAD_BATCH_FILE_LIMIT,
                        limit=self._limits.max_files_per_batch,
                        batch_id=str(batch_id),
                    ) from None
                raise UploadError(ErrorCode.UPLOAD_BATCH_CLOSED, batch_id=str(batch_id)) from None
        if last is None:
            raise ConcurrentUpdateError(RecordKind.BATCH)
        raise last

    def _accept(
        self,
        chunks: Iterable[bytes],
        *,
        filename: str | None,
        content_type: str | None,
        max_bytes: int,
        oversize_code: ErrorCode,
        deadline: datetime,
    ) -> StoredObject:
        with self._work.attempt() as directory:
            path = directory / "upload.bin"
            self._write(
                path,
                chunks,
                max_bytes=max_bytes,
                oversize_code=oversize_code,
                deadline=deadline,
            )
            kind = identify_file(path)
            if kind is IdentifiedKind.MACRO_OR_TEMPLATE:
                raise UploadError(ErrorCode.DOCX_MACRO_OR_TEMPLATE)
            if kind is IdentifiedKind.UNSUPPORTED:
                raise UploadError(ErrorCode.UPLOAD_UNSUPPORTED_TYPE)
            if declared_disagrees(kind, filename=filename, content_type=content_type):
                raise UploadError(ErrorCode.UPLOAD_SPOOFED_TYPE)
            fmt = kind.document_format
            if fmt is None:
                raise UploadError(ErrorCode.UPLOAD_UNSUPPORTED_TYPE)
            return self._inputs.save_stream(fmt, _read_chunks(path), max_bytes=max_bytes)

    def _write(
        self,
        path: Path,
        chunks: Iterable[bytes],
        *,
        max_bytes: int,
        oversize_code: ErrorCode,
        deadline: datetime,
    ) -> None:
        size = 0
        with path.open("wb") as file:
            for chunk in chunks:
                if self._clock.now() >= deadline:
                    raise UploadError(ErrorCode.UPLOAD_TIMEOUT)
                if not isinstance(chunk, bytes):
                    raise UploadError(ErrorCode.UPLOAD_MALFORMED_REQUEST)
                size += len(chunk)
                if size > max_bytes:
                    raise UploadError(oversize_code)
                file.write(chunk)
        if size == 0:
            raise UploadError(ErrorCode.UPLOAD_UNSUPPORTED_TYPE)


def _read_chunks(path: Path) -> Iterable[bytes]:
    with path.open("rb") as file:
        while chunk := file.read(READ_CHUNK_BYTES):
            yield chunk
