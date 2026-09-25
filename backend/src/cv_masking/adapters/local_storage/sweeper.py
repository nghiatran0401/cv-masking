"""Age-based cleanup of the cache root (docs/data-retention.md §4-§5).

Removes leftover temporary files and work directories, objects past the
retention window, and anything unexpected. Symlinks are removed, never followed.
Orphans with no metadata row are reconciled once SQLite exists (Stage 4).
"""

import logging
import os
import shutil
import stat
from datetime import UTC, datetime, timedelta
from typing import Final

from cv_masking.adapters.local_storage.root import (
    OBJECT_NAME_RE,
    TEMP_NAME_RE,
    WORK_NAME_RE,
    CacheRoot,
    StoreKind,
)
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.limits import RETENTION_WINDOW
from cv_masking.ports.storage import SweepReport

logger = logging.getLogger("cv_masking.storage")

TEMPORARY_MAX_AGE: Final = timedelta(hours=1)
WORK_MAX_AGE: Final = timedelta(hours=1)
UNEXPECTED_MAX_AGE: Final = timedelta(hours=1)
OBJECT_MAX_AGE: Final = RETENTION_WINDOW


def _classify(kind: StoreKind, name: str, mode: int) -> tuple[str, timedelta]:
    if kind is StoreKind.WORK:
        if WORK_NAME_RE.fullmatch(name) and stat.S_ISDIR(mode):
            return "work", WORK_MAX_AGE
    elif stat.S_ISREG(mode):
        if OBJECT_NAME_RE.fullmatch(name):
            return "expired", OBJECT_MAX_AGE
        if TEMP_NAME_RE.fullmatch(name):
            return "temporary", TEMPORARY_MAX_AGE
    return "unexpected", UNEXPECTED_MAX_AGE


class LocalStorageSweeper:
    __slots__ = ("_root",)

    def __init__(self, root: CacheRoot) -> None:
        self._root = root

    def sweep(self, now: datetime) -> SweepReport:
        if not isinstance(now, datetime) or now.utcoffset() != timedelta(0):
            raise InvariantError("sweep time must be a timezone-aware UTC datetime")
        counts = dict.fromkeys(("expired", "temporary", "work", "unexpected", "failed"), 0)
        for kind in StoreKind:
            with self._root.open_kind(kind) as dir_fd:
                for name in os.listdir(dir_fd):
                    outcome = self._sweep_entry(dir_fd, kind, name, now)
                    if outcome is not None:
                        counts[outcome] += 1
        report = SweepReport(**counts)
        logger.info(
            "storage sweep removed=%d expired=%d temporary=%d work=%d unexpected=%d failed=%d",
            report.removed,
            report.expired,
            report.temporary,
            report.work,
            report.unexpected,
            report.failed,
        )
        return report

    @staticmethod
    def _sweep_entry(dir_fd: int, kind: StoreKind, name: str, now: datetime) -> str | None:
        try:
            info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        except FileNotFoundError:
            return None
        category, max_age = _classify(kind, name, info.st_mode)
        if now - datetime.fromtimestamp(info.st_mtime, UTC) < max_age:
            return None
        try:
            if stat.S_ISDIR(info.st_mode):
                shutil.rmtree(name, dir_fd=dir_fd)
            else:
                os.unlink(name, dir_fd=dir_fd)
        except FileNotFoundError:
            return None
        except OSError:
            logger.warning("storage sweep could not remove a %s entry in %s", category, kind)
            return "failed"
        return category
