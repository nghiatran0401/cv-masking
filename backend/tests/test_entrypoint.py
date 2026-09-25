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


def test_binds_loopback_even_with_a_hostile_environment(
    recorder: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    for name in ("CV_MASKING_HOST", "HOST", "UVICORN_HOST"):
        monkeypatch.setenv(name, "0.0.0.0")  # noqa: S104 - asserting it is ignored
    entrypoint.main([])
    ((args, kwargs),) = recorder.calls
    assert args == ("cv_masking.api.app:create_runtime_app",)
    assert kwargs["host"] == "127.0.0.1"
    assert kwargs["port"] == 8765
    assert kwargs["proxy_headers"] is False
    assert kwargs["access_log"] is False


def test_invalid_port_or_host_flags_never_start_the_server(
    recorder: RunRecorder, monkeypatch: pytest.MonkeyPatch
) -> None:
    for argv in (["--host", "0.0.0.0"], ["--port", "9000"]):  # noqa: S104 - asserting rejected
        with pytest.raises(SystemExit):
            entrypoint.main(argv)
    monkeypatch.setenv("CV_MASKING_PORT", "80")
    with pytest.raises(ConfigError):
        entrypoint.main([])
    assert recorder.calls == []
