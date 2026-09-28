import os
from pathlib import Path

import pytest

from cv_masking import __main__ as entrypoint
from cv_masking.config import Settings
from cv_masking.desktop import (
    OPEN_BIN,
    InstanceLock,
    loopback_ui_url,
    open_loopback_browser,
    run_desktop,
)


def test_loopback_ui_url_rejects_a_hostile_token() -> None:
    assert loopback_ui_url(8765, None) == "http://127.0.0.1:8765/"
    assert loopback_ui_url(8765, "abc_DEF-123") == "http://127.0.0.1:8765/?bootstrap=abc_DEF-123"
    with pytest.raises(ValueError, match="bootstrap"):
        loopback_ui_url(8765, "http://evil.example")
    with pytest.raises(ValueError, match="port"):
        loopback_ui_url(80, None)


def test_instance_lock_is_exclusive(tmp_path: Path) -> None:
    path = tmp_path / "lock" / "instance.lock"
    first = InstanceLock(path)
    assert first.acquire() is True
    second = InstanceLock(path)
    assert second.acquire() is False
    first.close()
    third = InstanceLock(path)
    assert third.acquire() is True
    third.close()


def test_open_browser_uses_open_and_a_loopback_url(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_run(*args: object, **kwargs: object) -> None:
        assert args[0] == [OPEN_BIN, "http://127.0.0.1:8765/?bootstrap=token_value"]
        assert kwargs["check"] is True
        assert kwargs["timeout"] == 10

    monkeypatch.setattr("cv_masking.desktop.subprocess.run", fake_run)
    open_loopback_browser(8765, "token_value")


def test_desktop_without_ui_build_exits(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cv_masking.desktop.resolve_static_directory", lambda: None)
    monkeypatch.setattr("cv_masking.desktop.probe_health", lambda port: False)
    with pytest.raises(SystemExit, match="UI build missing"):
        run_desktop(open_browser=False, settings=Settings())


def test_desktop_opens_existing_instance_without_a_new_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    opened: list[tuple[int, str | None]] = []
    monkeypatch.setattr("cv_masking.desktop.resolve_static_directory", lambda: tmp_path)
    monkeypatch.setattr("cv_masking.desktop.probe_health", lambda port: True)
    monkeypatch.setattr(
        "cv_masking.desktop.open_loopback_browser",
        lambda port, bootstrap: opened.append((port, bootstrap)),
    )
    run_desktop(open_browser=True, settings=Settings())
    assert opened == [(8765, None)]


def test_desktop_flag_rejects_reload(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("cv_masking.__main__.run_desktop", lambda **kwargs: None)
    with pytest.raises(SystemExit, match="desktop or --reload"):
        entrypoint.main(["--desktop", "--reload"])


def test_desktop_flag_calls_run_desktop(monkeypatch: pytest.MonkeyPatch) -> None:
    called: dict[str, object] = {}

    def fake_desktop(*, open_browser: bool, settings: Settings) -> None:
        called["open_browser"] = open_browser
        called["host"] = settings.host

    monkeypatch.setattr("cv_masking.__main__.run_desktop", fake_desktop)
    monkeypatch.delenv("CV_MASKING_PORT", raising=False)
    entrypoint.main(["--desktop", "--no-browser"])
    assert called == {"open_browser": False, "host": "127.0.0.1"}


def test_launcher_script_stays_on_loopback() -> None:
    script = Path(__file__).resolve().parents[2] / "scripts" / "cv-masking.command"
    text = script.read_text(encoding="utf-8")
    assert "--desktop" in text
    assert ".".join(["0"] * 4) not in text
    assert "https://" not in text
    assert os.access(script, os.X_OK)
