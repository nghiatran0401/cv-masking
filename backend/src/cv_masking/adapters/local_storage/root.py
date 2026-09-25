"""The per-user cache root and owner-only, symlink-refusing access to its directories.

The root is resolved once when prepared. After that every operation goes
through a directory file descriptor opened with O_NOFOLLOW, so a symlink planted
at the root, a kind directory, or an object name is refused rather than followed.
"""

import logging
import os
import re
import stat
from collections.abc import Iterator
from contextlib import contextmanager, suppress
from enum import StrEnum
from pathlib import Path
from typing import Final

from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import ObjectRef
from cv_masking.ports.storage import StorageError

logger = logging.getLogger("cv_masking.storage")

DIR_MODE: Final = 0o700
FILE_MODE: Final = 0o600
OBJECT_MODE: Final = 0o400
ROOT_MARKER: Final = ".cv-masking-cache"
SPOTLIGHT_MARKER: Final = ".metadata_never_index"
EXTENSIONS: Final = {DocumentFormat.PDF: ".pdf", DocumentFormat.DOCX: ".docx"}

_UUID4: Final = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
OBJECT_NAME_RE: Final = re.compile(_UUID4 + r"\.(?:pdf|docx)")
TEMP_NAME_RE: Final = re.compile(r"\.[0-9a-f]{32}\.part")
WORK_NAME_RE: Final = re.compile(_UUID4)

_OPEN_DIR: Final = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_CLOEXEC
_CREATE_FILE: Final = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_CLOEXEC


class StoreKind(StrEnum):
    INPUTS = "inputs"
    OUTPUTS = "outputs"
    WORK = "work"


def default_cache_root() -> Path:
    return Path.home() / "Library" / "Caches" / "CVMasking"


def object_name(ref: ObjectRef, document_format: DocumentFormat) -> str:
    """The only way a stored file is named: random UUID plus the validated format."""
    if not isinstance(ref, ObjectRef) or not isinstance(document_format, DocumentFormat):
        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
    name = f"{ref.value}{EXTENSIONS[document_format]}"
    if OBJECT_NAME_RE.fullmatch(name) is None:
        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
    return name


def require_owned_file(fd: int) -> None:
    """Refuse anything but a private regular file owned by this user with one link."""
    info = os.fstat(fd)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or info.st_mode & 0o077
    ):
        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)


def _require_owned_dir(fd: int, *, tighten: bool) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
    if info.st_mode & 0o077:
        if not tighten:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
        os.fchmod(fd, DIR_MODE)
        logger.warning("storage directory permissions tightened to owner-only")


def _refuse_inside_git_checkout(root: Path) -> None:
    for directory in (root, *root.parents):
        if os.path.lexists(directory / ".git"):
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)


def _create_marker(dir_fd: int, name: str) -> None:
    try:
        os.close(os.open(name, _CREATE_FILE, FILE_MODE, dir_fd=dir_fd))
    except FileExistsError:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from None


class CacheRoot:
    """A validated, dedicated, owner-only cache directory. Build with ``prepare``."""

    __slots__ = ("_path",)

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def prepare(cls, path: Path) -> "CacheRoot":
        if not isinstance(path, Path) or not path.is_absolute() or path.name in {"", ".", ".."}:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
        try:
            root = Path(os.path.realpath(path.parent, strict=True)) / path.name
            _refuse_inside_git_checkout(root)
            try:
                os.mkdir(root, DIR_MODE)
                created = True
            except FileExistsError:
                created = False
            root_fd = os.open(root, _OPEN_DIR)
            try:
                _require_owned_dir(root_fd, tighten=True)
                cls._claim(root_fd, created=created)
                _create_marker(root_fd, SPOTLIGHT_MARKER)
                for kind in StoreKind:
                    cls._prepare_kind(root_fd, kind)
            finally:
                os.close(root_fd)
        except OSError as error:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
        return cls(root)

    @staticmethod
    def _claim(root_fd: int, *, created: bool) -> None:
        """Only use a directory this app created, or an empty one it may adopt."""
        entries = os.listdir(root_fd)
        if ROOT_MARKER not in entries and entries and not created:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
        _create_marker(root_fd, ROOT_MARKER)

    @staticmethod
    def _prepare_kind(root_fd: int, kind: StoreKind) -> None:
        with suppress(FileExistsError):
            os.mkdir(kind.value, DIR_MODE, dir_fd=root_fd)
        kind_fd = os.open(kind.value, _OPEN_DIR, dir_fd=root_fd)
        try:
            _require_owned_dir(kind_fd, tighten=True)
        finally:
            os.close(kind_fd)

    @contextmanager
    def open_kind(self, kind: StoreKind) -> Iterator[int]:
        """A file descriptor for one kind directory, re-checked on every use."""
        try:
            root_fd = os.open(self._path, _OPEN_DIR)
        except OSError as error:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
        try:
            try:
                kind_fd = os.open(kind.value, _OPEN_DIR, dir_fd=root_fd)
            except OSError as error:
                raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
            try:
                _require_owned_dir(kind_fd, tighten=False)
                yield kind_fd
            finally:
                os.close(kind_fd)
        finally:
            os.close(root_fd)
