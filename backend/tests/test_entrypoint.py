from typing import Any

import pytest
import uvicorn

from cv_masking import __main__ as entrypoint
from cv_masking.config import ConfigError


class RunRecorder:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append((args, kwargs))


@pytest.fixture
def recorder(monkeypatch: pytest.MonkeyPatch) -> RunRecorder:
    recorder = RunRecorder()
    monkeypatch.setattr(uvicorn, "run", recorder)
    monkeypatch.delenv("CV_MASKING_PORT", raising=False)
    return recorder


def test_binds_loopback_on_default_port(recorder: RunRecorder) -> None:
    entrypoint.main([])

    assert len(recorder.calls) == 1
    args, kwargs = recorder.calls[0]
    assert args == ("cv_masking.api.app:create_app",)
    assert kwargs["factory"] is True
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8765
    assert kwargs["reload"] is False
    assert kwargs["reload_dirs"] is None
    assert kwargs["proxy_headers"] is False
    assert kwargs["server_header"] is False
    assert kwargs["access_log"] is False


def test_reload_watches_only_the_package(recorder: RunRecorder) -> None:
    entrypoint.main(["--reload"])

    _, kwargs = recorder.calls[0]
    assert kwargs["reload"] is True
    assert kwargs["reload_dirs"] == [str(entrypoint.PACKAGE_DIR)]
    assert kwargs["host"] == "127.0.0.1"


def test_hostile_host_environment_is_ignored(
    recorder: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("CV_MASKING_HOST", "HOST", "UVICORN_HOST"):
        monkeypatch.setenv(name, "0.0.0.0")  # noqa: S104 - asserting it is ignored

    entrypoint.main([])

    _, kwargs = recorder.calls[0]
    assert kwargs["host"] == "127.0.0.1"


def test_port_comes_from_environment(
    recorder: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CV_MASKING_PORT", "9000")

    entrypoint.main([])

    _, kwargs = recorder.calls[0]
    assert kwargs["port"] == 9000


def test_invalid_port_fails_before_server_starts(
    recorder: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("CV_MASKING_PORT", "80")

    with pytest.raises(ConfigError):
        entrypoint.main([])

    assert recorder.calls == []


@pytest.mark.parametrize(
    "argv",
    [["--host", "0.0.0.0"], ["--port", "9000"]],  # noqa: S104 - asserting it is rejected
    ids=["host-flag", "port-flag"],
)
def test_no_host_or_port_cli_flags(recorder: RunRecorder, argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        entrypoint.main(argv)

    assert exc_info.value.code == 2
    assert recorder.calls == []
