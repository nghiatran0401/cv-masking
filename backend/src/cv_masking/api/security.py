"""Loopback Host/Origin checks, session cookie, CSRF header, rate limit, security headers."""

from __future__ import annotations

import hmac
import secrets
from collections import deque
from dataclasses import dataclass
from threading import Lock
from time import monotonic
from typing import Final

from starlette.datastructures import Headers, MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from cv_masking.api.errors import error_response
from cv_masking.api.ui import is_public_ui_path
from cv_masking.config import DEFAULT_PORT, LOOPBACK_HOST, SOURCE_CV_HOST, Settings
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES

SESSION_COOKIE: Final = "cv_masking_session"
CSRF_HEADER: Final = "x-csrf-token"
DEV_FRONTEND_PORT: Final = 5173
HEALTH_PATH: Final = "/api/health"
SESSION_PATH: Final = "/api/session"
RATE_WINDOW_SECONDS: Final = 60.0
RATE_LIMIT_MAX: Final = 240
MAX_CONTENT_LENGTH: Final = HARD_MAX_FILE_BYTES + 1_048_576

_CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self'; font-src 'self'; "
    f"connect-src 'self' https://{SOURCE_CV_HOST}; "
    "frame-src 'self' blob:; object-src 'none'; "
    "base-uri 'self'; frame-ancestors 'none'; form-action 'self'"
)

_SECURITY_HEADERS: Final = (
    ("Content-Security-Policy", _CONTENT_SECURITY_POLICY),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
    ("Referrer-Policy", "no-referrer"),
    ("Cache-Control", "no-store"),
    ("Permissions-Policy", "camera=(), microphone=(), geolocation=()"),
    ("Cross-Origin-Opener-Policy", "same-origin"),
    ("Cross-Origin-Resource-Policy", "same-origin"),
)

_MUTATING: Final = frozenset({"POST", "PUT", "PATCH", "DELETE"})


class BootstrapGate:
    """One-time launcher token. Dev/tests omit it and ``GET /api/session`` stays open."""

    __slots__ = ("_lock", "_token", "_used")

    def __init__(self, token: str | None) -> None:
        self._token = token
        self._used = False
        self._lock = Lock()

    def allow(self, given: str | None, cookie: str | None, session_token: str) -> bool:
        if self._token is None:
            return True
        if cookie is not None and _same_secret(cookie, session_token):
            return True
        if given is None:
            return False
        with self._lock:
            if self._used:
                return False
            if not _same_secret(given, self._token):
                return False
            self._used = True
            return True


@dataclass(frozen=True, slots=True)
class SessionState:
    session_token: str
    csrf_token: str
    bootstrap: BootstrapGate

    @staticmethod
    def new(*, bootstrap_token: str | None = None) -> SessionState:
        return SessionState(
            secrets.token_urlsafe(32),
            secrets.token_urlsafe(32),
            BootstrapGate(bootstrap_token),
        )


def allowed_hosts(settings: Settings) -> frozenset[str]:
    return frozenset(
        {
            f"{LOOPBACK_HOST}:{settings.port}",
            f"{LOOPBACK_HOST}:{DEV_FRONTEND_PORT}",
            f"{LOOPBACK_HOST}:{DEFAULT_PORT}",
        }
    )


def allowed_origins(settings: Settings) -> frozenset[str]:
    return frozenset(
        {
            f"http://{LOOPBACK_HOST}:{settings.port}",
            f"http://{LOOPBACK_HOST}:{DEV_FRONTEND_PORT}",
            f"http://{LOOPBACK_HOST}:{DEFAULT_PORT}",
        }
    )


class RateLimiter:
    """A single-user sliding window. One HR operator on loopback."""

    __slots__ = ("_hits",)

    def __init__(self) -> None:
        self._hits: deque[float] = deque()

    def allow(self) -> bool:
        now = monotonic()
        cutoff = now - RATE_WINDOW_SECONDS
        while self._hits and self._hits[0] < cutoff:
            self._hits.popleft()
        if len(self._hits) >= RATE_LIMIT_MAX:
            return False
        self._hits.append(now)
        return True


def apply_security_headers(headers: MutableHeaders) -> None:
    for name, value in _SECURITY_HEADERS:
        headers[name] = value


class SecurityGate:
    """Outermost ASGI wrapper: Host, Origin, session, CSRF, size, rate, headers."""

    def __init__(
        self,
        app: ASGIApp,
        session: SessionState,
        settings: Settings,
        limiter: RateLimiter,
    ) -> None:
        self.app = app
        self.session = session
        self.settings = settings
        self.limiter = limiter
        self._hosts = allowed_hosts(settings)
        self._origins = allowed_origins(settings)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        refusal = self._refuse(scope["method"], scope["path"], headers)
        if refusal is not None:
            code, status = refusal
            response = error_response(code, status)
            apply_security_headers(response.headers)
            await response(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                mutable = MutableHeaders(raw=list(message["headers"]))
                apply_security_headers(mutable)
                message["headers"] = mutable.raw
            await send(message)

        await self.app(scope, receive, send_with_headers)

    def _refuse(self, method: str, path: str, headers: Headers) -> tuple[ErrorCode, int] | None:
        host = headers.get("host", "")
        if host not in self._hosts:
            return ErrorCode.SECURITY_HOST_REJECTED, 403
        if not self.limiter.allow():
            return ErrorCode.SECURITY_RATE_LIMITED, 429
        raw_length = headers.get("content-length")
        if raw_length is not None and (
            not raw_length.isdigit() or int(raw_length) > MAX_CONTENT_LENGTH
        ):
            return ErrorCode.UPLOAD_FILE_TOO_LARGE, 413
        origin = headers.get("origin")
        if origin is not None and origin not in self._origins:
            return ErrorCode.SECURITY_ORIGIN_REJECTED, 403
        if path == HEALTH_PATH and method == "GET":
            return None
        if path == SESSION_PATH and method == "GET":
            return None
        if is_public_ui_path(method, path):
            return None
        if method in _MUTATING and origin is None:
            return ErrorCode.SECURITY_ORIGIN_REJECTED, 403
        cookie = _cookie_value(headers.get("cookie"), SESSION_COOKIE)
        csrf = headers.get(CSRF_HEADER)
        if cookie is None or csrf is None:
            return ErrorCode.SECURITY_TOKEN_INVALID, 403
        if not _same_secret(cookie, self.session.session_token) or not _same_secret(
            csrf, self.session.csrf_token
        ):
            return ErrorCode.SECURITY_TOKEN_INVALID, 403
        return None


def _same_secret(given: str, expected: str) -> bool:
    if len(given) != len(expected):
        return False
    return hmac.compare_digest(given, expected)


def _cookie_value(header: str | None, name: str) -> str | None:
    if header is None:
        return None
    for part in header.split(";"):
        stripped = part.strip()
        if stripped.startswith(name + "="):
            return stripped[len(name) + 1 :]
    return None
