import sqlite3
from pathlib import Path

import pytest

from cv_masking.adapters.local_storage import StorageRoot
from cv_masking.adapters.sqlite import SqliteMetadataStore
from cv_masking.adapters.sqlite.migrations import (
    LATEST_VERSION,
    MIGRATIONS,
    expected_fingerprint,
    schema_fingerprint,
)
from cv_masking.domain.codes import ErrorCode
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
