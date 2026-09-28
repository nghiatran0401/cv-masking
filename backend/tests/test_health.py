from fastapi.testclient import TestClient

from cv_masking import __version__
from cv_masking.api.app import create_app
from http_support import LOOPBACK_BASE, app_client


def test_health_returns_ok_and_version_only() -> None:
    response = TestClient(create_app(), base_url=LOOPBACK_BASE).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}
    assert "Content-Security-Policy" in response.headers
    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["Cache-Control"] == "no-store"


def test_api_docs_are_disabled() -> None:
    bare = TestClient(create_app(), base_url=LOOPBACK_BASE)
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert bare.get(path).status_code == 403
    client = app_client(create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
