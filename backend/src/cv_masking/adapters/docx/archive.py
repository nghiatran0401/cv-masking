"""Read a DOCX ZIP in memory. Never extracts to disk."""

import zipfile
from io import BytesIO
from typing import Final

from cv_masking.domain.codes import ErrorCode
from cv_masking.domain.limits import (
    MAX_DOCX_COMPRESSION_RATIO,
    MAX_DOCX_ENTRIES,
    MAX_DOCX_ENTRY_BYTES,
    MAX_DOCX_UNCOMPRESSED_BYTES,
)

_UNSAFE_NAME_CHARS: Final = frozenset({chr(0), "\\", ":"})


class DocxArchiveError(Exception):
    def __init__(self, code: ErrorCode) -> None:
        super().__init__(code.value)
        self.code = code


def read_docx_archive(data: bytes) -> dict[str, bytes]:
    """Return entry name → bytes after archive safety checks."""
    try:
        archive = zipfile.ZipFile(BytesIO(data))
    except zipfile.BadZipFile as error:
        raise DocxArchiveError(ErrorCode.DOCX_MALFORMED) from error
    with archive:
        names = archive.namelist()
        if len(names) > MAX_DOCX_ENTRIES:
            raise DocxArchiveError(ErrorCode.DOCX_RESOURCE_LIMIT)
        if len(names) != len(set(names)):
            raise DocxArchiveError(ErrorCode.DOCX_UNSAFE_ARCHIVE)
        total = 0
        parts: dict[str, bytes] = {}
        for name in names:
            if not _safe_entry_name(name):
                raise DocxArchiveError(ErrorCode.DOCX_UNSAFE_ARCHIVE)
            try:
                info = archive.getinfo(name)
            except KeyError as error:
                raise DocxArchiveError(ErrorCode.DOCX_MALFORMED) from error
            if info.is_dir():
                continue
            if info.file_size > MAX_DOCX_ENTRY_BYTES:
                raise DocxArchiveError(ErrorCode.DOCX_RESOURCE_LIMIT)
            if info.compress_size > 0 and info.file_size / info.compress_size > (
                MAX_DOCX_COMPRESSION_RATIO
            ):
                raise DocxArchiveError(ErrorCode.DOCX_RESOURCE_LIMIT)
            total += info.file_size
            if total > MAX_DOCX_UNCOMPRESSED_BYTES:
                raise DocxArchiveError(ErrorCode.DOCX_RESOURCE_LIMIT)
            try:
                parts[name] = archive.read(name)
            except (zipfile.BadZipFile, RuntimeError, ValueError, OSError) as error:
                raise DocxArchiveError(ErrorCode.DOCX_MALFORMED) from error
            if len(parts[name]) > MAX_DOCX_ENTRY_BYTES:
                raise DocxArchiveError(ErrorCode.DOCX_RESOURCE_LIMIT)
    return parts


def _safe_entry_name(name: str) -> bool:
    if not name or any(char in name for char in _UNSAFE_NAME_CHARS):
        return False
    if name.startswith("/") or name.startswith("\\"):
        return False
    return ".." not in name.split("/")
