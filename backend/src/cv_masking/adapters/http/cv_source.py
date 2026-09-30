"""HTTPS GET of one allowlisted CV URL.

This module is the only source file allowed to import ``http.client``. It also
runs ``/usr/bin/security`` to read public certificates from fixed Mac keychains.
It does not follow a redirect to another host, does not send cookies, and does
not put the URL into an exception.
"""

import http.client
import ssl
import subprocess
import sys
from collections.abc import Callable, Mapping
from contextlib import suppress
from pathlib import Path
from typing import Final, Protocol, cast
from urllib.parse import urljoin, urlsplit

from cv_masking.domain.limits import READ_CHUNK_BYTES
from cv_masking.domain.source_url import SOURCE_CV_HOST, parse_cv_source_url
from cv_masking.ports.cv_source import CvSourceError

SOURCE_FETCH_TIMEOUT_SECONDS: Final = 20.0
_MAX_REDIRECTS: Final = 3
_REDIRECT_STATUS: Final = frozenset({301, 302, 303, 307, 308})
_SECURITY_BIN: Final = "/usr/bin/security"
_KEYCHAINS: Final = (
    Path("/System/Library/Keychains/SystemRootCertificates.keychain"),
    Path("/Library/Keychains/System.keychain"),
    Path.home() / "Library/Keychains/login.keychain-db",
)
_REQUEST_HEADERS: Final[Mapping[str, str]] = {
    "User-Agent": "cv-masking",
    "Accept": "application/octet-stream",
    "Connection": "close",
}


class CvHttpResponse(Protocol):
    status: int

    def getheader(self, name: str) -> str | None: ...

    def read(self, amount: int) -> bytes: ...


class CvHttpConnection(Protocol):
    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None: ...

    def getresponse(self) -> CvHttpResponse: ...

    def close(self) -> None: ...


Connect = Callable[[str, int, float], CvHttpConnection]


def _open(host: str, port: int, timeout: float) -> CvHttpConnection:
    if host != SOURCE_CV_HOST or port != 443:
        raise CvSourceError
    # http.client's types don't match the small protocol this module calls.
    return cast(
        CvHttpConnection,
        http.client.HTTPSConnection(
            host,
            port,
            timeout=timeout,
            context=_trusted_context(),
        ),
    )


def _run_security(argv: list[str]) -> bytes | None:
    """Export public certificates only. ``argv`` is a fixed keychain path, never a URL."""
    try:
        completed = subprocess.run(
            argv,
            check=False,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None
    if completed.returncode != 0 or not completed.stdout:
        return None
    return bytes(completed.stdout)


def _build_context(run: Callable[[list[str]], bytes | None] = _run_security) -> ssl.SSLContext:
    """Verify certificates with the public CAs plus the Mac keychains.

    A bank laptop often trusts a company root in the keychain. The default
    Python bundle does not. Verification stays on; a bad export is ignored.
    """
    ctx = ssl.create_default_context()
    if sys.platform == "darwin":
        pems = [raw.decode("ascii", "ignore") for raw in _keychain_pems(run) if raw]
        if pems:
            try:
                ctx.load_verify_locations(cadata="\n".join(pems))
            except ssl.SSLError:
                ctx = ssl.create_default_context()
    if ctx.verify_mode != ssl.CERT_REQUIRED or not ctx.check_hostname:
        raise CvSourceError
    return ctx


def _keychain_pems(run: Callable[[list[str]], bytes | None]) -> list[bytes]:
    found: list[bytes] = []
    for path in _KEYCHAINS:
        if not path.is_file():
            continue
        raw = run([_SECURITY_BIN, "find-certificate", "-a", "-p", str(path)])
        if raw:
            found.append(raw)
    return found


_CACHED_CONTEXT: ssl.SSLContext | None = None


def _trusted_context() -> ssl.SSLContext:
    global _CACHED_CONTEXT
    if _CACHED_CONTEXT is None:
        _CACHED_CONTEXT = _build_context()
    return _CACHED_CONTEXT


class HttpsCvSource:
    """GET ``href`` with certificate verification. ``connect`` is injectable for tests."""

    __slots__ = ("_connect", "_timeout")

    def __init__(
        self,
        connect: Connect | None = None,
        *,
        timeout: float = SOURCE_FETCH_TIMEOUT_SECONDS,
    ) -> None:
        chosen: Connect = _open if connect is None else connect
        self._connect = chosen
        self._timeout = timeout

    def fetch(self, href: str, *, max_bytes: int) -> bytes:
        current = href
        for hop in range(_MAX_REDIRECTS + 1):
            parsed = parse_cv_source_url(current)
            if parsed is None or max_bytes < 1:
                raise CvSourceError
            body, location = self._get(parsed.href, max_bytes)
            if location is None:
                return body
            if hop == _MAX_REDIRECTS:
                break
            current = location
        raise CvSourceError

    def _get(self, href: str, max_bytes: int) -> tuple[bytes, str | None]:
        parts = urlsplit(href)
        if (
            parts.scheme != "https"
            or parts.hostname != SOURCE_CV_HOST
            or parts.port not in (None, 443)
        ):
            raise CvSourceError
        target = parts.path if parts.query == "" else f"{parts.path}?{parts.query}"
        conn: CvHttpConnection | None = None
        try:
            conn = self._connect(SOURCE_CV_HOST, 443, self._timeout)
            conn.request("GET", target, headers=_REQUEST_HEADERS)
            response = conn.getresponse()
            if response.status in _REDIRECT_STATUS:
                return b"", _same_host_redirect(href, response.getheader("Location"))
            if response.status != 200:
                raise CvSourceError
            declared = _content_length(response.getheader("Content-Length"), max_bytes)
            if declared == 0:
                return b"", None
            return _read_capped(response, max_bytes), None
        except CvSourceError:
            raise
        except (OSError, http.client.HTTPException, TimeoutError):
            raise CvSourceError from None
        finally:
            if conn is not None:
                with suppress(OSError):
                    conn.close()


def _same_host_redirect(current: str, location: str | None) -> str:
    if location is None:
        raise CvSourceError
    joined = urljoin(current, location.strip())
    parsed = parse_cv_source_url(joined)
    if parsed is None:
        raise CvSourceError
    return parsed.href


def _content_length(header: str | None, max_bytes: int) -> int | None:
    if header is None or header == "":
        return None
    try:
        declared = int(header)
    except ValueError:
        raise CvSourceError from None
    if declared < 0 or declared > max_bytes:
        raise CvSourceError
    return declared


def _read_capped(response: CvHttpResponse, max_bytes: int) -> bytes:
    chunks: list[bytes] = []
    total = 0
    while True:
        block = response.read(READ_CHUNK_BYTES)
        if block == b"":
            return b"".join(chunks)
        total += len(block)
        if total > max_bytes:
            raise CvSourceError
        chunks.append(block)
