import logging
import os
import stat
from pathlib import Path

import pytest

from cv_masking.adapters.local_storage import StorageRoot, StoreKind, default_storage_root
from cv_masking.adapters.local_storage.root import ROOT_MARKER, SPOTLIGHT_MARKER
from cv_masking.domain.codes import ErrorCode
from cv_masking.ports.storage import StorageError


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.lstat().st_mode)


def _rejected(path: object) -> None:
    with pytest.raises(StorageError) as caught:
        StorageRoot.prepare(path)  # type: ignore[arg-type]
    assert caught.value.code is ErrorCode.STORAGE_PATH_REJECTED


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_default_root_is_the_project_data_folder() -> None:
    assert default_storage_root() == PROJECT_ROOT / "data"


@pytest.mark.parametrize("ignore_file", [".gitignore", ".cursorignore"])
def test_default_root_is_ignored_by_git_and_cursor(ignore_file: str) -> None:
    lines = (PROJECT_ROOT / ignore_file).read_text(encoding="utf-8").splitlines()
    assert f"{default_storage_root().name}/" in lines


def test_prepare_creates_an_owner_only_layout(tmp_path: Path) -> None:
    root = StorageRoot.prepare(tmp_path / "cache")
    assert root.path == Path(os.path.realpath(tmp_path)) / "cache"
    assert _mode(root.path) == 0o700
    for kind in StoreKind:
        assert _mode(root.path / kind.value) == 0o700
    for marker in (ROOT_MARKER, SPOTLIGHT_MARKER):
        assert _mode(root.path / marker) == 0o600
    assert sorted(p.name for p in root.path.iterdir()) == sorted(
        [ROOT_MARKER, SPOTLIGHT_MARKER, *(k.value for k in StoreKind)]
    )


def test_prepare_is_idempotent(tmp_path: Path) -> None:
    first = StorageRoot.prepare(tmp_path / "cache")
    (first.path / "inputs" / "keep").write_bytes(b"synthetic")
    second = StorageRoot.prepare(tmp_path / "cache")
    assert second.path == first.path
    assert (second.path / "inputs" / "keep").exists()


def test_empty_existing_directory_is_adopted(tmp_path: Path) -> None:
    (tmp_path / "cache").mkdir(mode=0o700)
    root = StorageRoot.prepare(tmp_path / "cache")
    assert (root.path / ROOT_MARKER).is_file()


def test_non_empty_directory_without_marker_is_refused(tmp_path: Path) -> None:
    existing = tmp_path / "Documents"
    existing.mkdir()
    (existing / "inputs").mkdir()
    (existing / "inputs" / "synthetic-note.txt").write_bytes(b"synthetic")
    _rejected(existing)
    assert sorted(p.name for p in existing.iterdir()) == ["inputs"]
    assert (existing / "inputs" / "synthetic-note.txt").read_bytes() == b"synthetic"


@pytest.mark.parametrize(
    "path",
    [Path("relative/cache"), Path("/"), "/nonexistent-parent/cache", None],
    ids=["relative", "filesystem-root", "string", "none"],
)
def test_invalid_root_paths_are_refused(path: object) -> None:
    _rejected(path)


def test_missing_parent_is_refused(tmp_path: Path) -> None:
    _rejected(tmp_path / "missing" / "cache")
    assert not (tmp_path / "missing").exists()


def test_symlinked_root_is_refused(tmp_path: Path, outside: Path) -> None:
    (tmp_path / "cache").symlink_to(outside)
    _rejected(tmp_path / "cache")
    assert sorted(p.name for p in outside.iterdir()) == ["keep.txt"]


def test_file_at_root_is_refused(tmp_path: Path) -> None:
    (tmp_path / "cache").write_bytes(b"synthetic")
    _rejected(tmp_path / "cache")


def test_root_inside_a_project_checkout_is_allowed(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / ".git").mkdir(parents=True)
    root = StorageRoot.prepare(project / "data")
    assert (root.path / ROOT_MARKER).is_file()


def test_root_owned_by_another_user_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "cache").mkdir(mode=0o700)
    real_uid = os.getuid()
    monkeypatch.setattr(os, "getuid", lambda: real_uid + 1)
    _rejected(tmp_path / "cache")


def test_loose_root_permissions_are_tightened(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    StorageRoot.prepare(tmp_path / "cache")
    (tmp_path / "cache").chmod(0o755)
    (tmp_path / "cache" / "outputs").chmod(0o750)
    with caplog.at_level(logging.WARNING, logger="cv_masking.storage"):
        root = StorageRoot.prepare(tmp_path / "cache")
    assert _mode(root.path) == 0o700
    assert _mode(root.path / "outputs") == 0o700
    assert len(caplog.records) == 2
    assert all(str(tmp_path) not in r.getMessage() for r in caplog.records)


def test_symlinked_kind_directory_is_refused(tmp_path: Path, outside: Path) -> None:
    root = StorageRoot.prepare(tmp_path / "cache")
    (root.path / "inputs").rmdir()
    (root.path / "inputs").symlink_to(outside)
    _rejected(tmp_path / "cache")
    with pytest.raises(StorageError) as caught, root.open_kind(StoreKind.INPUTS):
        pass
    assert caught.value.code is ErrorCode.STORAGE_PATH_REJECTED


def test_kind_directory_loosened_after_prepare_is_refused_on_use(root: StorageRoot) -> None:
    (root.path / "work").chmod(0o770)
    with pytest.raises(StorageError), root.open_kind(StoreKind.WORK):
        pass


def test_missing_kind_directory_is_refused_on_use(root: StorageRoot) -> None:
    (root.path / "outputs").rmdir()
    with pytest.raises(StorageError), root.open_kind(StoreKind.OUTPUTS):
        pass


def test_marker_that_is_not_a_file_is_refused(tmp_path: Path) -> None:
    (tmp_path / "cache").mkdir()
    (tmp_path / "cache" / ROOT_MARKER).mkdir()
    _rejected(tmp_path / "cache")
