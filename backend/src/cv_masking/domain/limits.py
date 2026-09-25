"""Hard caps (decision D-09). Configuration may lower these, never raise them."""

from typing import Final

HARD_MAX_FILE_BYTES: Final = 20 * 1024 * 1024
HARD_MAX_FILES_PER_BATCH: Final = 100
HARD_MAX_PDF_PAGES: Final = 30
MAX_PROCESSING_ATTEMPTS: Final = 3
