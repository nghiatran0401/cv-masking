"""Runtime settings.

The bind host is a constant: the service must only ever listen on loopback, so
no setting, environment variable, or CLI flag can change it.
"""

import os
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

LOOPBACK_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8765
MIN_PORT: Final = 1024
MAX_PORT: Final = 65535
PORT_ENV_VAR: Final = "CV_MASKING_PORT"


class ConfigError(ValueError):
    """Raised when runtime configuration is invalid."""


@dataclass(frozen=True, slots=True)
class Settings:
    port: int = DEFAULT_PORT

    def __post_init__(self) -> None:
        if isinstance(self.port, bool) or not MIN_PORT <= self.port <= MAX_PORT:
            raise ConfigError(f"port must be an integer between {MIN_PORT} and {MAX_PORT}")

    @property
    def host(self) -> str:
        return LOOPBACK_HOST


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    raw_port = env.get(PORT_ENV_VAR)
    if raw_port is None:
        return Settings()
    if not (raw_port.isascii() and raw_port.isdigit()):
        raise ConfigError(f"{PORT_ENV_VAR} must be an integer between {MIN_PORT} and {MAX_PORT}")
    return Settings(port=int(raw_port))
