import logging
from typing import Any
from uuid import UUID

import pytest
from fastapi.testclient import TestClient
from service_helpers import ManualClock
from synthetic_files import SYNTHETIC_PDF, synthetic_docx

from cv_masking.adapters.local_storage import LocalInputStore, LocalWorkArea, StorageRoot
from cv_masking.api.app import create_app
from cv_masking.api.runtime import Runtime, limits_from_settings
from cv_masking.application import JobService, UploadService
from cv_masking.config import Settings
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.ids import DocumentId
from http_support import app_client


def _send(
    client: TestClient,
    batch_id: str,
    data: bytes,
    name: str = "synthetic.pdf",
    content_type: str = "application/pdf",
) -> Any:
    return client.post(
        f"/api/batches/{batch_id}/documents",
        files={"file": (name, data, content_type)},
    )


def test_upload_pdf_and_docx_then_start(
    client: TestClient, service: JobService, root: StorageRoot
) -> None:
    created = client.post("/api/batches", json={"mask_salary": True})
    assert created.status_code == 201
    batch_id = created.json()["batch_id"]
    pdf = _send(client, batch_id, SYNTHETIC_PDF)
    assert pdf.status_code == 201
    assert pdf.json()["state"] == DocumentState.UPLOADED.value
    assert pdf.json()["document_format"] == "pdf"
    assert "filename" not in pdf.json()
    assert "sha256" not in pdf.json()
    assert "Nguyen" not in str(pdf.json())
    docx = _send(
        client,
        batch_id,
        synthetic_docx(),
        name="synthetic.docx",
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )
    assert docx.status_code == 201
    status = client.get(f"/api/batches/{batch_id}")
    assert status.status_code == 200
    assert status.json()["document_count"] == 2
    started = client.post(
        f"/api/batches/{batch_id}/start",
        json={"expected_version": status.json()["version"]},
    )
    assert started.status_code == 200
    assert started.json()["state"] == "running"
    assert len(list((root.path / "inputs").iterdir())) == 2


def test_spoofed_extension_is_refused(client: TestClient, root: StorageRoot) -> None:
    batch_id = client.post("/api/batches", json={}).json()["batch_id"]
    response = _send(client, batch_id, SYNTHETIC_PDF, name="synthetic.docx")
    assert response.status_code == 400
    assert response.json()["code"] == ErrorCode.UPLOAD_SPOOFED_TYPE
    assert list((root.path / "inputs").iterdir()) == []


def test_oversized_file_is_refused(
    service: JobService,
    input_store: LocalInputStore,
    work_area: LocalWorkArea,
    clock: ManualClock,
    root: StorageRoot,
) -> None:
    tight = Settings(max_file_bytes=40)
    client = app_client(
        create_app(
            Runtime(
                service,
                UploadService(service, input_store, work_area, clock, limits_from_settings(tight)),
                tight,
            )
        )
    )
    batch_id = client.post("/api/batches", json={}).json()["batch_id"]
    response = _send(client, batch_id, SYNTHETIC_PDF + b"x" * 40)
    assert response.status_code == 413
    assert response.json()["code"] == ErrorCode.UPLOAD_FILE_TOO_LARGE
    assert list((root.path / "inputs").iterdir()) == []


def test_duplicate_in_the_same_batch_is_refused(client: TestClient, root: StorageRoot) -> None:
    batch_id = client.post("/api/batches", json={}).json()["batch_id"]
    assert _send(client, batch_id, SYNTHETIC_PDF).status_code == 201
    response = _send(client, batch_id, SYNTHETIC_PDF)
    assert response.status_code == 409
    assert response.json()["code"] == ErrorCode.UPLOAD_DUPLICATE
    assert len(list((root.path / "inputs").iterdir())) == 1


def test_malformed_multipart_is_refused(client: TestClient) -> None:
    batch_id = client.post("/api/batches", json={}).json()["batch_id"]
    response = client.post(f"/api/batches/{batch_id}/documents")
    assert response.status_code == 400
    assert response.json()["code"] == ErrorCode.UPLOAD_MALFORMED_REQUEST


def test_one_bad_file_does_not_remove_the_good_one(client: TestClient, root: StorageRoot) -> None:
    batch_id = client.post("/api/batches", json={}).json()["batch_id"]
    good = _send(client, batch_id, SYNTHETIC_PDF)
    assert good.status_code == 201
    bad = _send(client, batch_id, b"not a document", name="synthetic.pdf")
    assert bad.status_code == 400
    assert bad.json()["code"] == ErrorCode.UPLOAD_UNSUPPORTED_TYPE
    status = client.get(f"/api/batches/{batch_id}").json()
    assert status["document_count"] == 2
    states = {item["state"] for item in status["documents"]}
    assert states == {DocumentState.UPLOADED.value, DocumentState.FAILED.value}
    assert len(list((root.path / "inputs").iterdir())) == 1


def test_filename_never_appears_in_logs_or_status(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    leaky = "CV_Nguyen_Van_Mau_0900000000.pdf"
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        batch_id = client.post("/api/batches", json={}).json()["batch_id"]
        response = _send(client, batch_id, SYNTHETIC_PDF, name=leaky)
    assert response.status_code == 201
    payload = str(response.json()) + client.get(f"/api/batches/{batch_id}").text
    combined = payload + " ".join(record.getMessage() for record in caplog.records)
    for fragment in ("Nguyen", "0900000000", leaky):
        assert fragment not in combined


def test_closed_batch_rejects_new_uploads(client: TestClient) -> None:
    batch_id = client.post("/api/batches", json={}).json()["batch_id"]
    assert _send(client, batch_id, SYNTHETIC_PDF).status_code == 201
    version = client.get(f"/api/batches/{batch_id}").json()["version"]
    client.post(f"/api/batches/{batch_id}/start", json={"expected_version": version})
    response = _send(client, batch_id, SYNTHETIC_PDF + b"% extra\n")
    assert response.status_code == 409
    assert response.json()["code"] == ErrorCode.UPLOAD_BATCH_CLOSED


def test_retry_replaces_a_failed_document_after_start(
    client: TestClient, service: JobService
) -> None:
    batch_id = client.post("/api/batches", json={}).json()["batch_id"]
    first = _send(client, batch_id, SYNTHETIC_PDF)
    failed_id = first.json()["document_id"]
    version = client.get(f"/api/batches/{batch_id}").json()["version"]
    client.post(f"/api/batches/{batch_id}/start", json={"expected_version": version})
    document_id = DocumentId(UUID(failed_id))
    service.apply(document_id, lambda job, at: job.start_validation(at))
    service.apply(document_id, lambda job, at: job.fail(ErrorCode.INTERNAL_ERROR, at))
    retry = client.post(
        f"/api/batches/{batch_id}/documents",
        params={"replaces": failed_id},
        files={"file": ("synthetic.pdf", SYNTHETIC_PDF, "application/pdf")},
    )
    assert retry.status_code == 201
    assert retry.json()["document_id"] != failed_id
    assert retry.json()["state"] == DocumentState.UPLOADED.value
    status = client.get(f"/api/batches/{batch_id}").json()
    assert status["state"] == "running"
    assert status["document_count"] == 1
    assert {row["document_id"] for row in status["documents"]} == {retry.json()["document_id"]}
    extra = _send(client, batch_id, SYNTHETIC_PDF + b"% extra\n")
    assert extra.status_code == 409
    assert extra.json()["code"] == ErrorCode.UPLOAD_BATCH_CLOSED
