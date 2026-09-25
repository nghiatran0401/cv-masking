from fastapi.testclient import TestClient

from cv_masking import __version__
from cv_masking.api.app import create_app


def test_health_returns_ok_and_version_only() -> None:
    response = TestClient(create_app()).get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_api_docs_are_disabled() -> None:
    client = TestClient(create_app())
    for path in ("/docs", "/redoc", "/openapi.json"):
        assert client.get(path).status_code == 404
