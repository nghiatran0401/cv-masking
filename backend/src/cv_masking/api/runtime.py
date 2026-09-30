"""Compose the local adapters for a running API process and for its worker process."""

from dataclasses import dataclass
from pathlib import Path

from cv_masking.adapters.clock import SystemClock
from cv_masking.adapters.detection import PatternDetector, PresidioDetector
from cv_masking.adapters.docx import DocxExtractor, DocxVerifier, DocxXmlRedactor
from cv_masking.adapters.http.cv_source import HttpsCvSource
from cv_masking.adapters.local_storage import (
    LocalInputStore,
    LocalOutputStore,
    LocalStorageSweeper,
    LocalWorkArea,
    StorageRoot,
    default_storage_root,
)
from cv_masking.adapters.pdf import PyMuPDFExtractor, PyMuPDFRedactor, PyMuPDFVerifier
from cv_masking.adapters.sqlite import SqliteMetadataStore
from cv_masking.adapters.worker import SubprocessProcessor
from cv_masking.application import (
    DetectionService,
    DocumentPipeline,
    ExportService,
    JobService,
    RedactionService,
    SourceImportService,
    UploadLimits,
    UploadService,
    VerificationService,
    WorkerLoop,
    WorkerService,
)
from cv_masking.config import Settings, load_settings
from cv_masking.domain.formats import DocumentFormat


@dataclass(frozen=True, slots=True)
class Runtime:
    jobs: JobService
    uploads: UploadService
    settings: Settings
    worker: WorkerLoop | None = None
    """The background queue; None in tests that drive documents by hand."""
    exports: ExportService | None = None
    """Masked-file downloads and the ZIP report."""
    source_imports: SourceImportService | None = None
    """Allowlisted CV URL downloads. None in tests that never call that route."""


def build_runtime(settings: Settings | None = None, *, root: StorageRoot | None = None) -> Runtime:
    chosen = settings if settings is not None else load_settings()
    storage = root if root is not None else StorageRoot.prepare(default_storage_root())
    metadata = SqliteMetadataStore.open(storage)
    inputs = LocalInputStore(storage)
    outputs = LocalOutputStore(storage)
    clock = SystemClock()
    work = LocalWorkArea(storage)
    jobs = JobService(metadata, inputs, outputs, clock)
    uploads = UploadService(jobs, inputs, work, clock, limits_from_settings(chosen))
    processor = SubprocessProcessor(
        build_pipeline, storage.path, timeout_seconds=chosen.job_timeout_seconds
    )
    worker = WorkerService(
        jobs, inputs, outputs, processor, clock, sweeper=LocalStorageSweeper(storage)
    )
    return Runtime(
        jobs,
        uploads,
        chosen,
        WorkerLoop(worker, processor),
        ExportService(jobs, outputs, work),
        SourceImportService(uploads, HttpsCvSource(), max_file_bytes=chosen.max_file_bytes),
    )


def build_pipeline(root_path: Path) -> DocumentPipeline:
    """Runs inside the worker process. Its stores are only read from there."""
    storage = StorageRoot.prepare(root_path)
    inputs = LocalInputStore(storage)
    verification = VerificationService(
        inputs,
        LocalOutputStore(storage),
        PatternDetector(),
        SystemClock(),
        pdf=PyMuPDFVerifier(),
        docx=DocxVerifier(),
    )
    return DocumentPipeline(
        inputs,
        {DocumentFormat.PDF: PyMuPDFExtractor(), DocumentFormat.DOCX: DocxExtractor()},
        DetectionService(PresidioDetector()),
        RedactionService(inputs, pdf=PyMuPDFRedactor(), docx=DocxXmlRedactor()),
        verification,
    )


def limits_from_settings(settings: Settings) -> UploadLimits:
    return UploadLimits(
        max_file_bytes=settings.max_file_bytes,
        max_files_per_batch=settings.max_files_per_batch,
        max_batch_bytes=settings.max_batch_bytes,
        timeout_seconds=settings.upload_timeout_seconds,
    )
