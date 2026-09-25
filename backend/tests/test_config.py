import pytest

from cv_masking.config import (
    DEFAULT_PORT,
    LOOPBACK_HOST,
    PORT_ENV_VAR,
    ConfigError,
    load_settings,
)


def test_host_is_loopback_and_cannot_be_overridden_by_environment() -> None:
    assert LOOPBACK_HOST == "127.0.0.1"
    for env_name in ("CV_MASKING_HOST", "HOST", "UVICORN_HOST"):
        settings = load_settings({env_name: "0.0.0.0"})  # noqa: S104 - asserting it is ignored
        assert settings.host == LOOPBACK_HOST


def test_port_defaults_and_can_be_set() -> None:
    assert load_settings({}).port == DEFAULT_PORT == 8765
    assert load_settings({PORT_ENV_VAR: "9000"}).port == 9000


def test_invalid_ports_are_rejected() -> None:
    for raw in ("0", "1023", "65536", "", " 8765", "87a5", "٨٧٦٥"):
        with pytest.raises(ConfigError):
            load_settings({PORT_ENV_VAR: raw})
