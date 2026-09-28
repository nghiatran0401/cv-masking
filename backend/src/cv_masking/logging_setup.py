"""Metadata-only logging: IDs, codes, counts, and type names. Never values or paths."""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Final

LOG_FILE_NAME: Final = "app.log"
LOG_MAX_BYTES: Final = 10 * 1024 * 1024
LOG_BACKUP_COUNT: Final = 7
LOG_FILE_MODE: Final = 0o600

_UNSAFE: Final = re.compile(
    r"@|"
    r"://|"
    r"/Users/|"
    r"/home/|"
    r"/etc/|"
    r"/private/|"
    r"\.\./"
)


class MetadataOnlyFilter(logging.Filter):
    """Drop exception text and replace a line that looks like it could hold a document."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.exc_info = None
        record.exc_text = None
        record.stack_info = None
        try:
            message = record.getMessage()
        except (TypeError, ValueError):
            record.msg = "log line redacted"
            record.args = ()
            return True
        if _UNSAFE.search(message) is not None:
            record.msg = "log line redacted"
            record.args = ()
        return True


def install_metadata_filter() -> None:
    logger = logging.getLogger("cv_masking")
    if not any(isinstance(item, MetadataOnlyFilter) for item in logger.filters):
        logger.addFilter(MetadataOnlyFilter())


def configure_file_logging(log_directory: Path) -> None:
    """Rotate at 10 MiB, keep seven files, owner-only. ``log_directory`` must already exist."""
    install_metadata_filter()
    log_directory.mkdir(mode=0o700, exist_ok=True)
    log_directory.chmod(0o700)
    path = log_directory / LOG_FILE_NAME
    handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_CLOEXEC, LOG_FILE_MODE)
    os.close(handle)
    path.chmod(LOG_FILE_MODE)
    handler = RotatingFileHandler(
        path,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
    handler.addFilter(MetadataOnlyFilter())
    logger = logging.getLogger("cv_masking")
    logger.setLevel(logging.INFO)
    if not any(
        isinstance(existing, RotatingFileHandler)
        and getattr(existing, "baseFilename", None) == str(path)
        for existing in logger.handlers
    ):
        logger.addHandler(handler)
        logger.propagate = False
    if path.exists():
        path.chmod(LOG_FILE_MODE)
