import re
from pathlib import Path

import pytest

from cv_masking.api.ui import PACKAGE_STATIC

_URL = re.compile(r"\b[a-z][a-z0-9+.-]*://[^\s\"'`<>]+", re.IGNORECASE)
_ALLOWED = re.compile(r"^https?://127\.0\.0\.1(?::\d+)?(?:/|$)")
_ALLOWED_IN_JS = (
    re.compile(r"^https://react\.dev/errors/"),
    re.compile(r"^http://www\.w3\.org/"),
)


def _urls_in(directory: Path) -> list[str]:
    found: list[str] = []
    for path in directory.rglob("*"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        found.extend(match.group(0) for match in _URL.finditer(text))
    return found


def test_scanner_flags_a_remote_script(tmp_path: Path) -> None:
    (tmp_path / "index.html").write_text(
        '<script src="https://cdn.example.invalid/app.js"></script>',
        encoding="utf-8",
    )
    assert _urls_in(tmp_path) == ["https://cdn.example.invalid/app.js"]


def test_packaged_ui_has_no_remote_urls() -> None:
    if not (PACKAGE_STATIC / "index.html").is_file():
        pytest.skip("UI not built")
    html_css: list[str] = []
    scripts: list[str] = []
    for path in PACKAGE_STATIC.rglob("*"):
        if not path.is_file():
            continue
        for url in _URL.findall(path.read_text(encoding="utf-8", errors="ignore")):
            if _ALLOWED.match(url) is not None:
                continue
            if path.suffix in {".html", ".css"}:
                html_css.append(url)
            elif path.suffix == ".js" and not any(rule.match(url) for rule in _ALLOWED_IN_JS):
                scripts.append(url)
    assert html_css == []
    assert scripts == []
