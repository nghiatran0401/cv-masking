"""Import one allowlisted CV URL through a fake fetcher. No socket is opened."""

import logging

import pytest
from fastapi.testclient import TestClient
from synthetic_files import SYNTHETIC_PDF, synthetic_docx

from cv_masking.api.app import create_app
from cv_masking.api.runtime import Runtime
from cv_masking.application import JobService, SourceImportService, UploadService
from cv_masking.config import Settings
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.source_url import SOURCE_CV_HOST
from cv_masking.ports.cv_source import CvSourceError
from http_support import app_client

MARKER = "synthetic-marker"
PDF_URL = f"https://{SOURCE_CV_HOST}/2026/{MARKER}/synthetic-cv.pdf"
DOCX_URL = f"https://{SOURCE_CV_HOST}/2026/{MARKER}/synthetic-cv.docx"


class FakeSource:
    def __init__(self, payload: bytes = SYNTHETIC_PDF, *, fail: bool = False) -> None:
        self.payload = payload
        self.fail = fail
        self.hrefs: list[str] = []
        self.max_bytes: list[int] = []

    def fetch(self, href: str, *, max_bytes: int) -> bytes:
        self.hrefs.append(href)
        self.max_bytes.append(max_bytes)
        if self.fail:
            raise CvSourceError
        return self.payload


def _client(
    service: JobService, uploads: UploadService, settings: Settings, source: FakeSource
) -> TestClient:
    runtime = Runtime(
        service,
        uploads,
        settings,
        source_imports=SourceImportService(uploads, source, max_file_bytes=settings.max_file_bytes),
    )
    return app_client(create_app(runtime))


def _batch(client: TestClient) -> str:
    created = client.post("/api/batches", json={"mask_salary": True})
    assert created.status_code == 201
    batch_id = created.json()["batch_id"]
    assert isinstance(batch_id, str)
    return batch_id


def test_import_stores_a_pdf_without_echoing_the_url(
    service: JobService,
    uploads: UploadService,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    source = FakeSource()
    client = _client(service, uploads, settings, source)
    batch_id = _batch(client)
    response = client.post(f"/api/batches/{batch_id}/source-links", json={"url": PDF_URL})
    assert response.status_code == 201
    body = response.json()
    assert body["state"] == "uploaded"
    assert body["document_format"] == "pdf"
    assert MARKER not in response.text
    assert "ehiring" not in response.text
    assert "synthetic-cv" not in response.text
    assert MARKER not in caplog.text
    assert source.hrefs == [PDF_URL]


def test_import_stores_a_docx(
    service: JobService, uploads: UploadService, settings: Settings
) -> None:
    source = FakeSource(synthetic_docx())
    client = _client(service, uploads, settings, source)
    batch_id = _batch(client)
    response = client.post(f"/api/batches/{batch_id}/source-links", json={"url": DOCX_URL})
    assert response.status_code == 201
    assert response.json()["document_format"] == "docx"
    assert MARKER not in response.text


def test_other_host_is_refused_without_a_fetch(
    service: JobService, uploads: UploadService, settings: Settings
) -> None:
    source = FakeSource()
    client = _client(service, uploads, settings, source)
    batch_id = _batch(client)
    response = client.post(
        f"/api/batches/{batch_id}/source-links",
        json={"url": "https://evil.example/synthetic-cv.pdf"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == ErrorCode.UPLOAD_MALFORMED_REQUEST
    assert "evil.example" not in response.text
    assert source.hrefs == []


def test_a_fetch_failure_has_no_url_in_the_response_or_log(
    service: JobService,
    uploads: UploadService,
    settings: Settings,
    caplog: pytest.LogCaptureFixture,
) -> None:
    caplog.set_level(logging.DEBUG)
    source = FakeSource(fail=True)
    client = _client(service, uploads, settings, source)
    batch_id = _batch(client)
    response = client.post(f"/api/batches/{batch_id}/source-links", json={"url": PDF_URL})
    assert response.status_code == 400
    assert response.json()["code"] == ErrorCode.UPLOAD_SOURCE_UNAVAILABLE
    assert MARKER not in response.text
    assert MARKER not in caplog.text
    assert "ehiring" not in caplog.text


def test_a_login_page_is_not_stored(
    service: JobService, uploads: UploadService, settings: Settings
) -> None:
    source = FakeSource(b"<html>login</html>")
    client = _client(service, uploads, settings, source)
    batch_id = _batch(client)
    response = client.post(f"/api/batches/{batch_id}/source-links", json={"url": PDF_URL})
    assert response.status_code == 400
    assert response.json()["code"] == ErrorCode.UPLOAD_UNSUPPORTED_TYPE
    assert "login" not in response.text
    assert MARKER not in response.text


def test_an_oversized_body_is_refused(
    service: JobService, uploads: UploadService, settings: Settings
) -> None:
    source = FakeSource(b"0123456789")
    limited = Settings(max_file_bytes=4)
    client = _client(service, uploads, limited, source)
    batch_id = _batch(client)
    response = client.post(f"/api/batches/{batch_id}/source-links", json={"url": PDF_URL})
    assert response.status_code == 413
    assert response.json()["code"] == ErrorCode.UPLOAD_FILE_TOO_LARGE


def test_a_validation_error_does_not_echo_the_url(
    service: JobService, uploads: UploadService, settings: Settings
) -> None:
    source = FakeSource()
    client = _client(service, uploads, settings, source)
    batch_id = _batch(client)
    response = client.post(
        f"/api/batches/{batch_id}/source-links",
        json={"url": "https://evil.example/synthetic-cv.pdf", "note": "leak"},
    )
    assert response.status_code == 400
    assert response.json()["code"] == ErrorCode.UPLOAD_MALFORMED_REQUEST
    assert "evil.example" not in response.text
    assert source.hrefs == []
