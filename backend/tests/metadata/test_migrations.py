import sqlite3
from pathlib import Path
from uuid import UUID

import pytest

from cv_masking.adapters.local_storage import StorageRoot
from cv_masking.adapters.sqlite import SqliteMetadataStore
from cv_masking.adapters.sqlite.migrations import _BOOTSTRAP as MIGRATIONS_BOOTSTRAP
from cv_masking.adapters.sqlite.migrations import (
    LATEST_VERSION,
    MIGRATIONS,
    expected_fingerprint,
    schema_fingerprint,
)
from cv_masking.domain.codes import ErrorCode, ReviewReason
from cv_masking.domain.document_job import DocumentState
from cv_masking.domain.ids import DocumentId
from cv_masking.ports.storage import StorageError

MIGRATION_1_CHECKSUM = "14b89c74ee6671c57855b43bc46dc4413ee7c58215a7b6a16efa507fdb6208c7"


def _raw(path: Path) -> sqlite3.Connection:
    return sqlite3.connect(path, isolation_level=None)


def _refused(root: StorageRoot) -> None:
    with pytest.raises(StorageError) as caught:
        SqliteMetadataStore.open(root)
    assert caught.value.code is ErrorCode.STORAGE_INTEGRITY_FAILED


def test_new_database_is_migrated_to_the_latest_version(store: SqliteMetadataStore) -> None:
    conn = _raw(store.path)
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == LATEST_VERSION
        assert schema_fingerprint(conn) == expected_fingerprint()
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_released_migrations_are_never_edited() -> None:
    assert [m.version for m in MIGRATIONS] == list(range(1, LATEST_VERSION + 1))
    assert MIGRATIONS[0].checksum == MIGRATION_1_CHECKSUM


@pytest.mark.parametrize(
    "statement",
    [
        f"PRAGMA user_version = {LATEST_VERSION + 1}",
        "UPDATE schema_migrations SET checksum = '" + "0" * 64 + "'",
        "CREATE TABLE extra (note TEXT) STRICT",
    ],
    ids=["newer-version", "edited-checksum", "extra-table"],
)
def test_unexpected_schema_is_refused(
    root: StorageRoot, store: SqliteMetadataStore, statement: str
) -> None:
    conn = _raw(store.path)
    conn.execute(statement)
    conn.close()
    _refused(root)


def test_foreign_database_is_never_adopted(root: StorageRoot) -> None:
    path = root.metadata_path / "jobs.sqlite3"
    conn = _raw(path)
    conn.execute("CREATE TABLE other_app (id INTEGER PRIMARY KEY)")
    conn.close()
    path.chmod(0o600)
    _refused(root)
    conn = _raw(path)
    try:
        tables = [row[0] for row in conn.execute("SELECT name FROM sqlite_schema")]
    finally:
        conn.close()
    assert tables == ["other_app"]


_BATCH = "00000000-0000-4000-8000-00000000000b"
_HIDDEN_HELD = "00000000-0000-4000-8000-0000000000d1"
_BLOCKED = "00000000-0000-4000-8000-0000000000d2"


def _version_1_database(path: Path) -> None:
    """A Stage 11 database: one document held for hidden-content approval, one blocked."""
    conn = _raw(path)
    try:
        conn.execute("BEGIN")
        conn.execute(MIGRATIONS_BOOTSTRAP)
        for statement in MIGRATIONS[0].statements:
            conn.execute(statement)
        conn.execute(
            "INSERT INTO schema_migrations (version, checksum) VALUES (1, ?)",
            (MIGRATION_1_CHECKSUM,),
        )
        conn.execute("INSERT INTO batches VALUES (?, 'running', 1, 2, 0, 1, 1)", (_BATCH,))
        for index, (document_id, reason) in enumerate(
            ((_HIDDEN_HELD, "PDF_HIDDEN_CONTENT"), (_BLOCKED, "PDF_ENCRYPTED")), start=1
        ):
            conn.execute(
                "INSERT INTO documents (document_id, batch_id, state, created_at, updated_at,"
                " version, document_format, input_ref, content_sha256, size_bytes, uploaded_at,"
                " attempt, hidden_content_approved, findings_review_approved,"
                " finding_counts_recorded)"
                " VALUES (?, ?, 'review_required', 0, 1, 3, 'pdf', ?, ?, 10, 0, 1, 0, 0, 0)",
                (document_id, _BATCH, f"00000000-0000-4000-8000-00000000001{index}", "a" * 64),
            )
            conn.execute("INSERT INTO document_review_reasons VALUES (?, ?)", (document_id, reason))
        conn.execute("PRAGMA user_version = 1")
        conn.execute("COMMIT")
    finally:
        conn.close()
    path.chmod(0o600)


def test_version_1_is_upgraded_and_hidden_content_holds_are_failed(root: StorageRoot) -> None:
    _version_1_database(root.metadata_path / "jobs.sqlite3")
    with SqliteMetadataStore.open(root).read() as reader:
        held = reader.get_document(DocumentId(UUID(_HIDDEN_HELD)))
        blocked = reader.get_document(DocumentId(UUID(_BLOCKED)))
    assert held.state is DocumentState.FAILED
    assert held.error_code is ErrorCode.JOB_INTERRUPTED
    assert held.review_reasons == frozenset()
    assert held.version == 4
    assert blocked.state is DocumentState.REVIEW_REQUIRED
    assert blocked.review_reasons == frozenset({ReviewReason.PDF_ENCRYPTED})
    assert blocked.hidden_removed.items == ()
