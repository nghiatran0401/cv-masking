"""Compose the local adapters for a running API process."""

from dataclasses import dataclass

from cv_masking.adapters.clock import SystemClock
from cv_masking.adapters.local_storage import (
    LocalInputStore,
    LocalOutputStore,
    LocalWorkArea,
    StorageRoot,
    default_storage_root,
)
from cv_masking.adapters.sqlite import SqliteMetadataStore
from cv_masking.application import JobService, UploadLimits, UploadService
from cv_masking.config import Settings, load_settings


@dataclass(frozen=True, slots=True)
class Runtime:
    jobs: JobService
    uploads: UploadService
    settings: Settings


def build_runtime(settings: Settings | None = None, *, root: StorageRoot | None = None) -> Runtime:
    chosen = settings if settings is not None else load_settings()
    storage = root if root is not None else StorageRoot.prepare(default_storage_root())
    metadata = SqliteMetadataStore.open(storage)
    inputs = LocalInputStore(storage)
    jobs = JobService(metadata, inputs, LocalOutputStore(storage), SystemClock())
    uploads = UploadService(
        jobs, inputs, LocalWorkArea(storage), SystemClock(), limits_from_settings(chosen)
    )
    return Runtime(jobs, uploads, chosen)


def limits_from_settings(settings: Settings) -> UploadLimits:
    return UploadLimits(
        max_file_bytes=settings.max_file_bytes,
        max_files_per_batch=settings.max_files_per_batch,
        max_batch_bytes=settings.max_batch_bytes,
        timeout_seconds=settings.upload_timeout_seconds,
    )
