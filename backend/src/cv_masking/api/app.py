from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError

from cv_masking import __version__
from cv_masking.api.batches import router as batches_router
from cv_masking.api.errors import (
    ApiError,
    api_error_handler,
    conflict_handler,
    not_found_handler,
    storage_handler,
    transition_handler,
    upload_handler,
    validation_handler,
)
from cv_masking.api.health import router as health_router
from cv_masking.api.runtime import Runtime, build_runtime
from cv_masking.application.uploads import UploadError
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.ports.metadata import ConcurrentUpdateError, RecordNotFoundError
from cv_masking.ports.storage import StorageError


def create_app(runtime: Runtime | None = None) -> FastAPI:
    # Interactive docs are disabled: FastAPI's Swagger UI and ReDoc pages load
    # scripts and styles from a public CDN, which the no-remote-assets rule forbids.
    app = FastAPI(
        title="CV Masking",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        swagger_ui_oauth2_redirect_url=None,
    )
    app.state.runtime = runtime
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(UploadError, upload_handler)
    app.add_exception_handler(RecordNotFoundError, not_found_handler)
    app.add_exception_handler(ConcurrentUpdateError, conflict_handler)
    app.add_exception_handler(InvalidTransitionError, transition_handler)
    app.add_exception_handler(StorageError, storage_handler)
    app.include_router(health_router)
    app.include_router(batches_router)
    return app


def create_runtime_app() -> FastAPI:
    """Production factory: opens the local data/ folder. Tests must not call this."""
    return create_app(build_runtime())
