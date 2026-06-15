"""Tests for the FastAPI server — business logic mocked, no real network."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

fastapi = pytest.importorskip("fastapi", reason="fastapi not installed")
from fastapi.testclient import TestClient  # noqa: E402

from web4agent.models import FetchAttempt, WebReadResult  # noqa: E402
from web4agent.utils import utc_now_iso  # noqa: E402


def _ok(url: str = "https://example.com") -> WebReadResult:
    return WebReadResult(
        url=url,
        final_url=url,
        title="Test Page",
        text="A" * 400,
        markdown="# Test\n\nContent",
        status_code=200,
        success=True,
        strategy_used="fast",
        fetched_at=utc_now_iso(),
        elapsed_ms=50,
        attempts=[FetchAttempt(strategy="fast", success=True, status_code=200)],
    )


def _fail(url: str = "https://example.com") -> WebReadResult:
    return WebReadResult(
        url=url,
        success=False,
        error="timeout",
        strategy_used="fast",
        fetched_at=utc_now_iso(),
        attempts=[FetchAttempt(strategy="fast", success=False, error="timeout")],
    )


@pytest.fixture()
def client():
    from web4agent.server import app
    return TestClient(app)


# ── /health ────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_returns_ok_status(self, client):
        resp = client.get("/health")
        assert resp.json() == {"status": "ok"}


# ── POST /read ─────────────────────────────────────────────────────────────────

class TestApiRead:
    def test_successful_read(self, client):
        with patch("web4agent.server.read_url", AsyncMock(return_value=_ok())):
            resp = client.post("/read", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://example.com"
        assert data["success"] is True

    def test_default_strategy_is_auto(self, client):
        with patch("web4agent.server.read_url", AsyncMock(return_value=_ok())) as mock:
            client.post("/read", json={"url": "https://example.com"})
        mock.assert_called_once_with("https://example.com", strategy="auto")

    def test_custom_strategy_forwarded(self, client):
        with patch("web4agent.server.read_url", AsyncMock(return_value=_ok())) as mock:
            client.post("/read", json={"url": "https://example.com", "strategy": "fast"})
        mock.assert_called_once_with("https://example.com", strategy="fast")

    def test_failed_read_still_200(self, client):
        with patch("web4agent.server.read_url", AsyncMock(return_value=_fail())):
            resp = client.post("/read", json={"url": "https://example.com"})
        assert resp.status_code == 200
        assert resp.json()["success"] is False

    def test_missing_url_returns_422(self, client):
        resp = client.post("/read", json={})
        assert resp.status_code == 422

    def test_response_contains_strategy_used(self, client):
        with patch("web4agent.server.read_url", AsyncMock(return_value=_ok())):
            resp = client.post("/read", json={"url": "https://example.com"})
        assert "strategy_used" in resp.json()


# ── POST /read_many ────────────────────────────────────────────────────────────

class TestApiReadMany:
    def test_returns_list(self, client):
        results = [_ok("https://a.com"), _ok("https://b.com")]
        with patch("web4agent.server.read_many", AsyncMock(return_value=results)):
            resp = client.post("/read_many", json={"urls": ["https://a.com", "https://b.com"]})
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)
        assert len(resp.json()) == 2

    def test_default_concurrency_10(self, client):
        with patch("web4agent.server.read_many", AsyncMock(return_value=[])) as mock:
            client.post("/read_many", json={"urls": ["https://a.com"]})
        mock.assert_called_once_with(["https://a.com"], concurrency=10, strategy="auto")

    def test_custom_concurrency_forwarded(self, client):
        with patch("web4agent.server.read_many", AsyncMock(return_value=[])) as mock:
            client.post("/read_many", json={"urls": ["https://a.com"], "concurrency": 5})
        mock.assert_called_once_with(["https://a.com"], concurrency=5, strategy="auto")

    def test_empty_urls_returns_empty_list(self, client):
        with patch("web4agent.server.read_many", AsyncMock(return_value=[])):
            resp = client.post("/read_many", json={"urls": []})
        assert resp.status_code == 200
        assert resp.json() == []

    def test_missing_urls_returns_422(self, client):
        resp = client.post("/read_many", json={})
        assert resp.status_code == 422


# ── POST /discover_links ───────────────────────────────────────────────────────

class TestApiDiscoverLinks:
    def test_returns_link_list(self, client):
        links = ["https://example.com/a", "https://example.com/b"]
        with patch("web4agent.server.discover_links", AsyncMock(return_value=links)):
            resp = client.post("/discover_links", json={"url": "https://example.com"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["url"] == "https://example.com"
        assert data["links"] == links
        assert data["count"] == 2

    def test_default_same_domain_true(self, client):
        with patch("web4agent.server.discover_links", AsyncMock(return_value=[])) as mock:
            client.post("/discover_links", json={"url": "https://example.com"})
        mock.assert_called_once_with("https://example.com", same_domain=True, max_links=100)

    def test_same_domain_false(self, client):
        with patch("web4agent.server.discover_links", AsyncMock(return_value=[])) as mock:
            client.post("/discover_links", json={"url": "https://example.com", "same_domain": False})
        mock.assert_called_once_with("https://example.com", same_domain=False, max_links=100)

    def test_custom_max_links(self, client):
        with patch("web4agent.server.discover_links", AsyncMock(return_value=[])) as mock:
            client.post("/discover_links", json={"url": "https://example.com", "max_links": 50})
        mock.assert_called_once_with("https://example.com", same_domain=True, max_links=50)

    def test_missing_url_returns_422(self, client):
        resp = client.post("/discover_links", json={})
        assert resp.status_code == 422
