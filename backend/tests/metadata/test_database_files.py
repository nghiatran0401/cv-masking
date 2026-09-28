import os
import stat
from pathlib import Path
from typing import Any

import pytest
from domain_builders import T0, new_batch_id

from cv_masking.adapters.local_storage import LocalStorageSweeper, StorageRoot
from cv_masking.adapters.sqlite import DATABASE_NAME, SqliteMetadataStore
from cv_masking.domain.batch import Batch
from cv_masking.domain.codes import ErrorCode
from cv_masking.ports.storage import StorageError


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def test_database_lives_in_the_owner_only_metadata_folder(
    root: StorageRoot, store: SqliteMetadataStore
) -> None:
    assert store.path == root.metadata_path / DATABASE_NAME
    assert _mode(root.metadata_path) == 0o700
    assert _mode(store.path) == 0o600


def test_symlinked_database_is_refused(root: StorageRoot, outside: Path) -> None:
    (root.metadata_path / DATABASE_NAME).symlink_to(outside / "keep.txt")
    with pytest.raises(StorageError) as caught:
        SqliteMetadataStore.open(root)
    assert caught.value.code is ErrorCode.STORAGE_PATH_REJECTED
    assert (outside / "keep.txt").read_bytes() == b"synthetic outside file\n"


def test_sweeper_never_touches_the_database(root: StorageRoot, store: SqliteMetadataStore) -> None:
    with store.transaction() as tx:
        tx.add_batch(Batch.create(new_batch_id(), T0))
    os.utime(store.path, (T0.timestamp(), T0.timestamp()))
    LocalStorageSweeper(root).sweep(T0.replace(year=T0.year + 5))
    with store.read() as reader:
        assert len(reader.list_batches()) == 1


def test_a_side_file_unlinked_during_the_check_is_not_an_error(
    root: StorageRoot, store: SqliteMetadataStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The API and the worker thread share the store: a closing connection removes -wal/-shm."""
    side = root.metadata_path / f"{DATABASE_NAME}-wal"
    os.close(os.open(side, os.O_CREAT | os.O_WRONLY, 0o600))
    real_open = os.open

    def racing_open(path: Any, flags: int, mode: int = 0o777, *, dir_fd: int | None = None) -> int:
        fd = real_open(path, flags, mode, dir_fd=dir_fd)
        if isinstance(path, str) and path.endswith("-wal"):
            os.unlink(path, dir_fd=dir_fd)
        return fd

    monkeypatch.setattr(os, "open", racing_open)
    with store.read() as reader:
        assert reader.list_batches() == ()
