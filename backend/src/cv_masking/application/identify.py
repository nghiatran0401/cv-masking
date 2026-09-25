"""Classify an uploaded file from its bytes. Filenames are never stored."""

import zipfile
from enum import StrEnum
from pathlib import Path
from typing import Final

from cv_masking.domain.formats import DocumentFormat

PDF_MAGIC: Final = b"%PDF-"
OLE_MAGIC: Final = bytes.fromhex("d0cf11e0a1b11ae1")
ZIP_MAGICS: Final = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
CONTENT_TYPES_NAME: Final = "[Content_Types].xml"
MAX_CONTENT_TYPES_BYTES: Final = 1_000_000
DOCX_MAIN_TYPE: Final = (
    b"application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
)
MACRO_OR_TEMPLATE_MARKERS: Final = (
    b"macroEnabled",
    b"vbaProject",
    b"wordprocessingml.template",
    b"vnd.ms-word.template",
)
PDF_CONTENT_TYPES: Final = frozenset({"application/pdf"})
DOCX_CONTENT_TYPES: Final = frozenset(
    {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
)
GENERIC_CONTENT_TYPES: Final = frozenset({"", "application/octet-stream", "binary/octet-stream"})
PDF_EXTENSIONS: Final = frozenset({".pdf"})
DOCX_EXTENSIONS: Final = frozenset({".docx"})
OTHER_EXTENSIONS: Final = frozenset(
    {".doc", ".docm", ".dotx", ".dotm", ".rtf", ".odt", ".pages", ".jpg", ".jpeg", ".png", ".heic"}
)


class IdentifiedKind(StrEnum):
    PDF = "pdf"
    DOCX = "docx"
    MACRO_OR_TEMPLATE = "macro_or_template"
    UNSUPPORTED = "unsupported"

    @property
    def document_format(self) -> DocumentFormat | None:
        if self is IdentifiedKind.PDF:
            return DocumentFormat.PDF
        if self is IdentifiedKind.DOCX:
            return DocumentFormat.DOCX
        return None


def identify_file(path: Path) -> IdentifiedKind:
    """Decide the file type from content only. Reads a prefix, then at most one ZIP entry."""
    with path.open("rb") as file:
        prefix = file.read(1024)
    if PDF_MAGIC in prefix:
        return IdentifiedKind.PDF
    if prefix.startswith(OLE_MAGIC):
        return IdentifiedKind.UNSUPPORTED
    if not prefix.startswith(ZIP_MAGICS):
        return IdentifiedKind.UNSUPPORTED
    return _identify_office_zip(path)


def declared_disagrees(
    kind: IdentifiedKind, *, filename: str | None, content_type: str | None
) -> bool:
    """True when the client-supplied name or type contradicts the identified content."""
    hints = _declaration_hints(filename, content_type)
    if not hints:
        return False
    if len(hints) > 1:
        return True
    (declared,) = tuple(hints)
    if declared == "other":
        return kind in {IdentifiedKind.PDF, IdentifiedKind.DOCX}
    return kind.value != declared


def extension_of(filename: str | None) -> str | None:
    """The file suffix only. The rest of the name is discarded and never returned to callers."""
    if filename is None or filename == "":
        return None
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    if "." not in name or name.startswith("."):
        return None
    suffix = f".{name.rsplit('.', 1)[-1].lower()}"
    if not 2 <= len(suffix) <= 8 or not suffix[1:].isascii() or not suffix[1:].isalnum():
        return None
    return suffix


def _declaration_hints(filename: str | None, content_type: str | None) -> set[str]:
    hints: set[str] = set()
    ext = extension_of(filename)
    ctype = (content_type or "").split(";", 1)[0].strip().lower()
    if ext in PDF_EXTENSIONS or ctype in PDF_CONTENT_TYPES:
        hints.add(IdentifiedKind.PDF.value)
    if ext in DOCX_EXTENSIONS or ctype in DOCX_CONTENT_TYPES:
        hints.add(IdentifiedKind.DOCX.value)
    if ext in OTHER_EXTENSIONS or (
        ctype not in GENERIC_CONTENT_TYPES
        and ctype not in PDF_CONTENT_TYPES
        and ctype not in DOCX_CONTENT_TYPES
    ):
        hints.add("other")
    return hints


def _identify_office_zip(path: Path) -> IdentifiedKind:
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            if CONTENT_TYPES_NAME not in names:
                return IdentifiedKind.UNSUPPORTED
            info = archive.getinfo(CONTENT_TYPES_NAME)
            if info.file_size > MAX_CONTENT_TYPES_BYTES:
                return IdentifiedKind.UNSUPPORTED
            types = archive.read(CONTENT_TYPES_NAME)
    except zipfile.BadZipFile:
        return IdentifiedKind.UNSUPPORTED
    if len(types) > MAX_CONTENT_TYPES_BYTES:
        return IdentifiedKind.UNSUPPORTED
    if any(marker in types for marker in MACRO_OR_TEMPLATE_MARKERS):
        return IdentifiedKind.MACRO_OR_TEMPLATE
    if DOCX_MAIN_TYPE in types:
        return IdentifiedKind.DOCX
    return IdentifiedKind.UNSUPPORTED
