import pytest

from cv_masking.config import (
    DEFAULT_PORT,
    LOOPBACK_HOST,
    MAX_PORT,
    MIN_PORT,
    PORT_ENV_VAR,
    ConfigError,
    Settings,
    load_settings,
)


def test_host_is_loopback_constant() -> None:
    assert LOOPBACK_HOST == "127.0.0.1"
    assert Settings().host == LOOPBACK_HOST


def test_default_port_when_env_unset() -> None:
    assert load_settings({}).port == DEFAULT_PORT == 8765


@pytest.mark.parametrize("port", [MIN_PORT, 8765, MAX_PORT], ids=["min", "default", "max"])
def test_valid_ports_are_accepted(port: int) -> None:
    assert load_settings({PORT_ENV_VAR: str(port)}).port == port


@pytest.mark.parametrize(
    "raw",
    ["0", "80", "1023", "65536", "-1", "", " 8765", "8765 ", "87a5", "8765.0", "٨٧٦٥"],
    ids=[
        "zero",
        "privileged",
        "below-min",
        "above-max",
        "negative",
        "empty",
        "leading-space",
        "trailing-space",
        "non-numeric",
        "float",
        "non-ascii-digits",
    ],
)
def test_invalid_ports_are_rejected(raw: str) -> None:
    with pytest.raises(ConfigError):
        load_settings({PORT_ENV_VAR: raw})


def test_boolean_port_is_rejected() -> None:
    with pytest.raises(ConfigError):
        Settings(port=True)


@pytest.mark.parametrize(
    "env_name",
    ["CV_MASKING_HOST", "HOST", "UVICORN_HOST"],
)
def test_host_cannot_be_overridden_by_environment(env_name: str) -> None:
    settings = load_settings({env_name: "0.0.0.0"})  # noqa: S104 - asserting it is ignored

    assert settings.host == LOOPBACK_HOST


def test_settings_are_immutable() -> None:
    settings = Settings()

    with pytest.raises(AttributeError):
        settings.port = 9000  # type: ignore[misc]
