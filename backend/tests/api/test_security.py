"""Stage 14: Host/Origin, session, CSRF, size, rate, headers, path, hostile files, logs."""

import logging

import pytest
from fastapi.testclient import TestClient
from synthetic_docxs import dtd_docx, traversal_docx, zip_bomb_docx
from synthetic_pdfs import many_pages_pdf

from cv_masking.adapters.docx import DocxExtractor
from cv_masking.adapters.pdf import PyMuPDFExtractor
from cv_masking.api.app import create_app
from cv_masking.api.security import CSRF_HEADER, SESSION_COOKIE
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.logging_setup import install_metadata_filter
from http_support import LOOPBACK_BASE, app_client


def _bare() -> TestClient:
    return TestClient(create_app(), base_url=LOOPBACK_BASE)


def test_hostile_host_is_rejected() -> None:
    response = _bare().get("/api/health", headers={"host": "evil.example"})
    assert response.status_code == 403
    assert response.json() == {"code": ErrorCode.SECURITY_HOST_REJECTED.value}
    assert "evil" not in response.text


def test_localhost_host_is_rejected() -> None:
    response = _bare().get("/api/health", headers={"host": "localhost:8765"})
    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.SECURITY_HOST_REJECTED.value


def test_hostile_origin_is_rejected(client: TestClient) -> None:
    response = client.post(
        "/api/batches",
        json={},
        headers={"Origin": "http://evil.example"},
    )
    assert response.status_code == 403
    assert response.json() == {"code": ErrorCode.SECURITY_ORIGIN_REJECTED.value}


def test_mutating_request_without_origin_is_rejected() -> None:
    client = _bare()
    opened = client.get("/api/session")
    client.headers[CSRF_HEADER] = opened.json()["csrf_token"]
    response = client.post("/api/batches", json={})
    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.SECURITY_ORIGIN_REJECTED.value


def test_missing_session_token_is_rejected() -> None:
    response = _bare().get("/api/batches/00000000-0000-4000-8000-000000000001")
    assert response.status_code == 403
    assert response.json() == {"code": ErrorCode.SECURITY_TOKEN_INVALID.value}


def test_wrong_csrf_token_is_rejected() -> None:
    client = app_client(create_app())
    client.headers[CSRF_HEADER] = "x" * 43
    response = client.get("/api/batches/00000000-0000-4000-8000-000000000001")
    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.SECURITY_TOKEN_INVALID.value
    assert SESSION_COOKIE.lower() not in response.text.lower()


def test_path_traversal_does_not_escape_the_api(client: TestClient) -> None:
    for path in (
        "/api/batches/../health",
        "/api/batches/%2e%2e/health",
        "/api/batches/not-a-uuid",
        "/api/batches/00000000-0000-4000-8000-000000000001/documents/"
        "00000000-0000-4000-8000-000000000002/download/..",
    ):
        response = client.get(path)
        assert response.status_code in {200, 400, 403, 404, 405, 422}
        assert b"root:" not in response.content
        assert b"/etc/" not in response.content
        body = (
            response.json()
            if "application/json" in response.headers.get("content-type", "")
            else {}
        )
        if body:
            assert set(body) <= {"code", "status", "version"}
            if "code" in body:
                assert body["code"] in {code.value for code in ErrorCode}


def test_oversized_content_length_is_refused() -> None:
    client = app_client(create_app())
    response = client.post(
        "/api/batches",
        json={"mask_salary": True},
        headers={"Content-Length": "999999999"},
    )
    assert response.status_code == 413
    assert response.json()["code"] == ErrorCode.UPLOAD_FILE_TOO_LARGE.value


def test_rate_limit_returns_a_safe_code(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cv_masking.api.security.RATE_LIMIT_MAX", 3)
    client = _bare()
    codes = [client.get("/api/health").status_code for _ in range(5)]
    assert 429 in codes
    limited = client.get("/api/health")
    assert limited.status_code == 429
    assert limited.json() == {"code": ErrorCode.SECURITY_RATE_LIMITED.value}


def test_session_sets_httponly_samesite_cookie() -> None:
    response = _bare().get("/api/session")
    assert response.status_code == 200
    assert "csrf_token" in response.json()
    cookie = response.headers.get("set-cookie", "")
    assert SESSION_COOKIE in cookie
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie or "SameSite=Strict" in cookie
    assert response.json()["csrf_token"] not in cookie


def test_malformed_pdf_upload_does_not_leak_bytes(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    payload = b"not a pdf Nguyen Van Mau 0900000000"
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        batch_id = client.post("/api/batches", json={}).json()["batch_id"]
        response = client.post(
            f"/api/batches/{batch_id}/documents",
            files={"file": ("synthetic.pdf", payload, "application/pdf")},
        )
    assert response.status_code == 400
    assert response.json()["code"] == ErrorCode.UPLOAD_UNSUPPORTED_TYPE.value
    combined = response.text + " ".join(record.getMessage() for record in caplog.records)
    assert "Nguyen" not in combined
    assert "0900000000" not in combined


def test_page_and_archive_limits_fail_closed_without_logging_payloads(
    caplog: pytest.LogCaptureFixture,
) -> None:
    pdf = PyMuPDFExtractor()
    docx = DocxExtractor()
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        pages = pdf.extract(many_pages_pdf())
        bomb = docx.extract(zip_bomb_docx())
        dtd = docx.extract(dtd_docx())
        traversal = docx.extract(traversal_docx())
    assert pages.review == frozenset({ReviewReason.PDF_TOO_MANY_PAGES})
    assert bomb.failure is ErrorCode.DOCX_RESOURCE_LIMIT
    assert dtd.failure is ErrorCode.DOCX_MALFORMED
    assert traversal.failure is ErrorCode.DOCX_UNSAFE_ARCHIVE
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "passwd" not in combined
    assert "a" * 200 not in combined
    assert "../evil" not in combined


def test_hostile_docx_upload_does_not_leak_into_status_or_logs(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        batch_id = client.post("/api/batches", json={}).json()["batch_id"]
        response = client.post(
            f"/api/batches/{batch_id}/documents",
            files={
                "file": (
                    "synthetic.docx",
                    dtd_docx(),
                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                )
            },
        )
    assert response.status_code == 201
    status = client.get(f"/api/batches/{batch_id}")
    combined = (
        response.text + status.text + " ".join(record.getMessage() for record in caplog.records)
    )
    assert "passwd" not in combined
    assert "ENTITY" not in combined


def test_filter_redacts_unsafe_log_lines(caplog: pytest.LogCaptureFixture) -> None:
    install_metadata_filter()
    logger = logging.getLogger("cv_masking")
    with caplog.at_level(logging.INFO, logger="cv_masking"):
        logger.info("contact %s", "mau.nguyen@example.test")
        logger.info("path %s", "/Users/hr/Documents/cv.pdf")
        logger.error("boom", exc_info=RuntimeError("Nguyen Van Mau 0900000000"))
        logger.info(
            "document %s processed state=%s",
            "00000000-0000-4000-8000-0000000000aa",
            "completed",
        )
    messages = [record.getMessage() for record in caplog.records]
    joined = " ".join(messages)
    assert "example.test" not in joined
    assert "/Users/" not in joined
    assert "Nguyen" not in joined
    assert "0900000000" not in joined
    assert any("processed" in message for message in messages)
    assert any("redacted" in message for message in messages)
