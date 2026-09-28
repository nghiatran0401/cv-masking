"""Serve the Vite production build from the API origin. No remote assets."""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_ENV_VAR = "CV_MASKING_STATIC_DIR"
PACKAGE_STATIC = Path(__file__).resolve().parent.parent / "static"


def resolve_static_directory(environ: Mapping[str, str] | None = None) -> Path | None:
    """Packaged ``cv_masking/static`` after ``make build``, or ``CV_MASKING_STATIC_DIR``."""
    env = os.environ if environ is None else environ
    raw = env.get(STATIC_ENV_VAR)
    if raw:
        path = Path(raw)
        return path if (path / "index.html").is_file() else None
    if (PACKAGE_STATIC / "index.html").is_file():
        return PACKAGE_STATIC
    return None


def safe_ui_index(directory: Path) -> Path:
    """``index.html`` inside ``directory``; refuse a missing file or a symlink escape."""
    root = directory.resolve()
    index = root / "index.html"
    if index.is_symlink() or not index.is_file():
        raise ValueError("ui index missing")
    resolved = index.resolve()
    if not resolved.is_relative_to(root):
        raise ValueError("ui index escaped")
    return resolved


def is_public_ui_path(method: str, path: str) -> bool:
    """HTML and hashed Vite assets are public; everything else still needs a session."""
    if method not in {"GET", "HEAD"}:
        return False
    if ".." in path.split("/"):
        return False
    if path in {"/", "/index.html"}:
        return True
    return path.startswith("/assets/")


def register_ui(app: FastAPI, directory: Path) -> None:
    index = safe_ui_index(directory)
    assets = directory / "assets"

    @app.get("/")
    @app.get("/index.html")
    def ui_index() -> FileResponse:
        return FileResponse(index, media_type="text/html; charset=utf-8")

    if assets.is_dir() and not assets.is_symlink():
        app.mount(
            "/assets",
            StaticFiles(directory=str(assets.resolve()), follow_symlink=False),
            name="ui-assets",
        )
