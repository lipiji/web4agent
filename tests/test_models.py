"""Tests for Pydantic models."""

import pytest
from web4agent.models import FetchAttempt, WebReadResult


# ── FetchAttempt ───────────────────────────────────────────────────────────────

class TestFetchAttempt:
    def test_required_fields_only(self):
        a = FetchAttempt(strategy="fast", success=True)
        assert a.strategy == "fast"
        assert a.success is True
        assert a.status_code is None
        assert a.error is None
        assert a.elapsed_ms is None

    def test_all_fields(self):
        a = FetchAttempt(strategy="browser", success=False, status_code=403, error="Forbidden", elapsed_ms=512)
        assert a.status_code == 403
        assert a.error == "Forbidden"
        assert a.elapsed_ms == 512

    def test_success_false(self):
        a = FetchAttempt(strategy="crawl4ai", success=False, error="timeout")
        assert a.success is False
        assert a.error == "timeout"


# ── WebReadResult ──────────────────────────────────────────────────────────────

class TestWebReadResult:
    def test_minimal_construction(self):
        r = WebReadResult(url="https://example.com", fetched_at="2024-01-01T00:00:00+00:00")
        assert r.url == "https://example.com"
        assert r.success is False
        assert r.attempts == []
        assert r.metadata == {}
        assert r.title is None
        assert r.text is None
        assert r.markdown is None
        assert r.html is None
        assert r.error is None

    def test_mutable_defaults_are_independent(self):
        r1 = WebReadResult(url="https://a.com", fetched_at="t")
        r2 = WebReadResult(url="https://b.com", fetched_at="t")
        r1.attempts.append(FetchAttempt(strategy="fast", success=True))
        assert r2.attempts == [], "Field(default_factory=list) must not share state"

    def test_mutable_metadata_independent(self):
        r1 = WebReadResult(url="https://a.com", fetched_at="t")
        r2 = WebReadResult(url="https://b.com", fetched_at="t")
        r1.metadata["key"] = "value"
        assert r2.metadata == {}, "Field(default_factory=dict) must not share state"

    def test_full_construction(self):
        attempt = FetchAttempt(strategy="fast", success=True, status_code=200, elapsed_ms=100)
        r = WebReadResult(
            url="https://example.com",
            final_url="https://example.com/",
            title="Example Domain",
            text="Some content here",
            markdown="# Example Domain\nSome content here",
            html="<html><title>Example Domain</title></html>",
            status_code=200,
            success=True,
            strategy_used="fast",
            attempts=[attempt],
            fetched_at="2024-01-01T00:00:00+00:00",
            elapsed_ms=100,
            metadata={"foo": "bar"},
        )
        assert r.success is True
        assert r.title == "Example Domain"
        assert len(r.attempts) == 1
        assert r.metadata == {"foo": "bar"}

    def test_model_copy_immutability(self):
        r = WebReadResult(url="https://example.com", fetched_at="t", success=True)
        r2 = r.model_copy(update={"success": False, "error": "oops"})
        assert r2.success is False
        assert r2.error == "oops"
        assert r.success is True  # original unchanged

    def test_model_copy_preserves_fields(self):
        r = WebReadResult(url="https://x.com", fetched_at="t", title="X", elapsed_ms=99)
        r2 = r.model_copy(update={"success": True})
        assert r2.title == "X"
        assert r2.elapsed_ms == 99

    def test_error_result(self):
        r = WebReadResult(
            url="https://example.com",
            fetched_at="t",
            success=False,
            error="Connection refused",
            strategy_used="fast",
        )
        assert r.success is False
        assert "Connection" in r.error
