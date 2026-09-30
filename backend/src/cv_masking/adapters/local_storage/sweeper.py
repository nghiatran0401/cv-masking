"""Age-based cleanup of the storage root (docs/data-retention.md §4-§5).

Removes leftover temporary files, work directories, and anything unexpected.
Stored inputs and outputs are never removed by age: HR deletes them (decision D-22).
Symlinks are removed, never followed.
"""

import logging
import stat
from datetime import UTC, datetime, timedelta
from typing import Final

from cv_masking.adapters.local_storage.root import (
    OBJECT_NAME_RE,
    TEMP_NAME_RE,
    WORK_NAME_RE,
    StorageDir,
    StorageRoot,
    StoreKind,
)
from cv_masking.domain.errors import InvariantError
from cv_masking.ports.storage import SweepReport

logger = logging.getLogger("cv_masking.storage")

TEMPORARY_MAX_AGE: Final = timedelta(hours=1)
WORK_MAX_AGE: Final = timedelta(hours=1)
UNEXPECTED_MAX_AGE: Final = timedelta(hours=1)


def _classify(kind: StoreKind, name: str, mode: int) -> tuple[str, timedelta] | None:
    """The sweep category and maximum age of an entry, or None if it is kept."""
    if kind is StoreKind.WORK:
        if WORK_NAME_RE.fullmatch(name) and stat.S_ISDIR(mode):
            return "work", WORK_MAX_AGE
    elif stat.S_ISREG(mode):
        if OBJECT_NAME_RE.fullmatch(name):
            return None
        if TEMP_NAME_RE.fullmatch(name):
            return "temporary", TEMPORARY_MAX_AGE
    return "unexpected", UNEXPECTED_MAX_AGE


class LocalStorageSweeper:
    __slots__ = ("_root",)

    def __init__(self, root: StorageRoot) -> None:
        self._root = root

    def sweep(self, now: datetime) -> SweepReport:
        if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
            raise InvariantError("sweep time must be a timezone-aware UTC datetime")
        counts = dict.fromkeys(("temporary", "work", "unexpected", "failed"), 0)
        for kind in StoreKind:
            with self._root.open_kind(kind) as directory:
                for name in directory.listdir():
                    outcome = self._sweep_entry(directory, kind, name, now)
                    if outcome is not None:
                        counts[outcome] += 1
        report = SweepReport(**counts)
        logger.info(
            "storage sweep removed=%d temporary=%d work=%d unexpected=%d failed=%d",
            report.removed,
            report.temporary,
            report.work,
            report.unexpected,
            report.failed,
        )
        return report

    @staticmethod
    def _sweep_entry(
        directory: StorageDir, kind: StoreKind, name: str, now: datetime
    ) -> str | None:
        try:
            info = directory.stat(name)
        except FileNotFoundError:
            return None
        classified = _classify(kind, name, info.st_mode)
        if classified is None:
            return None
        category, max_age = classified
        if now - datetime.fromtimestamp(info.st_mtime, UTC) < max_age:
            return None
        try:
            if stat.S_ISDIR(info.st_mode):
                directory.rmtree(name)
            else:
                directory.unlink(name)
        except FileNotFoundError:
            return None
        except OSError:
            logger.warning("storage sweep could not remove a %s entry in %s", category, kind)
            return "failed"
        return category
