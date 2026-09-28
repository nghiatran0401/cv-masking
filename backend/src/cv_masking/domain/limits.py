"""Hard caps (decision D-09). Configuration may lower these, never raise them."""

from typing import Final

HARD_MAX_FILE_BYTES: Final = 20 * 1024 * 1024
HARD_MAX_FILES_PER_BATCH: Final = 50
HARD_MAX_BATCH_BYTES: Final = 500 * 1024 * 1024
HARD_MAX_PDF_PAGES: Final = 30
MIN_PAGE_TEXT_CHARS: Final = 8
"""Minimum extractable characters on a page before it is treated as image-only."""
MAX_DOCX_ENTRIES: Final = 2_000
MAX_DOCX_ENTRY_BYTES: Final = 50 * 1024 * 1024
MAX_DOCX_UNCOMPRESSED_BYTES: Final = 100 * 1024 * 1024
MAX_DOCX_COMPRESSION_RATIO: Final = 100
MAX_DOCX_TEXT_CHARS: Final = 300_000
MAX_XML_DEPTH: Final = 64
MAX_PROCESSING_ATTEMPTS: Final = 3
DEFAULT_UPLOAD_TIMEOUT_SECONDS: Final = 60
HARD_MAX_UPLOAD_TIMEOUT_SECONDS: Final = 15 * 60
DEFAULT_JOB_TIMEOUT_SECONDS: Final = 120
"""Wall-clock budget for one document (validate, redact, verify); typical CVs need seconds."""
HARD_MAX_JOB_TIMEOUT_SECONDS: Final = 10 * 60
READ_CHUNK_BYTES: Final = 64 * 1024
