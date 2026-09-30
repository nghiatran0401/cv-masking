"""HTTPS CV fetch with an injected connection. No socket is opened."""

import ssl
import sys
from collections.abc import Mapping

import pytest

from cv_masking.adapters.http.cv_source import (
    SOURCE_FETCH_TIMEOUT_SECONDS,
    HttpsCvSource,
    _build_context,
    _open,
)
from cv_masking.domain.source_url import SOURCE_CV_HOST
from cv_masking.ports.cv_source import CvSourceError

PDF = b"%PDF-1.7\n% synthetic\n"
HREF = f"https://{SOURCE_CV_HOST}/2026/synthetic-token/synthetic-cv.pdf"


class FakeResponse:
    def __init__(self, status: int, headers: Mapping[str, str], chunks: list[bytes]) -> None:
        self.status = status
        self._headers = {key.lower(): value for key, value in headers.items()}
        self._chunks = list(chunks)
        self.reads = 0

    def getheader(self, name: str) -> str | None:
        return self._headers.get(name.lower())

    def read(self, amount: int) -> bytes:
        self.reads += 1
        if not self._chunks:
            return b""
        return self._chunks.pop(0)[:amount]


class FakeConnection:
    def __init__(self, script: "Script", response: FakeResponse) -> None:
        self._script = script
        self._response = response

    def request(
        self,
        method: str,
        url: str,
        body: bytes | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> None:
        self._script.requests.append((method, url, dict(headers or {})))

    def getresponse(self) -> FakeResponse:
        return self._response

    def close(self) -> None:
        return None


class Script:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self._responses = list(responses)
        self.requests: list[tuple[str, str, dict[str, str]]] = []
        self.opened: list[tuple[str, int, float]] = []

    def connect(self, host: str, port: int, timeout: float) -> FakeConnection:
        self.opened.append((host, port, timeout))
        return FakeConnection(self, self._responses.pop(0))


def _source(responses: list[FakeResponse]) -> tuple[HttpsCvSource, Script]:
    script = Script(responses)
    return HttpsCvSource(script.connect), script


def test_get_returns_the_body_without_cookies() -> None:
    source, script = _source([FakeResponse(200, {}, [PDF])])
    assert source.fetch(HREF, max_bytes=len(PDF)) == PDF
    assert script.opened == [(SOURCE_CV_HOST, 443, SOURCE_FETCH_TIMEOUT_SECONDS)]
    method, target, headers = script.requests[0]
    assert method == "GET"
    assert target == "/2026/synthetic-token/synthetic-cv.pdf"
    lowered = {key.lower() for key in headers}
    assert "cookie" not in lowered
    assert "authorization" not in lowered
    assert "referer" not in lowered
    assert headers["User-Agent"] == "cv-masking"


def test_follows_a_same_host_redirect_only() -> None:
    source, script = _source(
        [
            FakeResponse(302, {"Location": "/2026/other.pdf"}, []),
            FakeResponse(200, {}, [PDF]),
        ]
    )
    assert source.fetch(HREF, max_bytes=len(PDF)) == PDF
    assert [host for host, _port, _timeout in script.opened] == [SOURCE_CV_HOST, SOURCE_CV_HOST]
    assert script.requests[1][1] == "/2026/other.pdf"


def test_refuses_an_off_host_redirect_without_connecting_again() -> None:
    source, script = _source(
        [FakeResponse(302, {"Location": "https://evil.example/synthetic-cv.pdf"}, [])]
    )
    with pytest.raises(CvSourceError) as caught:
        source.fetch(HREF, max_bytes=100)
    assert script.opened == [(SOURCE_CV_HOST, 443, SOURCE_FETCH_TIMEOUT_SECONDS)]
    assert "evil.example" not in str(caught.value)
    assert "synthetic-token" not in str(caught.value)


def test_does_not_connect_for_a_refused_url() -> None:
    source, script = _source([])
    with pytest.raises(CvSourceError):
        source.fetch("https://evil.example/synthetic-cv.pdf", max_bytes=100)
    with pytest.raises(CvSourceError):
        source.fetch(f"http://{SOURCE_CV_HOST}/synthetic-cv.pdf", max_bytes=100)
    assert script.opened == []


def test_refuses_a_declared_oversize_body_before_reading() -> None:
    response = FakeResponse(200, {"Content-Length": "99999"}, [PDF])
    source, _script = _source([response])
    with pytest.raises(CvSourceError):
        source.fetch(HREF, max_bytes=100)
    assert response.reads == 0


def test_refuses_a_body_that_grows_past_the_cap() -> None:
    source, _script = _source([FakeResponse(200, {}, [b"%PDF-too-long"])])
    with pytest.raises(CvSourceError):
        source.fetch(HREF, max_bytes=4)


def test_refuses_a_non_success_status() -> None:
    source, _script = _source([FakeResponse(401, {}, [b"login"])])
    with pytest.raises(CvSourceError) as caught:
        source.fetch(HREF, max_bytes=100)
    assert "login" not in str(caught.value)
    assert "synthetic-token" not in str(caught.value)


def test_a_network_error_does_not_keep_the_url() -> None:
    def connect(_host: str, _port: int, _timeout: float) -> FakeConnection:
        raise OSError(f"timed out {HREF}")

    source = HttpsCvSource(connect)
    with pytest.raises(CvSourceError) as caught:
        source.fetch(HREF, max_bytes=100)
    assert str(caught.value) == "source fetch failed"
    assert caught.value.__cause__ is None
    assert "synthetic-token" not in str(caught.value)


def test_open_refuses_a_different_host_before_connecting() -> None:
    with pytest.raises(CvSourceError):
        _open("evil.example", 443, 1.0)


def test_mac_context_reads_only_fixed_keychains_and_keeps_verification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(sys, "platform", "darwin")
    seen: list[list[str]] = []

    def run(argv: list[str]) -> bytes | None:
        seen.append(argv)
        return b"not-a-certificate"

    ctx = _build_context(run)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
    assert seen
    for argv in seen:
        assert argv[:4] == ["/usr/bin/security", "find-certificate", "-a", "-p"]
        assert argv[4].endswith((".keychain", ".keychain-db"))


def test_other_platforms_do_not_read_keychains(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")

    def run(argv: list[str]) -> bytes | None:
        raise AssertionError(argv)

    ctx = _build_context(run)
    assert ctx.verify_mode == ssl.CERT_REQUIRED
    assert ctx.check_hostname is True
