"""Identifier and digest value objects.

Identifiers must be random (version 4) UUIDs so they carry no information
about the document or the user.
"""

import re
from dataclasses import dataclass
from typing import Final
from uuid import RFC_4122, UUID

from cv_masking.domain.errors import InvariantError

_SHA256_HEX_RE: Final = re.compile(r"[0-9a-f]{64}")


def _require_uuid4(value: object, field: str) -> None:
    if not isinstance(value, UUID) or value.variant != RFC_4122 or value.version != 4:
        raise InvariantError(f"{field} must be a version 4 UUID")


@dataclass(frozen=True, slots=True)
class BatchId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid4(self.value, "BatchId")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class DocumentId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid4(self.value, "DocumentId")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class FindingId:
    value: UUID

    def __post_init__(self) -> None:
        _require_uuid4(self.value, "FindingId")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """Opaque reference to a stored file (input or output), never a path."""

    value: UUID

    def __post_init__(self) -> None:
        _require_uuid4(self.value, "ObjectRef")

    def __str__(self) -> str:
        return str(self.value)


@dataclass(frozen=True, slots=True)
class Sha256Digest:
    """Lowercase hex SHA-256 of a stored file."""

    value: str

    def __post_init__(self) -> None:
        if not isinstance(self.value, str) or _SHA256_HEX_RE.fullmatch(self.value) is None:
            raise InvariantError("Sha256Digest must be 64 lowercase hex characters")

    def __str__(self) -> str:
        return self.value
