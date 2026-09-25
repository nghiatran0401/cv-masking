from fastapi import FastAPI

from cv_masking import __version__
from cv_masking.api.health import router as health_router


def create_app() -> FastAPI:
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
    app.include_router(health_router)
    return app
