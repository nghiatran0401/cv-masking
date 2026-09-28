import os
from datetime import timedelta

import pytest
from service_helpers import (
    SYNTHETIC_INPUT,
    ManualClock,
    queued_document,
    uploaded_document,
    verified,
    verifying_document,
)

from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.application import ORPHAN_GRACE, JobService, ReconcileReport
from cv_masking.domain.batch import BatchState
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.errors import InvalidTransitionError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.verification import VerificationOutcome
from cv_masking.ports.metadata import RecordNotFoundError
from cv_masking.ports.storage import StorageError


def _objects(root: StorageRoot, kind: str) -> list[str]:
    return sorted(path.name for path in (root.path / kind).iterdir())


def _failing_delete(self: LocalInputStore, ref: object, fmt: object) -> bool:
    raise StorageError(ErrorCode.STORAGE_WRITE_FAILED)


def test_full_lifecycle_finishes_the_batch_and_keeps_only_the_output(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
) -> None:
    batch = service.create_batch()
    job = queued_document(service, input_store, batch.batch_id)
    pending = verifying_document(service, input_store, output_store, batch.batch_id)
    batch = service.get_batch(batch.batch_id)
    service.start_batch(batch.batch_id, expected_version=batch.version)
    done = verified(service, pending)
    assert service.get_batch(batch.batch_id).state is BatchState.RUNNING
    service.cancel_document(job.document_id)
    assert done.state is DocumentState.COMPLETED
    assert service.get_batch(batch.batch_id).state is BatchState.FINISHED
    assert _objects(root, "inputs") == []
    assert _objects(root, "outputs") == [f"{done.output_ref}.pdf"]


def test_failed_verification_keeps_residual_output_for_inspection(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
) -> None:
    batch = service.create_batch()
    job = verifying_document(service, input_store, output_store, batch.batch_id)
    failed = verified(
        service, job, VerificationOutcome.FAILED, frozenset({ErrorCode.VERIFY_RESIDUAL_FINDING})
    )
    assert _objects(root, "outputs") == [f"{failed.output_ref}.pdf"]
    assert _objects(root, "inputs") == []


def test_invalid_output_is_deleted(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
) -> None:
    batch = service.create_batch()
    job = verifying_document(service, input_store, output_store, batch.batch_id)
    verified(service, job, VerificationOutcome.FAILED, frozenset({ErrorCode.VERIFY_OUTPUT_INVALID}))
    assert _objects(root, "outputs") == []
    assert _objects(root, "inputs") == []


def test_interrupt_deletes_the_abandoned_output_and_input(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
) -> None:
    batch = service.create_batch()
    job = verifying_document(service, input_store, output_store, batch.batch_id)
    service.apply(job.document_id, lambda j, at: j.interrupt(at))
    assert _objects(root, "outputs") == []
    assert _objects(root, "inputs") == []


def test_file_deletion_failure_after_commit_is_left_to_reconcile(
    service: JobService,
    input_store: LocalInputStore,
    root: StorageRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id)
    monkeypatch.setattr(LocalInputStore, "delete", _failing_delete)
    assert service.cancel_document(job.document_id).state is DocumentState.CANCELLED
    assert len(_objects(root, "inputs")) == 1
    monkeypatch.undo()
    assert service.reconcile_storage() == ReconcileReport(removed_inputs=1)
    assert _objects(root, "inputs") == []


def test_remove_document_only_while_the_batch_is_open(
    service: JobService, input_store: LocalInputStore, root: StorageRoot
) -> None:
    batch = service.create_batch()
    removed = uploaded_document(service, input_store, batch.batch_id)
    kept = uploaded_document(service, input_store, batch.batch_id)
    service.remove_document(removed.document_id)
    assert _objects(root, "inputs") == [f"{kept.input_ref}.pdf"]
    batch = service.get_batch(batch.batch_id)
    service.start_batch(batch.batch_id, expected_version=batch.version)
    with pytest.raises(InvalidTransitionError):
        service.remove_document(kept.document_id)
    assert _objects(root, "inputs") == [f"{kept.input_ref}.pdf"]


def test_replace_failed_reopens_the_batch_and_keeps_the_count(
    service: JobService, input_store: LocalInputStore
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id)
    batch = service.get_batch(batch.batch_id)
    service.start_batch(batch.batch_id, expected_version=batch.version)
    service.apply(job.document_id, lambda current, at: current.start_validation(at))
    service.apply(job.document_id, lambda current, at: current.fail(ErrorCode.INTERNAL_ERROR, at))
    assert service.get_batch(batch.batch_id).state is BatchState.FINISHED
    stored = input_store.save_stream(DocumentFormat.PDF, [SYNTHETIC_INPUT], max_bytes=1_000_000)
    replacement = service.replace_failed_with_upload(job.document_id, stored)
    assert replacement.document_id != job.document_id
    assert replacement.state is DocumentState.UPLOADED
    current = service.get_batch(batch.batch_id)
    assert current.state is BatchState.RUNNING
    assert current.document_count == 1
    with pytest.raises(RecordNotFoundError):
        service.get_document(job.document_id)


def test_purge_deletes_every_file_and_row_of_that_batch_only(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
) -> None:
    batch = service.create_batch()
    keep = service.create_batch()
    kept = uploaded_document(service, input_store, keep.batch_id)
    uploaded_document(service, input_store, batch.batch_id, DocumentFormat.DOCX)
    verified(service, verifying_document(service, input_store, output_store, batch.batch_id))
    service.purge_batch(batch.batch_id)
    with pytest.raises(RecordNotFoundError):
        service.get_batch(batch.batch_id)
    assert _objects(root, "outputs") == []
    assert _objects(root, "inputs") == [f"{kept.input_ref}.pdf"]


def test_purge_fails_closed_when_a_file_cannot_be_deleted(
    service: JobService,
    input_store: LocalInputStore,
    root: StorageRoot,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id)
    monkeypatch.setattr(LocalInputStore, "delete", _failing_delete)
    with pytest.raises(StorageError):
        service.purge_batch(batch.batch_id)
    assert service.get_document(job.document_id) == job
    monkeypatch.undo()
    service.purge_batch(batch.batch_id)
    assert _objects(root, "inputs") == []


def test_reconcile_removes_old_unreferenced_files_only(
    service: JobService, input_store: LocalInputStore, root: StorageRoot, clock: ManualClock
) -> None:
    batch = service.create_batch()
    needed = queued_document(service, input_store, batch.batch_id)
    input_store.save_stream(DocumentFormat.PDF, [b"synthetic orphan"], max_bytes=100)
    stamp = (clock.now() - ORPHAN_GRACE - timedelta(seconds=1)).timestamp()
    for path in (root.path / "inputs").iterdir():
        os.utime(path, (stamp, stamp))
    young = input_store.save_stream(DocumentFormat.DOCX, [b"synthetic young orphan"], max_bytes=100)
    assert service.reconcile_storage() == ReconcileReport(removed_inputs=1)
    assert _objects(root, "inputs") == sorted([f"{needed.input_ref}.pdf", f"{young.ref}.docx"])
