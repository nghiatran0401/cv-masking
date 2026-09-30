"""Stage 15: same-origin UI, bootstrap token, public HTML/assets only."""

from pathlib import Path

from fastapi.testclient import TestClient

from cv_masking.api.app import create_app
from cv_masking.api.ui import is_public_ui_path
from cv_masking.config import SOURCE_CV_HOST
from cv_masking.domain.codes import ErrorCode
from http_support import LOOPBACK_BASE

BOOTSTRAP = "stage15-bootstrap-token_value"


def _ui(directory: Path) -> Path:
    assets = directory / "assets"
    assets.mkdir()
    (directory / "index.html").write_text(
        "<!doctype html><title>synthetic-ui</title>", encoding="utf-8"
    )
    (assets / "app.js").write_text("console.log('synthetic-ui');\n", encoding="utf-8")
    return directory


def test_index_and_assets_are_public(tmp_path: Path) -> None:
    client = TestClient(create_app(static_directory=_ui(tmp_path)), base_url=LOOPBACK_BASE)
    page = client.get("/")
    assert page.status_code == 200
    assert "synthetic-ui" in page.text
    csp = page.headers["Content-Security-Policy"]
    allowed_origin = f"https://{SOURCE_CV_HOST}"
    assert csp.startswith("default-src 'self'")
    assert f"connect-src 'self' {allowed_origin}" in csp
    assert "frame-src 'self' blob:" in csp
    assert "object-src 'none'" in csp
    assert "*" not in csp
    assert "://" not in SOURCE_CV_HOST
    assert "https:" not in csp.replace(allowed_origin, "")
    script = client.get("/assets/app.js")
    assert script.status_code == 200
    assert "synthetic-ui" in script.text


def test_ui_path_traversal_is_not_public() -> None:
    assert is_public_ui_path("GET", "/assets/../index.html") is False
    assert is_public_ui_path("GET", "/assets/app.js") is True
    assert is_public_ui_path("POST", "/") is False


def test_session_requires_bootstrap_once(tmp_path: Path) -> None:
    app = create_app(static_directory=_ui(tmp_path), bootstrap_token=BOOTSTRAP)
    bare = TestClient(app, base_url=LOOPBACK_BASE)
    missing = bare.get("/api/session")
    assert missing.status_code == 403
    assert missing.json() == {"code": ErrorCode.SECURITY_TOKEN_INVALID.value}
    assert BOOTSTRAP not in missing.text
    wrong = bare.get("/api/session", params={"bootstrap": "wrong-token"})
    assert wrong.status_code == 403
    assert "wrong-token" not in wrong.text
    opened = bare.get("/api/session", params={"bootstrap": BOOTSTRAP})
    assert opened.status_code == 200
    assert "csrf_token" in opened.json()
    replay = TestClient(app, base_url=LOOPBACK_BASE)
    reused = replay.get("/api/session", params={"bootstrap": BOOTSTRAP})
    assert reused.status_code == 403
    cookie = opened.cookies.get("cv_masking_session")
    assert cookie is not None
    replay.cookies.set("cv_masking_session", cookie)
    refresh = replay.get("/api/session")
    assert refresh.status_code == 200


def test_api_still_needs_a_session_when_ui_is_public(tmp_path: Path) -> None:
    client = TestClient(create_app(static_directory=_ui(tmp_path)), base_url=LOOPBACK_BASE)
    response = client.get("/api/batches/00000000-0000-4000-8000-000000000001")
    assert response.status_code == 403
    assert response.json()["code"] == ErrorCode.SECURITY_TOKEN_INVALID.value
