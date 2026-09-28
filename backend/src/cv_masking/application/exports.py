"""Masked-file downloads and the metadata-only ZIP report (D-38).

Download names are ``redacted-<document-uuid>.<ext>``. Original file names
never leave the browser. The ZIP holds only completed outputs plus one CSV of
IDs, states, codes, and counts — never values, paths, or work files.
"""

import csv
import io
import logging
import zipfile
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from typing import Final

from cv_masking.application.jobs import JobService
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory
from cv_masking.domain.ids import BatchId, DocumentId
from cv_masking.domain.limits import READ_CHUNK_BYTES
from cv_masking.domain.policy import EntityType
from cv_masking.ports.metadata import RecordKind, RecordNotFoundError
from cv_masking.ports.storage import OutputStore, WorkArea

logger = logging.getLogger("cv_masking.exports")

REPORT_NAME: Final = "report.csv"
_ZIP_EPOCH: Final = (1980, 1, 1, 0, 0, 0)
_ZIPPED: Final = frozenset({DocumentState.COMPLETED})


def download_filename(document_id: DocumentId, document_format: DocumentFormat) -> str:
    return f"redacted-{document_id.value}.{document_format.value}"


def zip_filename(batch_id: BatchId) -> str:
    return f"masked-{batch_id.value}.zip"


class ExportService:
    __slots__ = ("_jobs", "_outputs", "_work")

    def __init__(self, jobs: JobService, outputs: OutputStore, work: WorkArea) -> None:
        self._jobs = jobs
        self._outputs = outputs
        self._work = work

    def open_download(self, batch_id: BatchId, document_id: DocumentId) -> tuple[DocumentJob, str]:
        """The job and the safe download name. Residual failures are inspect-only (D-46)."""
        job = self._require_in_batch(batch_id, document_id)
        if not job.has_downloadable_output or job.document_format is None:
            raise InvalidTransitionError("download", job.state, "document has no masked output")
        return job, download_filename(job.document_id, job.document_format)

    def iter_output(self, job: DocumentJob) -> Iterator[bytes]:
        if job.output_ref is None or job.document_format is None:
            raise InvalidTransitionError("download", job.state, "document has no masked output")
        with self._outputs.open(job.output_ref, job.document_format) as handle:
            while chunk := handle.read(READ_CHUNK_BYTES):
                yield chunk

    @contextmanager
    def zip_path(self, batch_id: BatchId) -> Iterator[Path]:
        """A temporary ZIP of completed outputs plus the CSV. Removed when the block exits."""
        self._jobs.get_batch(batch_id)
        with self._work.attempt() as directory:
            path = directory / "export.zip"
            self._write_zip(batch_id, path)
            logger.info("batch %s export written", batch_id)
            yield path

    def report_csv(self, batch_id: BatchId) -> str:
        documents = self._jobs.list_documents(batch_id)
        buffer = io.StringIO()
        columns = (
            "document_id",
            "status",
            "error_code",
            *(f"count_{entity.value}" for entity in EntityType),
            *(f"hidden_{category.value}" for category in HiddenContentCategory),
        )
        writer = csv.DictWriter(buffer, fieldnames=columns, lineterminator="\n")
        writer.writeheader()
        for job in documents:
            counts = dict(job.finding_counts.items) if job.finding_counts is not None else {}
            hidden = job.hidden_removed.as_dict()
            writer.writerow(
                {
                    "document_id": str(job.document_id),
                    "status": job.state.value,
                    "error_code": "" if job.error_code is None else job.error_code.value,
                    **{f"count_{entity.value}": counts.get(entity, 0) for entity in EntityType},
                    **{
                        f"hidden_{category.value}": hidden.get(category, 0)
                        for category in HiddenContentCategory
                    },
                }
            )
        return buffer.getvalue()

    def _write_zip(self, batch_id: BatchId, path: Path) -> None:
        documents = self._jobs.list_documents(batch_id)
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            self._add_text(archive, REPORT_NAME, self.report_csv(batch_id))
            for job in documents:
                if (
                    job.state not in _ZIPPED
                    or job.output_ref is None
                    or job.document_format is None
                ):
                    continue
                name = download_filename(job.document_id, job.document_format)
                info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
                info.compress_type = zipfile.ZIP_DEFLATED
                with (
                    archive.open(info, "w") as dest,
                    self._outputs.open(job.output_ref, job.document_format) as source,
                ):
                    while chunk := source.read(READ_CHUNK_BYTES):
                        dest.write(chunk)

    def _add_text(self, archive: zipfile.ZipFile, name: str, text: str) -> None:
        info = zipfile.ZipInfo(name, date_time=_ZIP_EPOCH)
        info.compress_type = zipfile.ZIP_DEFLATED
        archive.writestr(info, text.encode("utf-8"))

    def _require_in_batch(self, batch_id: BatchId, document_id: DocumentId) -> DocumentJob:
        job = self._jobs.get_document(document_id)
        if job.batch_id != batch_id:
            raise RecordNotFoundError(RecordKind.DOCUMENT)
        return job
