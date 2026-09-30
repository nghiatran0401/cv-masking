"""Map domain and application failures to closed error-code HTTP responses."""

import logging

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict
from starlette.exceptions import HTTPException

from cv_masking.application.uploads import UploadError
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.ports.metadata import ConcurrentUpdateError, RecordNotFoundError
from cv_masking.ports.storage import StorageError

_UPLOAD_BAD_REQUEST = frozenset(
    {
        ErrorCode.UPLOAD_UNSUPPORTED_TYPE,
        ErrorCode.UPLOAD_SPOOFED_TYPE,
        ErrorCode.DOCX_MACRO_OR_TEMPLATE,
        ErrorCode.UPLOAD_MALFORMED_REQUEST,
        ErrorCode.UPLOAD_SOURCE_UNAVAILABLE,
    }
)
_UPLOAD_CONFLICT = frozenset({ErrorCode.UPLOAD_DUPLICATE, ErrorCode.UPLOAD_BATCH_CLOSED})
_UPLOAD_TOO_LARGE = frozenset(
    {
        ErrorCode.UPLOAD_FILE_TOO_LARGE,
        ErrorCode.UPLOAD_BATCH_FILE_LIMIT,
        ErrorCode.UPLOAD_BATCH_SIZE_LIMIT,
    }
)


class ErrorBody(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: ErrorCode
    batch_id: str | None = None
    document_id: str | None = None
    limit: int | None = None


def error_response(
    code: ErrorCode,
    status: int,
    *,
    batch_id: str | None = None,
    document_id: str | None = None,
    limit: int | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status,
        content=ErrorBody(
            code=code, batch_id=batch_id, document_id=document_id, limit=limit
        ).model_dump(exclude_none=True),
    )


class ApiError(Exception):
    def __init__(
        self,
        code: ErrorCode,
        status: int,
        *,
        batch_id: str | None = None,
        document_id: str | None = None,
        limit: int | None = None,
    ) -> None:
        super().__init__(code.value)
        self.code = code
        self.status = status
        self.batch_id = batch_id
        self.document_id = document_id
        self.limit = limit


def status_for(code: ErrorCode) -> int:
    if code is ErrorCode.UPLOAD_TIMEOUT:
        return 408
    if code is ErrorCode.SECURITY_RATE_LIMITED:
        return 429
    if code in {
        ErrorCode.SECURITY_HOST_REJECTED,
        ErrorCode.SECURITY_ORIGIN_REJECTED,
        ErrorCode.SECURITY_TOKEN_INVALID,
    }:
        return 403
    if code in _UPLOAD_CONFLICT:
        return 409
    if code in _UPLOAD_TOO_LARGE:
        return 413
    if code in _UPLOAD_BAD_REQUEST:
        return 400
    if code in {
        ErrorCode.STORAGE_WRITE_FAILED,
        ErrorCode.STORAGE_PATH_REJECTED,
        ErrorCode.STORAGE_INTEGRITY_FAILED,
        ErrorCode.INTERNAL_ERROR,
    }:
        return 500
    return 400


async def validation_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RequestValidationError):
        raise error
    return error_response(ErrorCode.UPLOAD_MALFORMED_REQUEST, 400)


async def api_error_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ApiError):
        raise error
    return error_response(
        error.code,
        error.status,
        batch_id=error.batch_id,
        document_id=error.document_id,
        limit=error.limit,
    )


async def not_found_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, RecordNotFoundError):
        raise error
    return error_response(ErrorCode.INTERNAL_ERROR, 404)


async def conflict_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, ConcurrentUpdateError):
        raise error
    return error_response(ErrorCode.INTERNAL_ERROR, 409)


async def transition_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, InvalidTransitionError):
        raise error
    return error_response(ErrorCode.INTERNAL_ERROR, 409)


async def storage_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, StorageError):
        raise error
    return error_response(error.code, 500)


async def upload_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, UploadError):
        raise error
    return error_response(
        error.code,
        status_for(error.code),
        batch_id=error.batch_id,
        document_id=error.document_id,
        limit=error.limit,
    )


async def unexpected_handler(_request: Request, error: Exception) -> JSONResponse:
    logging.getLogger("cv_masking.api").error("unhandled error type=%s", type(error).__name__)
    return error_response(ErrorCode.INTERNAL_ERROR, 500)


async def http_exception_handler(_request: Request, error: Exception) -> JSONResponse:
    if not isinstance(error, HTTPException):
        raise error
    status = error.status_code if error.status_code >= 400 else 500
    return error_response(ErrorCode.INTERNAL_ERROR, status)
