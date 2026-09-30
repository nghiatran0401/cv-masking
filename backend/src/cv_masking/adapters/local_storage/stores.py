"""Local input and output stores: atomic, hashed, owner-only, never overwriting."""

import hashlib
import logging
import os
import stat
from collections.abc import Iterable
from datetime import UTC, datetime
from typing import BinaryIO, ClassVar, Final
from uuid import UUID, uuid4

from cv_masking.adapters.local_storage.root import (
    FILE_MODE,
    OBJECT_MODE,
    OBJECT_NAME_RE,
    StorageDir,
    StorageRoot,
    StoreKind,
    object_name,
    require_owned_file,
)
from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import ObjectRef, Sha256Digest
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES
from cv_masking.ports.storage import (
    ObjectListing,
    ObjectSink,
    Producer,
    StorageError,
    StoredObject,
)

logger = logging.getLogger("cv_masking.storage")

_READ_CHUNK: Final = 64 * 1024
_OPEN_READ: Final = (
    os.O_RDONLY
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_NONBLOCK", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)
)
_CREATE_TEMP: Final = (
    os.O_WRONLY
    | os.O_CREAT
    | os.O_EXCL
    | getattr(os, "O_NOFOLLOW", 0)
    | getattr(os, "O_CLOEXEC", 0)
    | getattr(os, "O_BINARY", 0)
)


class _Sink:
    """Counts, hashes, and size-limits bytes on their way to the temporary file."""

    __slots__ = ("_file", "_hash", "_limit_code", "_max_bytes", "size")

    def __init__(self, file: BinaryIO, max_bytes: int, limit_code: ErrorCode) -> None:
        self._file = file
        self._hash = hashlib.sha256()
        self._max_bytes = max_bytes
        self._limit_code = limit_code
        self.size = 0

    def write(self, data: bytes, /) -> int:
        if not isinstance(data, bytes | bytearray | memoryview):
            raise TypeError("an object sink only accepts bytes")
        length = memoryview(data).nbytes
        if self.size + length > self._max_bytes:
            raise StorageError(self._limit_code)
        self._file.write(data)
        self._hash.update(data)
        self.size += length
        return length

    def digest(self) -> Sha256Digest:
        return Sha256Digest(self._hash.hexdigest())


def _discard(directory: StorageDir, name: str) -> None:
    """Best-effort removal during failure handling; leftovers are swept by age."""
    try:
        directory.unlink(name)
    except FileNotFoundError:
        return
    except OSError:
        logger.warning(
            "storage cleanup deferred to sweeper code=%s", ErrorCode.STORAGE_WRITE_FAILED
        )


