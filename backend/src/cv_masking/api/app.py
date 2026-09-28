import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from starlette.middleware import Middleware

from cv_masking import __version__
from cv_masking.adapters.local_storage import LOGS_DIR, default_storage_root
from cv_masking.api.batches import router as batches_router
from cv_masking.api.errors import (
    ApiError,
    api_error_handler,
    conflict_handler,
    http_exception_handler,
    not_found_handler,
    storage_handler,
    transition_handler,
    unexpected_handler,
    upload_handler,
    validation_handler,
)
from cv_masking.api.health import router as health_router
from cv_masking.api.runtime import Runtime, build_runtime
from cv_masking.api.security import RateLimiter, SecurityGate, SessionState
from cv_masking.api.session import router as session_router
from cv_masking.application.uploads import UploadError
from cv_masking.config import Settings
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.logging_setup import configure_file_logging, install_metadata_filter
from cv_masking.ports.metadata import ConcurrentUpdateError, RecordNotFoundError
from cv_masking.ports.storage import StorageError


def create_app(runtime: Runtime | None = None) -> FastAPI:
    install_metadata_filter()
    session = SessionState.new()
    settings = runtime.settings if runtime is not None else Settings()
    limiter = RateLimiter()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        worker = runtime.worker if runtime is not None else None
        if worker is not None:
            await asyncio.to_thread(worker.start)
        try:
            yield
        finally:
            if worker is not None:
                await asyncio.to_thread(worker.stop)

    # Interactive docs are disabled: FastAPI's Swagger UI and ReDoc pages load
    # scripts and styles from a public CDN, which the no-remote-assets rule forbids.
    app = FastAPI(
        title="CV Masking",
        version=__version__,
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        swagger_ui_oauth2_redirect_url=None,
        lifespan=lifespan,
        middleware=[
            Middleware(SecurityGate, session=session, settings=settings, limiter=limiter),
        ],
    )
    app.state.runtime = runtime
    app.state.session = session
    app.add_exception_handler(RequestValidationError, validation_handler)
    app.add_exception_handler(ApiError, api_error_handler)
    app.add_exception_handler(UploadError, upload_handler)
    app.add_exception_handler(RecordNotFoundError, not_found_handler)
    app.add_exception_handler(ConcurrentUpdateError, conflict_handler)
    app.add_exception_handler(InvalidTransitionError, transition_handler)
    app.add_exception_handler(StorageError, storage_handler)
    app.add_exception_handler(HTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unexpected_handler)
    app.include_router(health_router)
    app.include_router(session_router)
    app.include_router(batches_router)
    return app


def create_runtime_app() -> FastAPI:
    """Production factory: opens the local data/ folder. Tests must not call this."""
    runtime = build_runtime()
    configure_file_logging(default_storage_root() / LOGS_DIR)
    return create_app(runtime)
