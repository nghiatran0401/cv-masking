"""Loopback TestClient that presents a valid Host, Origin, session cookie, and CSRF header."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from cv_masking.api.security import CSRF_HEADER

LOOPBACK_BASE = "http://127.0.0.1:8765"
LOOPBACK_ORIGIN = "http://127.0.0.1:8765"


def authenticate_client(client: TestClient) -> TestClient:
    opened = client.get("/api/session")
    assert opened.status_code == 200
    client.headers[CSRF_HEADER] = opened.json()["csrf_token"]
    client.headers["Origin"] = LOOPBACK_ORIGIN
    return client


def app_client(app: FastAPI) -> TestClient:
    return authenticate_client(TestClient(app, base_url=LOOPBACK_BASE))
