"""Storage ports for uploaded inputs, redacted outputs, and per-attempt work space.

Objects are addressed only by a random ObjectRef and the validated document
format. No caller-supplied name or path ever reaches a store.
"""

from collections.abc import Callable, Iterable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import BinaryIO, Final, Protocol

from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.errors import InvariantError
from cv_masking.domain.formats import DocumentFormat
from cv_masking.domain.ids import ObjectRef, Sha256Digest
from cv_masking.domain.limits import HARD_MAX_FILE_BYTES

STORAGE_ERROR_CODES: Final = frozenset(
    {
        ErrorCode.STORAGE_WRITE_FAILED,
        ErrorCode.STORAGE_PATH_REJECTED,
        ErrorCode.STORAGE_INTEGRITY_FAILED,
        ErrorCode.UPLOAD_FILE_TOO_LARGE,
    }
)


class StorageError(Exception):
    """A storage operation failed; carries only a safe error code."""

    def __init__(self, code: ErrorCode) -> None:
        if code not in STORAGE_ERROR_CODES:
            raise InvariantError("StorageError needs a storage error code")
        super().__init__(code.value)
        self.code = code


@dataclass(frozen=True, slots=True)
class StoredObject:
    ref: ObjectRef
    document_format: DocumentFormat
    sha256: Sha256Digest
    size_bytes: int

    def __post_init__(self) -> None:
        if not isinstance(self.ref, ObjectRef):
            raise InvariantError("StoredObject.ref must be an ObjectRef")
        if not isinstance(self.document_format, DocumentFormat):
            raise InvariantError("StoredObject.document_format must be a DocumentFormat")
        if not isinstance(self.sha256, Sha256Digest):
            raise InvariantError("StoredObject.sha256 must be a Sha256Digest")
        size = self.size_bytes
        if isinstance(size, bool) or not isinstance(size, int):
            raise InvariantError("StoredObject.size_bytes must be an integer")
        if not 1 <= size <= HARD_MAX_FILE_BYTES:
            raise InvariantError("StoredObject.size_bytes is out of range")


class ObjectSink(Protocol):
    """Write-only view of an object being stored."""

    def write(self, data: bytes, /) -> int: ...


type Producer = Callable[[ObjectSink], None]


class ObjectStore(Protocol):
    def save(
        self, document_format: DocumentFormat, producer: Producer, *, max_bytes: int
    ) -> StoredObject:
        """Store what ``producer`` writes. Nothing is visible unless it returns normally."""
        ...

    def open(self, ref: ObjectRef, document_format: DocumentFormat) -> BinaryIO: ...

    def verify(self, stored: StoredObject) -> None:
        """Raise STORAGE_INTEGRITY_FAILED unless the object has the recorded hash and size."""
        ...

    def delete(self, ref: ObjectRef, document_format: DocumentFormat) -> bool:
        """Delete the object; False if it did not exist."""
        ...


class InputStore(ObjectStore, Protocol):
    def save_stream(
        self, document_format: DocumentFormat, chunks: Iterable[bytes], *, max_bytes: int
    ) -> StoredObject: ...


class OutputStore(ObjectStore, Protocol): ...


class WorkArea(Protocol):
    def attempt(self) -> AbstractContextManager[Path]:
        """A fresh owner-only directory, removed when the block exits (success or failure)."""
        ...


@dataclass(frozen=True, slots=True)
class SweepReport:
    expired: int = 0
    temporary: int = 0
    work: int = 0
    unexpected: int = 0
    failed: int = 0

    @property
    def removed(self) -> int:
        return self.expired + self.temporary + self.work + self.unexpected


class StorageSweeper(Protocol):
    def sweep(self, now: datetime) -> SweepReport: ...
