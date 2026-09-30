"""The per-user storage root and symlink-refusing access to its directories.

The root is resolved once when prepared. On macOS every operation goes through a
directory file descriptor opened with O_NOFOLLOW, so a symlink planted at the
root, a kind directory, or an object name is refused rather than followed. On
Windows the same calls stay inside that directory and refuse a symlink or junction.
"""

import logging
import os
import re
import shutil
import stat
from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager, suppress
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
ROOT_MARKER: Final = ".cv-masking-data"
SPOTLIGHT_MARKER: Final = ".metadata_never_index"
EXTENSIONS: Final = {DocumentFormat.PDF: ".pdf", DocumentFormat.DOCX: ".docx"}

_UUID4: Final = r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}"
OBJECT_NAME_RE: Final = re.compile(_UUID4 + r"\.(?:pdf|docx)")
TEMP_NAME_RE: Final = re.compile(r"\.[0-9a-f]{32}\.part")
WORK_NAME_RE: Final = re.compile(_UUID4)


def _os_flag(name: str) -> int:
    value = getattr(os, name, 0)
    return value if isinstance(value, int) else 0


_OPEN_DIR: Final = (
    os.O_RDONLY | _os_flag("O_DIRECTORY") | _os_flag("O_NOFOLLOW") | _os_flag("O_CLOEXEC")
)
_CREATE_FILE: Final = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | _os_flag("O_NOFOLLOW")
    | _os_flag("O_CLOEXEC")
    | _os_flag("O_BINARY")
)


class StoreKind(StrEnum):
    INPUTS = "inputs"
    OUTPUTS = "outputs"
    WORK = "work"


METADATA_DIR: Final = "metadata"
"""Holds the SQLite database. Not a StoreKind, so the sweeper never looks inside."""
LOGS_DIR: Final = "logs"
"""Rotated application logs (IDs and codes only). Not swept."""
LOCK_DIR: Final = "lock"
"""Single-instance lock. Not swept."""


_PROJECT_ROOT: Final = Path(__file__).resolve().parents[5]


def default_storage_root() -> Path:
    """``<project>/data``; the name must stay listed in .gitignore and .cursorignore."""
    return _PROJECT_ROOT / "data"


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
    if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
    if os.name == "nt":
        return
    if info.st_uid != os.getuid() or info.st_mode & 0o077:
        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)


