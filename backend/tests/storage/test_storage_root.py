import logging
import os
import stat
from pathlib import Path

import pytest

from cv_masking.adapters.local_storage import (
    LOGS_DIR,
    METADATA_DIR,
    StorageRoot,
    StoreKind,
    default_storage_root,
)
from cv_masking.adapters.local_storage.root import ROOT_MARKER, SPOTLIGHT_MARKER
from cv_masking.domain.codes import ErrorCode
from cv_masking.ports.storage import StorageError

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _rejected(path: Path) -> None:
    with pytest.raises(StorageError) as caught:
        StorageRoot.prepare(path)
    assert caught.value.code is ErrorCode.STORAGE_PATH_REJECTED


def test_default_root_is_the_ignored_project_data_folder() -> None:
    assert default_storage_root() == PROJECT_ROOT / "data"
    for ignore_file in (".gitignore", ".cursorignore"):
        lines = (PROJECT_ROOT / ignore_file).read_text(encoding="utf-8").splitlines()
        assert "data/" in lines, ignore_file


def test_prepare_creates_an_owner_only_layout(tmp_path: Path) -> None:
    root = StorageRoot.prepare(tmp_path / "data")
    directories = (*(kind.value for kind in StoreKind), METADATA_DIR, LOGS_DIR)
    assert _mode(root.path) == 0o700
    for directory in directories:
        assert _mode(root.path / directory) == 0o700
    assert sorted(p.name for p in root.path.iterdir()) == sorted(
        [ROOT_MARKER, SPOTLIGHT_MARKER, *directories]
    )


def test_non_empty_directory_without_marker_is_refused(tmp_path: Path) -> None:
    existing = tmp_path / "Documents"
    (existing / "inputs").mkdir(parents=True)
    (existing / "inputs" / "synthetic-note.txt").write_bytes(b"synthetic")
    _rejected(existing)
    assert sorted(p.name for p in existing.iterdir()) == ["inputs"]


def test_symlinked_root_or_kind_directory_is_refused(tmp_path: Path, outside: Path) -> None:
    (tmp_path / "linked").symlink_to(outside)
    _rejected(tmp_path / "linked")
    root = StorageRoot.prepare(tmp_path / "data")
    (root.path / "inputs").rmdir()
    (root.path / "inputs").symlink_to(outside)
    with pytest.raises(StorageError), root.open_kind(StoreKind.INPUTS):
        pass
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]


def test_root_owned_by_another_user_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "data").mkdir(mode=0o700)
    real_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real_uid + 1)
    _rejected(tmp_path / "data")


def test_loose_permissions_are_tightened_without_logging_paths(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    StorageRoot.prepare(tmp_path / "data")
    (tmp_path / "data").chmod(0o755)
    with caplog.at_level(logging.WARNING, logger="cv_masking.storage"):
        root = StorageRoot.prepare(tmp_path / "data")
    assert _mode(root.path) == 0o700
    assert caplog.records
    assert all(str(tmp_path) not in r.getMessage() for r in caplog.records)
