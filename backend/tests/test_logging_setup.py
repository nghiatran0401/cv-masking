import logging
import stat
from logging.handlers import RotatingFileHandler
from pathlib import Path

from cv_masking.logging_setup import (
    LOG_FILE_MODE,
    LOG_FILE_NAME,
    configure_file_logging,
    install_metadata_filter,
)


def test_file_logs_are_owner_only_and_metadata_only(tmp_path: Path) -> None:
    directory = tmp_path / "logs"
    configure_file_logging(directory)
    logger = logging.getLogger("cv_masking")
    previous_level = logger.level
    try:
        logger.info("batch %s created", "00000000-0000-4000-8000-0000000000aa")
        logger.info("leak %s", "mau.nguyen@example.test")
        for handler in logger.handlers:
            handler.flush()
        path = directory / LOG_FILE_NAME
        assert stat.S_IMODE(path.stat().st_mode) == LOG_FILE_MODE
        text = path.read_text(encoding="utf-8")
        assert "00000000-0000-4000-8000-0000000000aa" in text
        assert "example.test" not in text
        assert "created" in text
    finally:
        remaining: list[logging.Handler] = []
        for handler in logger.handlers:
            if isinstance(handler, RotatingFileHandler):
                handler.close()
            else:
                remaining.append(handler)
        logger.handlers[:] = remaining
        logger.propagate = True
        logger.setLevel(previous_level)


def test_filter_is_idempotent() -> None:
    install_metadata_filter()
    install_metadata_filter()
    logger = logging.getLogger("cv_masking")
    filters = [item for item in logger.filters if type(item).__name__ == "MetadataOnlyFilter"]
    assert len(filters) == 1
