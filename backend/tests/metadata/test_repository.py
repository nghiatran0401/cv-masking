import sqlite3

import pytest
from domain_builders import (
    T0,
    completed,
    findings_review,
    job_in_state,
    later,
    rebuild,
    verification_for,
    verifying,
)

from cv_masking.adapters.sqlite import SqliteMetadataStore
from cv_masking.domain.batch import Batch
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.document_job import DocumentJob, DocumentState
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import DocumentId
from cv_masking.domain.policy import MaskingPolicy
from cv_masking.domain.verification import VerificationOutcome
from cv_masking.ports.metadata import ConcurrentUpdateError
from cv_masking.ports.storage import StorageError


def _save(store: SqliteMetadataStore, job: DocumentJob) -> None:
    with store.transaction() as tx:
        tx.add_batch(Batch.create(job.batch_id, job.created_at).add_document(job.created_at))
        tx.add_document(job)


def _load(store: SqliteMetadataStore, document_id: DocumentId) -> DocumentJob:
    with store.read() as reader:
        return reader.get_document(document_id)


@pytest.mark.parametrize("state", list(DocumentState))
def test_every_state_round_trips(store: SqliteMetadataStore, state: DocumentState) -> None:
    job = job_in_state(state, DocumentFormat.DOCX)
    _save(store, job)
    assert _load(store, job.document_id) == job


def test_stale_update_is_a_conflict_and_changes_nothing(store: SqliteMetadataStore) -> None:
    job = job_in_state(DocumentState.QUEUED)
    _save(store, job)
    first = job.start_processing(MaskingPolicy(), later(job))
    with store.transaction() as tx:
        tx.update_document(first, expected_version=job.version)
    with pytest.raises(ConcurrentUpdateError), store.transaction() as tx:
        tx.update_document(job.cancel(later(job)), expected_version=job.version)
    assert _load(store, job.document_id) == first


def test_a_failed_transaction_writes_nothing(store: SqliteMetadataStore) -> None:
    job = job_in_state(DocumentState.UPLOADED)

    def save_then_fail() -> None:
        with store.transaction() as tx:
            tx.add_batch(Batch.create(job.batch_id, T0).add_document(T0))
            tx.add_document(job)
            raise RuntimeError("synthetic failure")

    with pytest.raises(RuntimeError, match="synthetic"):
        save_then_fail()
    with store.read() as reader:
        assert reader.list_batches() == ()


def test_deleting_a_batch_removes_every_row_about_it(
    store: SqliteMetadataStore, raw: sqlite3.Connection
) -> None:
    job = findings_review()
    _save(store, job)
    with store.transaction() as tx:
        tx.delete_batch(job.batch_id)
    for table in (
        "batches",
        "documents",
        "document_finding_counts",
        "document_review_reasons",
        "document_verification_failures",
    ):
        assert raw.execute(f"SELECT count(*) FROM {table}").fetchone()[0] == 0  # noqa: S608


def test_object_uses_say_which_files_are_still_needed(store: SqliteMetadataStore) -> None:
    queued = job_in_state(DocumentState.QUEUED)
    done = rebuild(completed(), batch_id=queued.batch_id)
    job = verifying()
    failed = rebuild(
        job.record_verification(
            verification_for(
                job, VerificationOutcome.FAILED, frozenset({ErrorCode.VERIFY_RESIDUAL_FINDING})
            ),
            later(job),
        ),
        batch_id=queued.batch_id,
    )
    with store.transaction() as tx:
        tx.add_batch(Batch.create(queued.batch_id, T0))
        for document in (queued, done, failed):
            tx.add_document(document)
    with store.read() as reader:
        inputs = {use.ref: use.needed for use in reader.input_uses()}
        outputs = {use.ref: use.needed for use in reader.output_uses()}
    assert inputs == {queued.input_ref: True, done.input_ref: False, failed.input_ref: False}
    assert outputs == {done.output_ref: True, failed.output_ref: False}


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE documents SET state = 'bogus_state'",
        "UPDATE documents SET state = 'uploaded'",
        "UPDATE documents SET error_code = 'NOT_A_REAL_CODE'",
        "UPDATE documents SET updated_at = created_at",
    ],
    ids=["unknown-state", "impossible-state", "unknown-code", "time-travel"],
)
def test_tampered_rows_fail_closed(
    store: SqliteMetadataStore, raw: sqlite3.Connection, sql: str
) -> None:
    job = completed()
    _save(store, job)
    raw.execute(sql)
    with pytest.raises(StorageError) as caught:
        _load(store, job.document_id)
    assert caught.value.code is ErrorCode.STORAGE_INTEGRITY_FAILED
