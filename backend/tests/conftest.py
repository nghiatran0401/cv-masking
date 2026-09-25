import sqlite3
from collections.abc import Iterator
from pathlib import Path

import pytest
from service_helpers import ManualClock

from cv_masking.adapters.local_storage import (
    LocalInputStore,
    LocalOutputStore,
    LocalStorageSweeper,
    LocalWorkArea,
    StorageRoot,
)
from cv_masking.adapters.sqlite import SqliteMetadataStore
from cv_masking.application import JobService


@pytest.fixture
def root(tmp_path: Path) -> StorageRoot:
    return StorageRoot.prepare(tmp_path / "data")


@pytest.fixture
def input_store(root: StorageRoot) -> LocalInputStore:
    return LocalInputStore(root)


@pytest.fixture
def output_store(root: StorageRoot) -> LocalOutputStore:
    return LocalOutputStore(root)


@pytest.fixture
def work_area(root: StorageRoot) -> LocalWorkArea:
    return LocalWorkArea(root)


@pytest.fixture
def sweeper(root: StorageRoot) -> LocalStorageSweeper:
    return LocalStorageSweeper(root)


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory outside the storage root holding a file that must never be touched."""
    directory = tmp_path / "outside"
    directory.mkdir()
    (directory / "keep.txt").write_bytes(b"synthetic outside file\n")
    (directory / "keep.txt").chmod(0o600)
    return directory


@pytest.fixture
def store(root: StorageRoot) -> SqliteMetadataStore:
    return SqliteMetadataStore.open(root)


@pytest.fixture
def raw(store: SqliteMetadataStore) -> Iterator[sqlite3.Connection]:
    """A plain connection that bypasses the store, to inspect or tamper with the file."""
    conn = sqlite3.connect(store.path, isolation_level=None)
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
    finally:
        conn.close()


@pytest.fixture
def clock() -> ManualClock:
    return ManualClock()


@pytest.fixture
def service(
    store: SqliteMetadataStore,
    input_store: LocalInputStore,
    output_store: LocalOutputStore,
    clock: ManualClock,
) -> JobService:
    return JobService(store, input_store, output_store, clock)
