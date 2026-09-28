import pytest

from cv_masking.config import (
    DEFAULT_PORT,
    JOB_TIMEOUT_ENV_VAR,
    LOOPBACK_HOST,
    MAX_FILE_ENV_VAR,
    PORT_ENV_VAR,
    ConfigError,
    load_settings,
)
from cv_masking.domain.limits import (
    DEFAULT_JOB_TIMEOUT_SECONDS,
    HARD_MAX_FILE_BYTES,
    HARD_MAX_JOB_TIMEOUT_SECONDS,
)


def test_host_is_loopback_and_cannot_be_overridden_by_environment() -> None:
    assert LOOPBACK_HOST == "127.0.0.1"
    for env_name in ("CV_MASKING_HOST", "HOST", "UVICORN_HOST"):
        settings = load_settings({env_name: "0.0.0.0"})  # noqa: S104 - asserting it is ignored
        assert settings.host == LOOPBACK_HOST


def test_port_defaults_and_can_be_set() -> None:
    assert load_settings({}).port == DEFAULT_PORT == 8765
    assert load_settings({PORT_ENV_VAR: "9000"}).port == 9000


def test_file_limit_cannot_exceed_the_hard_cap() -> None:
    assert load_settings({}).max_file_bytes == HARD_MAX_FILE_BYTES
    assert load_settings({MAX_FILE_ENV_VAR: "1024"}).max_file_bytes == 1024
    with pytest.raises(ConfigError):
        load_settings({MAX_FILE_ENV_VAR: str(HARD_MAX_FILE_BYTES + 1)})


def test_invalid_ports_are_rejected() -> None:
    for raw in ("0", "1023", "65536", "", " 8765", "87a5", "٨٧٦٥"):
        with pytest.raises(ConfigError):
            load_settings({PORT_ENV_VAR: raw})


def test_job_timeout_defaults_and_cannot_exceed_the_hard_cap() -> None:
    assert load_settings({}).job_timeout_seconds == DEFAULT_JOB_TIMEOUT_SECONDS == 120
    assert load_settings({JOB_TIMEOUT_ENV_VAR: "30"}).job_timeout_seconds == 30
    assert HARD_MAX_JOB_TIMEOUT_SECONDS == 600
    for raw in ("0", str(HARD_MAX_JOB_TIMEOUT_SECONDS + 1), "", "1.5", "-5"):
        with pytest.raises(ConfigError):
            load_settings({JOB_TIMEOUT_ENV_VAR: raw})
