"""Stage 12: cancel, approve (keep), and deny (delete) endpoints, and the safe document view."""

from pathlib import Path
from typing import Any

import pytest
from domain_builders import COUNTS
from fastapi.testclient import TestClient
from service_helpers import SYNTHETIC_INPUT, uploaded_document, verified, verifying_document

from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.application import JobService
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentJob
from cv_masking.domain.hidden import HiddenContentCategory, HiddenContentCounts
from cv_masking.domain.verification import VerificationOutcome

_FINDINGS = frozenset({ReviewReason.DETECT_LOW_CONFIDENCE})


def _url(job: DocumentJob, action: str) -> str:
    return f"/api/batches/{job.batch_id}/documents/{job.document_id}/{action}"


def _post(client: TestClient, job: DocumentJob, action: str, version: int | None = None) -> Any:
    return client.post(_url(job, action), json={"expected_version": version or job.version})


def _held(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    outcome: VerificationOutcome = VerificationOutcome.PASSED,
) -> DocumentJob:
    batch = service.create_batch()
    job = verifying_document(service, input_store, output_store, batch.batch_id, _FINDINGS)
    return verified(service, job, outcome)


def _objects(root: StorageRoot, kind: str) -> list[Path]:
    return sorted((root.path / kind).iterdir())


def test_approve_keeps_a_verified_findings_review(
    client: TestClient,
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
) -> None:
    job = _held(service, input_store, output_store)
    view = client.get(f"/api/batches/{job.batch_id}").json()["documents"][0]
    assert view["state"] == "review_required"
    assert view["can_approve"] is True
    assert view["review_reasons"] == ["DETECT_LOW_CONFIDENCE"]
    response = _post(client, job, "approve")
    assert response.status_code == 200
    body = response.json()
    assert body["state"] == "completed"
    assert body["can_approve"] is False
    assert body["finding_counts"] == {t.value: n for t, n in COUNTS.items}
    assert len(_objects(root, "outputs")) == 1


def test_deny_deletes_the_output(
    client: TestClient,
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
) -> None:
    job = _held(service, input_store, output_store)
    response = _post(client, job, "deny")
    assert response.status_code == 200
    assert response.json()["state"] == "rejected"
    assert _objects(root, "outputs") == []
    assert _objects(root, "inputs") == []


def test_a_verifier_review_cannot_be_approved_only_denied(
    client: TestClient,
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
) -> None:
    job = _held(service, input_store, output_store, VerificationOutcome.REVIEW_REQUIRED)
    view = client.get(f"/api/batches/{job.batch_id}").json()["documents"][0]
    assert view["can_approve"] is False
    refused = _post(client, job, "approve")
    assert refused.status_code == 409
    assert refused.json() == {"code": ErrorCode.INTERNAL_ERROR.value}
    assert _post(client, job, "deny").json()["state"] == "rejected"


def test_cancel_applies_to_waiting_documents_only(
    client: TestClient, service: JobService, input_store: LocalInputStore
) -> None:
    batch = service.create_batch()
    waiting = uploaded_document(service, input_store, batch.batch_id)
    held = uploaded_document(service, input_store, batch.batch_id, content=SYNTHETIC_INPUT + b"2")
    held = service.apply(held.document_id, lambda j, at: j.start_validation(at))
    cancelled = _post(client, waiting, "cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["state"] == "cancelled"
    assert cancelled.json()["error_code"] == ErrorCode.JOB_CANCELLED.value
    assert _post(client, held, "cancel").status_code == 409


@pytest.mark.parametrize("action", ["cancel", "approve", "deny"])
def test_actions_check_the_version_and_the_batch(
    client: TestClient,
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    action: str,
) -> None:
    job = (
        uploaded_document(service, input_store, service.create_batch().batch_id)
        if action == "cancel"
        else _held(service, input_store, output_store)
    )
    assert _post(client, job, action, job.version + 5).status_code == 409
    other = service.create_batch()
    wrong_batch = client.post(
        f"/api/batches/{other.batch_id}/documents/{job.document_id}/{action}",
        json={"expected_version": job.version},
    )
    assert wrong_batch.status_code == 404
    assert service.get_document(job.document_id) == job


def test_the_document_view_holds_codes_and_counts_only(
    client: TestClient,
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id)
    job = service.apply(job.document_id, lambda j, at: j.start_validation(at))
    hidden = HiddenContentCounts(((HiddenContentCategory.ANNOTATIONS, 2),))
    service.apply(job.document_id, lambda j, at: j.validation_passed(at, hidden))
    view = client.get(f"/api/batches/{batch.batch_id}").json()["documents"][0]
    assert view["hidden_removed"] == {"annotations": 2}
    assert set(view) == {
        "document_id",
        "batch_id",
        "state",
        "document_format",
        "size_bytes",
        "attempt",
        "error_code",
        "review_reasons",
        "can_approve",
        "has_output",
        "finding_counts",
        "residual_counts",
        "residual_pages",
        "hidden_removed",
        "version",
    }
