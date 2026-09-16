"""Security unit tests for LocalhostOriginMiddleware.

Verifies protection against drive-by cross-origin attacks, external website DNS-rebinding,
and malicious cross-site POST/WebSocket invocations on local APIs.
"""
import pytest
from starlette.testclient import TestClient

from src.web.server import app


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


def test_allowed_local_origin_succeeds(client: TestClient) -> None:
    """Verify standard requests from localhost and 127.0.0.1 origins are allowed."""
    for origin in ("http://127.0.0.1:8000", "http://localhost:8000"):
        res = client.get("/api/health", headers={"Origin": origin})
        assert res.status_code == 200
        assert res.json().get("status") == "ok"


def test_forbidden_external_origin_blocked(client: TestClient) -> None:
    """Verify requests originating from external websites receive 403 Forbidden."""
    evil_origins = [
        "https://evil.com",
        "http://malicious-site.org:8080",
        "https://attacker.io",
        "http://192.168.1.100:8000",
    ]
    for origin in evil_origins:
        res = client.get("/api/health", headers={"Origin": origin})
        assert res.status_code == 403
        assert "Forbidden" in res.json().get("error", "")


def test_state_changing_request_with_external_referer_blocked(client: TestClient) -> None:
    """Verify POST/PUT/DELETE requests with external referer headers receive 403 Forbidden."""
    res = client.post(
        "/api/chat/clear",
        headers={"Referer": "https://malicious-tracker.com/exploit"},
    )
    assert res.status_code == 403
    assert "Forbidden" in res.json().get("error", "")


def test_state_changing_request_with_local_referer_allowed(client: TestClient) -> None:
    """Verify POST/PUT/DELETE requests with local referer headers are permitted."""
    res = client.post(
        "/api/chat/clear",
        headers={"Referer": "http://127.0.0.1:8000/"},
    )
    # Status should be 200 (or non-403), indicating successful origin validation
    assert res.status_code == 200
