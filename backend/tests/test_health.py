import pytest
from fastapi.testclient import TestClient

from cv_masking import __version__
from cv_masking.api.app import create_app


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def test_health_returns_ok_and_version_only(client: TestClient) -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "version": __version__}


def test_health_rejects_non_get_methods(client: TestClient) -> None:
    response = client.post("/api/health")

    assert response.status_code == 405


@pytest.mark.parametrize(
    "path",
    ["/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"],
    ids=["swagger", "redoc", "openapi", "oauth2-redirect"],
)
def test_api_docs_are_disabled(client: TestClient, path: str) -> None:
    response = client.get(path)

    assert response.status_code == 404


def test_unknown_route_is_not_found(client: TestClient) -> None:
    response = client.get("/api/unknown")

    assert response.status_code == 404
