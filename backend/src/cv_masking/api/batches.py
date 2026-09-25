from collections.abc import Iterator
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, File, Request, UploadFile
from pydantic import BaseModel, ConfigDict, Field

from cv_masking.api.errors import ApiError
from cv_masking.api.runtime import Runtime
from cv_masking.domain.batch import Batch
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentJob
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.ids import BatchId, DocumentId
from cv_masking.domain.limits import READ_CHUNK_BYTES

router = APIRouter(prefix="/api/batches")


class CreateBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mask_salary: bool = True


class VersionedRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_version: int = Field(ge=0)


class SetSalaryRequest(VersionedRequest):
    mask_salary: bool


class BatchView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    batch_id: str
    state: str
    mask_salary: bool
    document_count: int
    version: int


class DocumentView(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    document_id: str
    batch_id: str
    state: str
    document_format: str | None
    size_bytes: int | None
    attempt: int
    error_code: str | None
    version: int


class BatchDetail(BatchView):
    documents: tuple[DocumentView, ...]


def _runtime(request: Request) -> Runtime:
    runtime = getattr(request.app.state, "runtime", None)
    if not isinstance(runtime, Runtime):
        raise ApiError(ErrorCode.INTERNAL_ERROR, 500)
    return runtime


def _batch_id(value: UUID) -> BatchId:
    try:
        return BatchId(value)
    except InvariantError:
        raise ApiError(ErrorCode.UPLOAD_MALFORMED_REQUEST, 400) from None


def _document_id(value: UUID) -> DocumentId:
    try:
        return DocumentId(value)
    except InvariantError:
        raise ApiError(ErrorCode.UPLOAD_MALFORMED_REQUEST, 400) from None


def _batch_view(batch: Batch) -> BatchView:
    return BatchView(
        batch_id=str(batch.batch_id),
        state=batch.state.value,
        mask_salary=batch.mask_salary,
        document_count=batch.document_count,
        version=batch.version,
    )


def _document_view(job: DocumentJob) -> DocumentView:
    return DocumentView(
        document_id=str(job.document_id),
        batch_id=str(job.batch_id),
        state=job.state.value,
        document_format=job.document_format.value if job.document_format is not None else None,
        size_bytes=job.size_bytes,
        attempt=job.attempt,
        error_code=job.error_code.value if job.error_code is not None else None,
        version=job.version,
    )


@router.post("", status_code=201)
def create_batch(
    body: CreateBatchRequest, runtime: Annotated[Runtime, Depends(_runtime)]
) -> BatchView:
    return _batch_view(runtime.jobs.create_batch(mask_salary=body.mask_salary))


@router.get("")
def list_batches(runtime: Annotated[Runtime, Depends(_runtime)]) -> tuple[BatchView, ...]:
    return tuple(_batch_view(batch) for batch in runtime.jobs.list_batches())


@router.get("/{batch_id}")
def get_batch(batch_id: UUID, runtime: Annotated[Runtime, Depends(_runtime)]) -> BatchDetail:
    chosen = _batch_id(batch_id)
    batch = runtime.jobs.get_batch(chosen)
    documents = runtime.jobs.list_documents(chosen)
    return BatchDetail(
        **_batch_view(batch).model_dump(), documents=tuple(map(_document_view, documents))
    )


@router.patch("/{batch_id}")
def set_mask_salary(
    batch_id: UUID, body: SetSalaryRequest, runtime: Annotated[Runtime, Depends(_runtime)]
) -> BatchView:
    return _batch_view(
        runtime.jobs.set_mask_salary(
            _batch_id(batch_id), body.mask_salary, expected_version=body.expected_version
        )
    )


@router.post("/{batch_id}/start")
def start_batch(
    batch_id: UUID, body: VersionedRequest, runtime: Annotated[Runtime, Depends(_runtime)]
) -> BatchView:
    return _batch_view(
        runtime.jobs.start_batch(_batch_id(batch_id), expected_version=body.expected_version)
    )


@router.delete("/{batch_id}", status_code=204)
def purge_batch(batch_id: UUID, runtime: Annotated[Runtime, Depends(_runtime)]) -> None:
    runtime.jobs.purge_batch(_batch_id(batch_id))


@router.post("/{batch_id}/documents", status_code=201)
def upload_document(
    batch_id: UUID,
    runtime: Annotated[Runtime, Depends(_runtime)],
    file: Annotated[UploadFile | None, File()] = None,
) -> DocumentView:
    if file is None:
        raise ApiError(ErrorCode.UPLOAD_MALFORMED_REQUEST, 400, batch_id=str(batch_id))
    job = runtime.uploads.upload(
        _batch_id(batch_id),
        _iter_file(file),
        filename=file.filename,
        content_type=file.content_type,
    )
    return _document_view(job)


@router.delete("/{batch_id}/documents/{document_id}", status_code=204)
def remove_document(
    batch_id: UUID, document_id: UUID, runtime: Annotated[Runtime, Depends(_runtime)]
) -> None:
    chosen_batch = _batch_id(batch_id)
    job = runtime.jobs.get_document(_document_id(document_id))
    if job.batch_id != chosen_batch:
        raise ApiError(ErrorCode.INTERNAL_ERROR, 404)
    runtime.jobs.remove_document(job.document_id)


def _iter_file(upload: UploadFile) -> Iterator[bytes]:
    """Yield request bytes in bounded chunks. Never reads the whole upload into memory."""
    stream = upload.file
    while True:
        chunk = stream.read(READ_CHUNK_BYTES)
        if not chunk:
            return
        yield chunk
