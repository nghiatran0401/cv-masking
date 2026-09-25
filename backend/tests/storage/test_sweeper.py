import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from cv_masking.adapters.local_storage import LocalStorageSweeper, StorageRoot
from cv_masking.ports.storage import SweepReport

NOW = datetime(2026, 9, 25, 12, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)
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


def test_stored_objects_are_never_removed_by_age(
    sweeper: LocalStorageSweeper, root: StorageRoot
) -> None:
    old_input = _file(root.path / "inputs", f"{uuid4()}.pdf", timedelta(days=365))
    old_output = _file(root.path / "outputs", f"{uuid4()}.docx", timedelta(days=365))
    assert sweeper.sweep(NOW) == SweepReport()
    assert old_input.exists()
    assert old_output.exists()


def test_leftover_temporary_files_are_removed_only_after_an_hour(
    sweeper: LocalStorageSweeper, root: StorageRoot
) -> None:
    fresh = _file(root.path / "inputs", f".{uuid4().hex}.part", HOUR - SECOND)
    leftover = _file(root.path / "outputs", f".{uuid4().hex}.part", HOUR)
    assert sweeper.sweep(NOW) == SweepReport(temporary=1)
    assert fresh.exists()
    assert not leftover.exists()


def test_old_work_and_unexpected_entries_are_removed_without_following_links(
    sweeper: LocalStorageSweeper, root: StorageRoot, outside: Path
) -> None:
    work = root.path / "work" / str(uuid4())
    work.mkdir(mode=0o700)
    (work / "escape").symlink_to(outside)
    _age(work, HOUR)
    link = root.path / "inputs" / f"{uuid4()}.pdf"
    link.symlink_to(outside / "keep.txt")
    _age(link, HOUR)
    stray = _file(root.path / "outputs", "notes.txt", HOUR)
    assert sweeper.sweep(NOW) == SweepReport(work=1, unexpected=2)
    for path in (work, link, stray):
        assert not os.path.lexists(path)
    assert (outside / "keep.txt").read_bytes() == b"synthetic outside file\n"