class _LocalObjectStore:
    _kind: ClassVar[StoreKind]
    _limit_code: ClassVar[ErrorCode]

    __slots__ = ("_root",)

    def __init__(self, root: StorageRoot) -> None:
        self._root = root

    def save(
        self, document_format: DocumentFormat, producer: Producer, *, max_bytes: int
    ) -> StoredObject:
        ref = ObjectRef(uuid4())
        name = object_name(ref, document_format)
        if isinstance(max_bytes, bool) or not isinstance(max_bytes, int):
            raise StorageError(ErrorCode.STORAGE_WRITE_FAILED)
        if not 1 <= max_bytes <= HARD_MAX_FILE_BYTES:
            raise StorageError(ErrorCode.STORAGE_WRITE_FAILED)
        temp = f".{uuid4().hex}.part"
        with self._root.open_kind(self._kind) as directory:
            linked = False
            try:
                try:
                    fd = directory.open(temp, _CREATE_TEMP, FILE_MODE)
                    sink = self._fill(fd, producer, max_bytes)
                    directory.link(temp, name)
                    linked = True
                    directory.fsync()
                except OSError as error:
                    raise StorageError(ErrorCode.STORAGE_WRITE_FAILED) from error
            except BaseException:
                if linked:
                    _discard(directory, name)
                raise
            finally:
                _discard(directory, temp)
        logger.info("stored %s object %s", self._kind, ref)
        return StoredObject(ref, document_format, sink.digest(), sink.size)

    def _fill(self, fd: int, producer: Producer, max_bytes: int) -> _Sink:
        with os.fdopen(fd, "wb") as file:
            sink = _Sink(file, max_bytes, self._limit_code)
            producer(sink)
            if sink.size == 0:
                raise StorageError(ErrorCode.STORAGE_WRITE_FAILED)
            file.flush()
            if hasattr(os, "fchmod"):
                os.fchmod(file.fileno(), OBJECT_MODE)
            os.fsync(file.fileno())
        return sink

    def open(self, ref: ObjectRef, document_format: DocumentFormat) -> BinaryIO:
        name = object_name(ref, document_format)
        with self._root.open_kind(self._kind) as directory:
            try:
                fd = directory.open(name, _OPEN_READ)
            except FileNotFoundError as error:
                raise StorageError(ErrorCode.STORAGE_INTEGRITY_FAILED) from error
            except OSError as error:
                raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
        try:
            require_owned_file(fd)
        except BaseException:
            os.close(fd)
            raise
        return os.fdopen(fd, "rb")

    def verify(self, stored: StoredObject) -> None:
        digest = hashlib.sha256()
        size = 0
        with self.open(stored.ref, stored.document_format) as file:
            while chunk := file.read(_READ_CHUNK):
                digest.update(chunk)
                size += len(chunk)
        if size != stored.size_bytes or digest.hexdigest() != stored.sha256.value:
            raise StorageError(ErrorCode.STORAGE_INTEGRITY_FAILED)

    def delete(self, ref: ObjectRef, document_format: DocumentFormat) -> bool:
        name = object_name(ref, document_format)
        with self._root.open_kind(self._kind) as directory:
            try:
                info = directory.stat(name)
            except FileNotFoundError:
                return False
            except OSError as error:
                raise StorageError(ErrorCode.STORAGE_WRITE_FAILED) from error
            if stat.S_ISDIR(info.st_mode):
                raise StorageError(ErrorCode.STORAGE_PATH_REJECTED)
            try:
                directory.unlink(name)
            except FileNotFoundError:
                return False
            except OSError as error:
                raise StorageError(ErrorCode.STORAGE_WRITE_FAILED) from error
        logger.info("deleted %s object %s", self._kind, ref)
        return True

    def list_objects(self) -> tuple[ObjectListing, ...]:
        listings: list[ObjectListing] = []
        with self._root.open_kind(self._kind) as directory:
            for name in directory.listdir():
                if OBJECT_NAME_RE.fullmatch(name) is None:
                    continue
                try:
                    info = directory.stat(name)
                except FileNotFoundError:
                    continue
                except OSError as error:
                    raise StorageError(ErrorCode.STORAGE_PATH_REJECTED) from error
                if not stat.S_ISREG(info.st_mode):
                    continue
                stem, extension = name.split(".")
                listings.append(
                    ObjectListing(
                        ObjectRef(UUID(stem)),
                        DocumentFormat(extension),
                        datetime.fromtimestamp(info.st_mtime, UTC),
                    )
                )
        return tuple(listings)


class LocalInputStore(_LocalObjectStore):
    """Uploaded input copies (files/inputs). Oversize uploads fail as UPLOAD_FILE_TOO_LARGE."""

    _kind = StoreKind.INPUTS
    _limit_code = ErrorCode.UPLOAD_FILE_TOO_LARGE
    __slots__ = ()

    def save_stream(
        self, document_format: DocumentFormat, chunks: Iterable[bytes], *, max_bytes: int
    ) -> StoredObject:
        def copy(sink: ObjectSink) -> None:
            for chunk in chunks:
                sink.write(chunk)

        return self.save(document_format, copy, max_bytes=max_bytes)


class LocalOutputStore(_LocalObjectStore):
    """Redacted outputs (files/outputs)."""

    _kind = StoreKind.OUTPUTS
    _limit_code = ErrorCode.STORAGE_WRITE_FAILED
    __slots__ = ()