def _is_reparse(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    return bool(callable(is_junction) and is_junction())


class StorageDir:
    """One storage directory.

    On macOS every call uses the ``O_NOFOLLOW`` directory descriptor. On Windows
    the same calls use a path confined to that directory, and a symlink or
    junction is refused.
    """

    __slots__ = ("_fd", "_path")

    def __init__(self, fd: int, path: Path) -> None:
        self._fd = fd
        self._path = path

    def close(self) -> None:
        if self._fd < 0:
            return
        os.close(self._fd)
        self._fd = -1

    def listdir(self) -> list[str]:
        if os.name == "nt":
            return os.listdir(self._path)
        return os.listdir(self._fd)

    def open(self, name: str, flags: int, mode: int = 0o777) -> int:
        if os.name == "nt":
            return os.open(self._locate(name), flags, mode)
        return os.open(name, flags, mode, dir_fd=self._fd)

    def stat(self, name: str) -> os.stat_result:
        if os.name == "nt":
            return os.stat(self._locate(name), follow_symlinks=False)
        return os.stat(name, dir_fd=self._fd, follow_symlinks=False)

    def unlink(self, name: str) -> None:
        if os.name == "nt":
            os.unlink(self._locate(name))
            return
        os.unlink(name, dir_fd=self._fd)

    def link(self, source: str, dest: str) -> None:
        if os.name == "nt":
            os.link(self._locate(source), self._locate(dest))
            return
        os.link(source, dest, src_dir_fd=self._fd, dst_dir_fd=self._fd, follow_symlinks=False)

    def mkdir(self, name: str, mode: int) -> None:
        if os.name == "nt":
            os.mkdir(self._locate(name), mode)
            return
        os.mkdir(name, mode, dir_fd=self._fd)

    def rmtree(self, name: str) -> None:
        if os.name == "nt":
            shutil.rmtree(self._locate(name))
            return
        shutil.rmtree(name, dir_fd=self._fd)

    def fsync(self) -> None:
        if self._fd >= 0:
            os.fsync(self._fd)

    def _locate(self, name: str) -> Path:
        if (
            not isinstance(name, str)
            or name in {"", ".", ".."}
            or "/" in name
            or "\\" in name
            or "\x00" in name
        ):
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
        child = self._path / name
        if _is_reparse(child):
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
        return child


def _require_owned_dir(fd: int, *, tighten: bool) -> None:
    info = os.fstat(fd)
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
    if info.st_mode & 0o077:
        if not tighten:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
        os.fchmod(fd, DIR_MODE)
        logger.warning("storage directory permissions tightened to owner-only")


def _touch_regular(directory: Path, name: str) -> None:
    target = directory / name
    if _is_reparse(target):
        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | _os_flag("O_CLOEXEC") | _os_flag("O_BINARY")
    try:
        os.close(os.open(target, flags, FILE_MODE))
    except FileExistsError:
        if _is_reparse(target) or not target.is_file():
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from None


def _create_marker(dir_fd: int, name: str) -> None:
    try:
        os.close(os.open(name, _CREATE_FILE, FILE_MODE, dir_fd=dir_fd))
    except FileExistsError:
        info = os.stat(name, dir_fd=dir_fd, follow_symlinks=False)
        if not stat.S_ISREG(info.st_mode):
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from None


class StorageRoot:
    """A validated, dedicated, owner-only storage directory. Build with ``prepare``."""

    __slots__ = ("_path",)

    def __init__(self, path: Path) -> None:
        self._path = path

    @property
    def path(self) -> Path:
        return self._path

    @classmethod
    def prepare(cls, path: Path) -> "StorageRoot":
        if os.name == "nt":
            return cls._prepare_nt(path)
        if not isinstance(path, Path) or not path.is_absolute() or path.name in {"", ".", ".."}:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
        try:
            root = Path(os.path.realpath(path.parent, strict=True)) / path.name
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
                for directory in (*StoreKind, METADATA_DIR, LOGS_DIR, LOCK_DIR):
                    cls._prepare_directory(root_fd, directory)
            finally:
                os.close(root_fd)
        except OSError as error:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
        return cls(root)

    @classmethod
    def _prepare_nt(cls, path: Path) -> "StorageRoot":
        """Windows has no ``O_NOFOLLOW`` directory descriptors.

        The root still has to be an absolute directory this app created. Symlinks
        and junctions are refused. Unix owner-only modes are not available, so the
        folder should stay inside the Windows user profile.
        """
        if not isinstance(path, Path) or not path.is_absolute() or path.name in {"", ".", ".."}:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
        try:
            parent = Path(os.path.realpath(path.parent, strict=True))
            root = parent / path.name
            if _is_reparse(root):
                raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
            try:
                root.mkdir()
                created = True
            except FileExistsError:
                created = False
                if _is_reparse(root) or not root.is_dir():
                    raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from None
            names = [entry.name for entry in root.iterdir()]
            if ROOT_MARKER not in names and names and not created:
                raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
            _touch_regular(root, ROOT_MARKER)
            _touch_regular(root, SPOTLIGHT_MARKER)
            for directory in (*StoreKind, METADATA_DIR, LOGS_DIR, LOCK_DIR):
                child = root / directory
                if child.exists():
                    if _is_reparse(child) or not child.is_dir():
                        raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
                else:
                    child.mkdir()
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
    def _prepare_directory(root_fd: int, name: str) -> None:
        with suppress(FileExistsError):
            os.mkdir(name, DIR_MODE, dir_fd=root_fd)
        dir_fd = os.open(name, _OPEN_DIR, dir_fd=root_fd)
        try:
            _require_owned_dir(dir_fd, tighten=True)
        finally:
            os.close(dir_fd)

    @property
    def metadata_path(self) -> Path:
        return self._path / METADATA_DIR

    def open_kind(self, kind: StoreKind) -> AbstractContextManager[StorageDir]:
        """One kind directory, re-checked on every use."""
        return self._open_directory(kind.value)

    def open_metadata(self) -> AbstractContextManager[StorageDir]:
        """The metadata directory, re-checked on every use."""
        return self._open_directory(METADATA_DIR)

    @contextmanager
    def _open_directory(self, name: str) -> Iterator[StorageDir]:
        if os.name == "nt":
            child = self._path / name
            if _is_reparse(child) or not child.is_dir():
                raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
            yield StorageDir(-1, child)
            return
        try:
            root_fd = os.open(self._path, _OPEN_DIR)
        except OSError as error:
            raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
        try:
            try:
                dir_fd = os.open(name, _OPEN_DIR, dir_fd=root_fd)
            except OSError as error:
                raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
            directory = StorageDir(dir_fd, self._path / name)
            try:
                _require_owned_dir(dir_fd, tighten=False)
                yield directory
            finally:
                directory.close()
        finally:
            os.close(root_fd)
