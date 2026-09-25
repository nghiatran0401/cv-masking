import logging
import os
import shutil
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

from cv_masking.adapters.local_storage.root import DIR_MODE, CacheRoot, StoreKind
from cv_masking.domain.codes import ErrorCode
from cv_masking.ports.storage import StorageError

logger = logging.getLogger("cv_masking.storage")


class LocalWorkArea:
    """Per-attempt scratch directories under files/work, always removed afterwards."""

    __slots__ = ("_root",)

    def __init__(self, root: CacheRoot) -> None:
        self._root = root

    @contextmanager
    def attempt(self) -> Iterator[Path]:
        name = str(uuid4())
        with self._root.open_kind(StoreKind.WORK) as dir_fd:
            try:
                os.mkdir(name, DIR_MODE, dir_fd=dir_fd)
            except OSError as error:
                raise StorageError(ErrorCode.STORAGE_WRITE_FAILED) from error
        try:
            yield self._root.path / StoreKind.WORK.value / name
        except BaseException:
            self._remove(name, raise_on_failure=False)
            raise
        self._remove(name, raise_on_failure=True)

    def _remove(self, name: str, *, raise_on_failure: bool) -> None:
        try:
            with self._root.open_kind(StoreKind.WORK) as dir_fd:
                shutil.rmtree(name, dir_fd=dir_fd)
        except FileNotFoundError:
            return
        except (OSError, StorageError) as error:
            if raise_on_failure:
                raise StorageError(ErrorCode.STORAGE_WRITE_FAILED) from error
            logger.warning(
                "work area cleanup deferred to sweeper code=%s", ErrorCode.STORAGE_WRITE_FAILED
            )
