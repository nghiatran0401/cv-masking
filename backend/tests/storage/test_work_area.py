import logging
import stat
from pathlib import Path

import pytest

from cv_masking.adapters.local_storage import CacheRoot, LocalWorkArea
from cv_masking.adapters.local_storage.root import WORK_NAME_RE
from cv_masking.domain.codes import ErrorCode
from cv_masking.ports.storage import StorageError


def _work_entries(root: CacheRoot) -> list[str]:
    return [path.name for path in (root.path / "work").iterdir()]


def _fail_inside(work_area: LocalWorkArea) -> None:
    with work_area.attempt() as directory:
        (directory / "part.bin").write_bytes(b"synthetic work data")
        raise RuntimeError("synthetic failure")


def _swap_for_symlink(work_area: LocalWorkArea, target: Path, *, then_fail: bool) -> None:
    with work_area.attempt() as directory:
        directory.rmdir()
        directory.symlink_to(target)
        if then_fail:
            raise RuntimeError("synthetic failure")


def test_attempt_gives_a_fresh_private_directory_and_removes_it(
    work_area: LocalWorkArea, root: CacheRoot
) -> None:
    with work_area.attempt() as directory:
        assert directory.parent == root.path / "work"
        assert WORK_NAME_RE.fullmatch(directory.name)
        assert stat.S_IMODE(directory.stat().st_mode) == 0o700
        (directory / "nested").mkdir()
        (directory / "nested" / "part.bin").write_bytes(b"synthetic work data")
    assert not directory.exists()
    assert _work_entries(root) == []


def test_attempts_are_isolated(work_area: LocalWorkArea) -> None:
    with work_area.attempt() as first, work_area.attempt() as second:
        assert first != second


def test_directory_is_removed_when_the_attempt_fails(
    work_area: LocalWorkArea, root: CacheRoot
) -> None:
    with pytest.raises(RuntimeError, match="synthetic failure"):
        _fail_inside(work_area)
    assert _work_entries(root) == []


def test_cleanup_does_not_follow_symlinks_out_of_the_work_area(
    work_area: LocalWorkArea, outside: Path
) -> None:
    with work_area.attempt() as directory:
        (directory / "escape").symlink_to(outside)
        (directory / "escape-file").symlink_to(outside / "keep.txt")
    assert (outside / "keep.txt").read_bytes() == b"synthetic outside file\n"


def test_body_removing_its_own_directory_is_fine(work_area: LocalWorkArea) -> None:
    with work_area.attempt() as directory:
        directory.rmdir()


def test_swapped_work_directory_fails_closed_and_outside_is_untouched(
    work_area: LocalWorkArea, outside: Path
) -> None:
    with pytest.raises(StorageError) as caught:
        _swap_for_symlink(work_area, outside, then_fail=False)
    assert caught.value.code is ErrorCode.STORAGE_WRITE_FAILED
    assert (outside / "keep.txt").exists()


def test_cleanup_failure_during_an_error_keeps_the_original_error(
    work_area: LocalWorkArea, outside: Path, caplog: pytest.LogCaptureFixture
) -> None:
    with (
        caplog.at_level(logging.WARNING, logger="cv_masking.storage"),
        pytest.raises(RuntimeError, match="synthetic failure"),
    ):
        _swap_for_symlink(work_area, outside, then_fail=True)
    assert [r.getMessage() for r in caplog.records] == [
        "work area cleanup deferred to sweeper code=STORAGE_WRITE_FAILED"
    ]
    assert (outside / "keep.txt").exists()


def test_attempt_fails_closed_when_work_directory_is_unsafe(
    work_area: LocalWorkArea, root: CacheRoot
) -> None:
    (root.path / "work").chmod(0o755)
    with pytest.raises(StorageError), work_area.attempt():
        pytest.fail("body must not run")
