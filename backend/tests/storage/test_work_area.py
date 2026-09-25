import stat
from pathlib import Path

import pytest

from cv_masking.adapters.local_storage import LocalWorkArea, StorageRoot
from cv_masking.domain.codes import ErrorCode
from cv_masking.ports.storage import StorageError


def _work_entries(root: StorageRoot) -> list[str]:
    return [path.name for path in (root.path / "work").iterdir()]


def _fail_inside(work_area: LocalWorkArea) -> None:
    with work_area.attempt() as directory:
        (directory / "part.bin").write_bytes(b"synthetic work data")
        raise RuntimeError("synthetic failure")


def _swap_for_symlink(work_area: LocalWorkArea, target: Path) -> None:
    with work_area.attempt() as directory:
        directory.rmdir()
        directory.symlink_to(target)


def test_attempt_gives_a_private_directory_and_always_removes_it(
    work_area: LocalWorkArea, root: StorageRoot
) -> None:
    with work_area.attempt() as directory:
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        (directory / "part.bin").write_bytes(b"synthetic work data")
    assert _work_entries(root) == []
    with pytest.raises(RuntimeError, match="synthetic failure"):
        _fail_inside(work_area)
    assert _work_entries(root) == []


def test_cleanup_does_not_follow_symlinks_out_of_the_work_area(
    work_area: LocalWorkArea, outside: Path
) -> None:
    with work_area.attempt() as directory:
        (directory / "escape").symlink_to(outside)
    assert (outside / "keep.txt").read_bytes() == b"synthetic outside file\n"


def test_swapped_work_directory_fails_closed_and_outside_is_untouched(
    work_area: LocalWorkArea, outside: Path
) -> None:
    with pytest.raises(StorageError) as caught:
        _swap_for_symlink(work_area, outside)
    assert caught.value.code is ErrorCode.STORAGE_WRITE_FAILED
    assert (outside / "keep.txt").exists()
