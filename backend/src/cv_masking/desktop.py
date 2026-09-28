"""macOS desktop start: one process, loopback health wait, default browser, lock file."""

from __future__ import annotations

import fcntl
import http.client
import logging
import os
import re
import secrets
import subprocess
import threading
from pathlib import Path
from time import monotonic, sleep
from typing import Final

import uvicorn

from cv_masking.adapters.local_storage import LOCK_DIR, StorageRoot, default_storage_root
from cv_masking.api.ui import resolve_static_directory
from cv_masking.config import BOOTSTRAP_ENV_VAR, LOOPBACK_HOST, Settings, load_settings

APP_FACTORY: Final = "cv_masking.api.app:create_runtime_app"
OPEN_BIN: Final = "/usr/bin/open"
HEALTH_WAIT_SECONDS: Final = 30.0
HEALTH_POLL_SECONDS: Final = 0.1
_BOOTSTRAP_CHARS: Final = re.compile(r"^[A-Za-z0-9_-]+$")
_PID_MODE: Final = 0o600

logger = logging.getLogger("cv_masking.desktop")


class InstanceLock:
    """Exclusive flock so a second double-click cannot bind the same port."""

    def __init__(self, path: Path) -> None:
        self._path = path
        self._fd: int | None = None

    def acquire(self) -> bool:
        self._path.parent.mkdir(mode=0o700, exist_ok=True)
        self._path.parent.chmod(0o700)
        handle = os.open(
            self._path,
            os.O_CREAT | os.O_RDWR | os.O_CLOEXEC,
            _PID_MODE,
        )
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            os.close(handle)
            return False
        os.ftruncate(handle, 0)
        os.write(handle, str(os.getpid()).encode("ascii"))
        os.fsync(handle)
        self._path.chmod(_PID_MODE)
        self._fd = handle
        return True

    def close(self) -> None:
        handle = self._fd
        self._fd = None
        if handle is None:
            return
        fcntl.flock(handle, fcntl.LOCK_UN)
        os.close(handle)


def loopback_ui_url(port: int, bootstrap: str | None) -> str:
    if not 1024 <= port <= 65535:
        raise ValueError("port out of range")
    base = f"http://{LOOPBACK_HOST}:{port}/"
    if bootstrap is None:
        return base
    if _BOOTSTRAP_CHARS.fullmatch(bootstrap) is None:
        raise ValueError("bootstrap token rejected")
    return f"{base}?bootstrap={bootstrap}"


def probe_health(port: int, timeout: float = 0.5) -> bool:
    """GET /api/health on loopback only. Does not send the bootstrap token."""
    connection = http.client.HTTPConnection(LOOPBACK_HOST, port, timeout=timeout)
    try:
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        return response.status == 200
    except OSError:
        return False
    finally:
        connection.close()


def wait_health(port: int, timeout: float = HEALTH_WAIT_SECONDS) -> None:
    deadline = monotonic() + timeout
    while monotonic() < deadline:
        if probe_health(port):
            return
        sleep(HEALTH_POLL_SECONDS)
    raise TimeoutError("health wait expired")


def open_loopback_browser(port: int, bootstrap: str | None) -> None:
    url = loopback_ui_url(port, bootstrap)
    subprocess.run([OPEN_BIN, url], check=True, timeout=10)


def run_desktop(*, open_browser: bool = True, settings: Settings | None = None) -> None:
    chosen = settings if settings is not None else load_settings()
    if chosen.host != LOOPBACK_HOST:
        raise SystemExit("desktop mode refuses a non-loopback host")
    if resolve_static_directory() is None:
        raise SystemExit("UI build missing; run make build")
    if probe_health(chosen.port):
        logger.info("already running; opening the browser")
        if open_browser:
            open_loopback_browser(chosen.port, None)
        return

    root = StorageRoot.prepare(default_storage_root())
    lock = InstanceLock(root.path / LOCK_DIR / "instance.lock")
    if not lock.acquire():
        logger.info("lock held; opening the browser")
        if open_browser:
            open_loopback_browser(chosen.port, None)
        return

    token = secrets.token_urlsafe(32)
    os.environ[BOOTSTRAP_ENV_VAR] = token
    server = uvicorn.Server(
        uvicorn.Config(
            APP_FACTORY,
            factory=True,
            host=chosen.host,
            port=chosen.port,
            reload=False,
            proxy_headers=False,
            server_header=False,
            access_log=False,
        )
    )

    def _open_when_ready() -> None:
        try:
            wait_health(chosen.port)
        except TimeoutError:
            logger.error("health wait expired")
            server.should_exit = True
            return
        if open_browser:
            try:
                open_loopback_browser(chosen.port, token)
            except (OSError, subprocess.CalledProcessError, ValueError):
                logger.error("browser open failed")

    opener = threading.Thread(target=_open_when_ready, name="cv-masking-open", daemon=True)
    opener.start()
    try:
        server.run()
    finally:
        lock.close()
        os.environ.pop(BOOTSTRAP_ENV_VAR, None)
