"""Document content never reaches the database or the logs, and purge leaves no trace."""

import hashlib
import logging
import re

import pytest
from service_helpers import uploaded_document, verified, verifying_document

from cv_masking.adapters.local_storage import LocalInputStore, LocalOutputStore, StorageRoot
from cv_masking.adapters.sqlite import SqliteMetadataStore
from cv_masking.adapters.sqlite.store import SIDE_FILE_SUFFIXES
from cv_masking.application import JobService
from cv_masking.domain.batch import BatchState
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.verification import VerificationOutcome

MARKERS = (b"Nguyen Van Mau", b"0900000000", b"mau.nguyen@example.test")
CONTENT = b"%PDF-1.7\n% synthetic " + b" ".join(MARKERS) + b"\n"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
ALLOWED_WORDS = (
    {
        "metadata",
        "store",
        "opened",
        "batch",
        "created",
        "started",
        "finished",
        "purged",
        "documents",
        "document",
        "added",
        "to",
        "removed",
        "->",
        "version",
        "storage",
        "reconciled",
        "inputs",
        "outputs",
        "failed",
        # storage adapter lines
        "stored",
        "deleted",
        "object",
    }
    | {state.value for state in DocumentState}
    | {state.value for state in BatchState}
)


def _database_bytes(store: SqliteMetadataStore) -> bytes:
    files = [
        store.path,
        *(store.path.with_name(store.path.name + s) for s in SIDE_FILE_SUFFIXES),
    ]
    return b"".join(path.read_bytes() for path in files if path.exists())


def _lifecycle(
    service: JobService, input_store: LocalInputStore, output_store: LocalOutputStore
) -> list[str]:
    batch = service.create_batch()
    job = uploaded_document(service, input_store, batch.batch_id, content=CONTENT)
    rejected = uploaded_document(service, input_store, batch.batch_id, DocumentFormat.DOCX, CONTENT)
    service.apply(rejected.document_id, lambda j, at: j.start_validation(at))
    service.apply(rejected.document_id, lambda j, at: j.fail(ErrorCode.DOCX_MALFORMED, at))
    review = verified(
        service,
        verifying_document(
            service,
            input_store,
            output_store,
            batch.batch_id,
            frozenset({ReviewReason.DETECT_LOW_CONFIDENCE}),
            output=CONTENT,
        ),
    )
    verified(
        service,
        verifying_document(service, input_store, output_store, batch.batch_id, output=CONTENT),
        VerificationOutcome.FAILED,
        frozenset({ErrorCode.VERIFY_RESIDUAL_FINDING}),
    )
    current = service.get_batch(batch.batch_id)
    service.start_batch(batch.batch_id, expected_version=current.version)
    service.cancel_document(job.document_id)
    service.approve_review(review.document_id, expected_version=review.version)
    service.reconcile_storage()
    return [str(batch.batch_id)]


def test_database_never_holds_document_content(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    store: SqliteMetadataStore,
) -> None:
    _lifecycle(service, input_store, output_store)
    stored = _database_bytes(store)
    digest = hashlib.sha256(CONTENT).hexdigest().encode()
    assert digest in stored
    for marker in (*MARKERS, CONTENT[:16]):
        assert marker not in stored, marker


def test_purge_leaves_no_trace_in_the_database(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    store: SqliteMetadataStore,
    root: StorageRoot,
) -> None:
    (batch_id,) = _lifecycle(service, input_store, output_store)
    digest = hashlib.sha256(CONTENT).hexdigest().encode()
    assert digest in _database_bytes(store)
    service.purge_batch(service.list_batches()[0].batch_id)
    stored = _database_bytes(store)
    assert digest not in stored
    assert batch_id.encode() not in stored
    assert [list((root.path / kind).iterdir()) for kind in ("inputs", "outputs")] == [[], []]


def test_log_lines_contain_only_ids_states_and_counts(
    service: JobService,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    root: StorageRoot,
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level(logging.DEBUG, logger="cv_masking"):
        _lifecycle(service, input_store, output_store)
        service.purge_batch(service.list_batches()[0].batch_id)

    messages = [record.getMessage() for record in caplog.records]
    assert len(messages) >= 10
    digest = hashlib.sha256(CONTENT).hexdigest()
    forbidden = (str(root.path), digest, *(m.decode() for m in MARKERS))
    for message in messages:
        assert not any(fragment in message for fragment in forbidden), message
        for token in re.split(r"[\s=]+", UUID_RE.sub("", message)):
            assert token == "" or token.isdigit() or token in ALLOWED_WORDS, (token, message)
