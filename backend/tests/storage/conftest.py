from pathlib import Path

import pytest

from cv_masking.adapters.local_storage import (
    LocalInputStore,
    LocalOutputStore,
    LocalStorageSweeper,
    LocalWorkArea,
    StorageRoot,
)


@pytest.fixture
def root(tmp_path: Path) -> StorageRoot:
    return StorageRoot.prepare(tmp_path / "cache")


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
