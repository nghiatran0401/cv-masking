from pathlib import Path

import pytest

from cv_masking.adapters.local_storage import (
    CacheRoot,
    LocalInputStore,
    LocalOutputStore,
    LocalStorageSweeper,
    LocalWorkArea,
)


@pytest.fixture
def root(tmp_path: Path) -> CacheRoot:
    return CacheRoot.prepare(tmp_path / "cache")


@pytest.fixture
def input_store(root: CacheRoot) -> LocalInputStore:
    return LocalInputStore(root)


@pytest.fixture
def output_store(root: CacheRoot) -> LocalOutputStore:
    return LocalOutputStore(root)


@pytest.fixture
def work_area(root: CacheRoot) -> LocalWorkArea:
    return LocalWorkArea(root)


@pytest.fixture
def sweeper(root: CacheRoot) -> LocalStorageSweeper:
    return LocalStorageSweeper(root)


@pytest.fixture
def outside(tmp_path: Path) -> Path:
    """A directory outside the cache root holding a file that must never be touched."""
    directory = tmp_path / "outside"
    directory.mkdir()
    (directory / "keep.txt").write_bytes(b"synthetic outside file\n")
    (directory / "keep.txt").chmod(0o600)
    return directory
