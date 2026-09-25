import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

import pytest

from cv_masking.adapters.local_storage import LocalStorageSweeper, StorageRoot
from cv_masking.adapters.local_storage.root import ROOT_MARKER, SPOTLIGHT_MARKER
from cv_masking.domain.errors import InvariantError
from cv_masking.ports.storage import SweepReport

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
DAY = timedelta(hours=24)
SECOND = timedelta(seconds=1)


def _age(path: Path, age: timedelta) -> Path:
    stamp = (NOW - age).timestamp()
    os.utime(path, (stamp, stamp), follow_symlinks=False)
    return path


def _file(directory: Path, name: str, age: timedelta) -> Path:
    path = directory / name
    path.write_bytes(b"synthetic")
    path.chmod(0o400)
    return _age(path, age)


def _object_name(suffix: str = ".pdf") -> str:
    return f"{uuid4()}{suffix}"


def test_fresh_entries_are_kept(sweeper: LocalStorageSweeper, root: StorageRoot) -> None:
    _file(root.path / "inputs", f".{uuid4().hex}.part", HOUR - SECOND)
    _age(_mkdir(root.path / "work" / str(uuid4())), HOUR - SECOND)
    _file(root.path / "outputs", "unexpected.txt", HOUR - SECOND)
    assert sweeper.sweep(NOW) == SweepReport()


def test_stored_objects_are_never_removed_by_age(
    sweeper: LocalStorageSweeper, root: StorageRoot
) -> None:
    old_input = _file(root.path / "inputs", _object_name(), DAY * 365)
    old_output = _file(root.path / "outputs", _object_name(".docx"), DAY * 365)
    assert sweeper.sweep(NOW) == SweepReport()
    assert old_input.read_bytes() == b"synthetic"
    assert old_output.read_bytes() == b"synthetic"


def test_leftover_temporary_files_are_removed_after_an_hour(
    sweeper: LocalStorageSweeper, root: StorageRoot
) -> None:
    leftover = _file(root.path / "outputs", f".{uuid4().hex}.part", HOUR)
    assert sweeper.sweep(NOW) == SweepReport(temporary=1)
    assert not leftover.exists()


def test_abandoned_work_directories_are_removed_without_following_links(
    sweeper: LocalStorageSweeper, root: StorageRoot, outside: Path
) -> None:
    work = _mkdir(root.path / "work" / str(uuid4()))
    (work / "part.bin").write_bytes(b"synthetic")
    (work / "escape").symlink_to(outside)
    _age(work, HOUR)
    assert sweeper.sweep(NOW) == SweepReport(work=1)
    assert not work.exists()
    assert (outside / "keep.txt").exists()


def test_unexpected_entries_are_removed_without_following_links(
    sweeper: LocalStorageSweeper, root: StorageRoot, outside: Path
) -> None:
    link = root.path / "inputs" / _object_name()
    link.symlink_to(outside / "keep.txt")
    _age(link, HOUR)
    stray = _file(root.path / "outputs", "notes.txt", HOUR)
    object_named_directory = _age(_mkdir(root.path / "outputs" / _object_name()), HOUR)
    work_file = _file(root.path / "work", str(uuid4()), HOUR)
    report = sweeper.sweep(NOW)
    assert report == SweepReport(unexpected=4)
    for path in (link, stray, object_named_directory, work_file):
        assert not os.path.lexists(path)
    assert (outside / "keep.txt").read_bytes() == b"synthetic outside file\n"


def test_root_level_markers_are_never_swept(
    sweeper: LocalStorageSweeper, root: StorageRoot
) -> None:
    for marker in (ROOT_MARKER, SPOTLIGHT_MARKER):
        _age(root.path / marker, DAY * 30)
    sweeper.sweep(NOW)
    assert (root.path / ROOT_MARKER).exists()
    assert (root.path / SPOTLIGHT_MARKER).exists()


def test_future_timestamps_are_kept(sweeper: LocalStorageSweeper, root: StorageRoot) -> None:
    _file(root.path / "inputs", f".{uuid4().hex}.part", -HOUR)
    assert sweeper.sweep(NOW) == SweepReport()


def test_removal_failures_are_counted_and_sweeping_continues(
    sweeper: LocalStorageSweeper, root: StorageRoot, monkeypatch: pytest.MonkeyPatch
) -> None:
    _file(root.path / "inputs", f".{uuid4().hex}.part", HOUR)
    _file(root.path / "outputs", f".{uuid4().hex}.part", HOUR)
    real_unlink = os.unlink
    calls: list[str] = []

    def unlink_once_failing(name: str, *, dir_fd: int | None = None) -> None:
        calls.append(name)
        if len(calls) == 1:
            raise PermissionError("synthetic permission failure")
        real_unlink(name, dir_fd=dir_fd)

    monkeypatch.setattr("cv_masking.adapters.local_storage.sweeper.os.unlink", unlink_once_failing)
    report = sweeper.sweep(NOW)
    assert report == SweepReport(temporary=1, failed=1)
    assert report.removed == 1


@pytest.mark.parametrize("now", [datetime(2026, 9, 25, 12, 0), "2026-09-25T12:00:00Z"])
def test_sweep_time_must_be_utc(sweeper: LocalStorageSweeper, now: object) -> None:
    with pytest.raises(InvariantError):
        sweeper.sweep(now)  # type: ignore[arg-type]


def _mkdir(path: Path) -> Path:
    path.mkdir(mode=0o700)
    return path
