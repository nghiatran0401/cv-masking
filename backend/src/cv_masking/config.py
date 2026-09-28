"""Runtime settings.

The bind host is a constant: the service must only ever listen on loopback, so
no setting, environment variable, or CLI flag can change it. Upload limits may
be lowered by environment variables; they cannot be raised above the hard caps.
The per-document time limit may be set between 1 second and its hard cap.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from cv_masking.domain.limits import (
    DEFAULT_JOB_TIMEOUT_SECONDS,
    DEFAULT_UPLOAD_TIMEOUT_SECONDS,
    HARD_MAX_BATCH_BYTES,
    HARD_MAX_FILE_BYTES,
    HARD_MAX_FILES_PER_BATCH,
    HARD_MAX_JOB_TIMEOUT_SECONDS,
    HARD_MAX_UPLOAD_TIMEOUT_SECONDS,
)

LOOPBACK_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765
MIN_PORT: Final = 1024
MAX_PORT: Final = 65535
PORT_ENV_VAR: Final = "CV_MASKING_PORT"
BOOTSTRAP_ENV_VAR: Final = "CV_MASKING_BOOTSTRAP_TOKEN"
MAX_FILE_ENV_VAR: Final = "CV_MASKING_MAX_FILE_BYTES"
MAX_FILES_ENV_VAR: Final = "CV_MASKING_MAX_FILES_PER_BATCH"
MAX_BATCH_ENV_VAR: Final = "CV_MASKING_MAX_BATCH_BYTES"
UPLOAD_TIMEOUT_ENV_VAR: Final = "CV_MASKING_UPLOAD_TIMEOUT_SECONDS"
JOB_TIMEOUT_ENV_VAR: Final = "CV_MASKING_JOB_TIMEOUT_SECONDS"


class ConfigError(ValueError):
    """Raised when runtime configuration is invalid."""


def _require_int(raw: str, name: str, minimum: int, maximum: int) -> int:
    if not (raw.isascii() and raw.isdigit()):
        raise ConfigError(f"{name} must be an integer between {minimum} and {maximum}")
    value = int(raw)
    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} must be an integer between {minimum} and {maximum}")
    return value


@dataclass(frozen=True, slots=True)
class Settings:
    port: int = DEFAULT_PORT
    max_file_bytes: int = HARD_MAX_FILE_BYTES
    max_files_per_batch: int = HARD_MAX_FILES_PER_BATCH
    max_batch_bytes: int = HARD_MAX_BATCH_BYTES
    upload_timeout_seconds: int = DEFAULT_UPLOAD_TIMEOUT_SECONDS
    job_timeout_seconds: int = DEFAULT_JOB_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        if isinstance(self.port, bool) or not MIN_PORT <= self.port <= MAX_PORT:
            raise ConfigError(f"port must be an integer between {MIN_PORT} and {MAX_PORT}")
        if (
            isinstance(self.max_file_bytes, bool)
            or not 1 <= self.max_file_bytes <= HARD_MAX_FILE_BYTES
        ):
            raise ConfigError("max_file_bytes is out of range")
        if (
            isinstance(self.max_files_per_batch, bool)
            or not 1 <= self.max_files_per_batch <= HARD_MAX_FILES_PER_BATCH
        ):
            raise ConfigError("max_files_per_batch is out of range")
        if (
            isinstance(self.max_batch_bytes, bool)
            or not 1 <= self.max_batch_bytes <= HARD_MAX_BATCH_BYTES
        ):
            raise ConfigError("max_batch_bytes is out of range")
        if (
            isinstance(self.upload_timeout_seconds, bool)
            or not 1 <= self.upload_timeout_seconds <= HARD_MAX_UPLOAD_TIMEOUT_SECONDS
        ):
            raise ConfigError("upload_timeout_seconds is out of range")
        if (
            isinstance(self.job_timeout_seconds, bool)
            or not 1 <= self.job_timeout_seconds <= HARD_MAX_JOB_TIMEOUT_SECONDS
        ):
            raise ConfigError("job_timeout_seconds is out of range")

    @property
    def host(self) -> str:
        return LOOPBACK_HOST


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    raw_port = env.get(PORT_ENV_VAR)
    port = (
        DEFAULT_PORT
        if raw_port is None
        else _require_int(raw_port, PORT_ENV_VAR, MIN_PORT, MAX_PORT)
    )
    return Settings(
        port=port,
        max_file_bytes=_optional_int(
            env, MAX_FILE_ENV_VAR, HARD_MAX_FILE_BYTES, 1, HARD_MAX_FILE_BYTES
        ),
        max_files_per_batch=_optional_int(
            env, MAX_FILES_ENV_VAR, HARD_MAX_FILES_PER_BATCH, 1, HARD_MAX_FILES_PER_BATCH
        ),
        max_batch_bytes=_optional_int(
            env, MAX_BATCH_ENV_VAR, HARD_MAX_BATCH_BYTES, 1, HARD_MAX_BATCH_BYTES
        ),
        upload_timeout_seconds=_optional_int(
            env,
            UPLOAD_TIMEOUT_ENV_VAR,
            DEFAULT_UPLOAD_TIMEOUT_SECONDS,
            1,
            HARD_MAX_UPLOAD_TIMEOUT_SECONDS,
        ),
        job_timeout_seconds=_optional_int(
            env,
            JOB_TIMEOUT_ENV_VAR,
            DEFAULT_JOB_TIMEOUT_SECONDS,
            1,
            HARD_MAX_JOB_TIMEOUT_SECONDS,
        ),
    )


def _optional_int(
    env: Mapping[str, str], name: str, default: int, minimum: int, maximum: int
) -> int:
    raw = env.get(name)
    if raw is None:
        return default
    return _require_int(raw, name, minimum, maximum)
