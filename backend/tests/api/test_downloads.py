"""Stage 13: individual masked downloads and the ZIP/CSV report (D-38)."""

import csv
import io
import zipfile
from uuid import UUID

from fastapi.testclient import TestClient
from service_helpers import SYNTHETIC_OUTPUT, uploaded_document, verified, verifying_document

from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.application import JobService, download_filename, zip_filename
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.hidden import HiddenContentCategory, HiddenContentCounts
from cv_masking.domain.policy import EntityType
from cv_masking.domain.verification import VerificationOutcome

_FINDINGS = frozenset({ReviewReason.DETECT_LOW_CONFIDENCE})


def _completed(
    service: JobService, input_store: LocalInputStore, output_store: LocalOutputStore
) -> DocumentJob:
    batch = service.create_batch()
    job = verifying_document(service, input_store, output_store, batch.batch_id)
    return verified(service, job, VerificationOutcome.PASSED)


def test_download_uses_the_redacted_uuid_name(
    client: TestClient,
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
) -> None:
    job = _completed(service, input_store, output_store)
    name = download_filename(job.document_id, DocumentFormat.PDF)
    response = client.get(f"/api/batches/{job.batch_id}/documents/{job.document_id}/download")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/pdf")
    assert response.headers["content-disposition"] == f'attachment; filename="{name}"'
    assert response.headers["cache-control"] == "no-store"
    assert response.content == SYNTHETIC_OUTPUT
    assert "Nguyen" not in response.headers["content-disposition"]


def test_a_findings_review_can_be_downloaded_before_keep_or_delete(
    client: TestClient,
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
) -> None:
    batch = service.create_batch()
    job = verifying_document(service, input_store, output_store, batch.batch_id, _FINDINGS)
    held = verified(service, job, VerificationOutcome.PASSED)
    response = client.get(f"/api/batches/{held.batch_id}/documents/{held.document_id}/download")
    assert response.status_code == 200
    assert response.content == SYNTHETIC_OUTPUT


def test_a_document_without_output_cannot_be_downloaded(
    client: TestClient, service: JobService, input_store: LocalInputStore
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id)
    response = client.get(f"/api/batches/{batch.batch_id}/documents/{job.document_id}/download")
    assert response.status_code == 409
    assert response.json() == {"code": ErrorCode.INTERNAL_ERROR.value}


def test_export_zip_holds_only_completed_outputs_and_the_csv(
    client: TestClient,
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
) -> None:
    done = _completed(service, input_store, output_store)
    hidden = HiddenContentCounts(((HiddenContentCategory.COMMENTS, 2),))
    queued = service.apply(
        service.apply(
            uploaded_document(
                service, input_store, done.batch_id, content=b"%PDF-synthetic second\n"
            ).document_id,
            lambda j, at: j.start_validation(at),
        ).document_id,
        lambda j, at: j.validation_passed(at, hidden),
    )
    held = verifying_document(
        service,
        input_store,
        output_store,
        done.batch_id,
        _FINDINGS,
        output=b"%PDF-synthetic review output\n",
        content=b"%PDF-synthetic review input\n",
    )
    verified(service, held, VerificationOutcome.PASSED)

    response = client.get(f"/api/batches/{done.batch_id}/export")
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"
    expected_zip = zip_filename(done.batch_id)
    assert expected_zip in response.headers["content-disposition"]
    archive = zipfile.ZipFile(io.BytesIO(response.content))
    names = set(archive.namelist())
    completed_name = download_filename(done.document_id, DocumentFormat.PDF)
    assert names == {"report.csv", completed_name}
    assert archive.read(completed_name) == SYNTHETIC_OUTPUT
    leaked = [name for name in names if "input" in name or "work" in name or "Nguyen" in name]
    assert leaked == []
    text = archive.read("report.csv").decode("utf-8")
    rows = list(csv.DictReader(io.StringIO(text)))
    by_id = {row["document_id"]: row for row in rows}
    assert by_id[str(done.document_id)]["status"] == DocumentState.COMPLETED.value
    assert by_id[str(done.document_id)][f"count_{EntityType.EMAIL.value}"] == "1"
    assert by_id[str(queued.document_id)]["status"] == DocumentState.QUEUED.value
    assert by_id[str(queued.document_id)][f"hidden_{HiddenContentCategory.COMMENTS.value}"] == "2"
    assert by_id[str(held.document_id)]["status"] == DocumentState.REVIEW_REQUIRED.value
    assert "filename" not in text
    assert "Nguyen" not in text
    assert list((root.path / "work").iterdir()) == []


def test_export_of_the_wrong_batch_is_not_found(client: TestClient) -> None:
    other = UUID("00000000-0000-4000-8000-000000000099")
    response = client.get(f"/api/batches/{other}/export")
    assert response.status_code == 404
