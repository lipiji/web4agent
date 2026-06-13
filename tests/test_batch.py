"""Tests for concurrent batch fetching."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from web4agent.models import FetchAttempt, WebReadResult
from web4agent.utils import utc_now_iso


def _ok(url: str, text: str = "A" * 400) -> WebReadResult:
    return WebReadResult(
        url=url, fetched_at=utc_now_iso(), success=True,
        text=text, status_code=200,
        attempts=[FetchAttempt(strategy="fast", success=True)],
    )


def _fail(url: str, error: str = "timeout") -> WebReadResult:
    return WebReadResult(
        url=url, fetched_at=utc_now_iso(), success=False,
        error=error,
        attempts=[FetchAttempt(strategy="fast", success=False, error=error)],
    )


class TestReadMany:
    @pytest.mark.asyncio
    async def test_returns_results_in_input_order(self):
        urls = [
            "https://a.com",
            "https://b.com",
            "https://c.com",
        ]

        async def fake_read_url(url, strategy="auto"):
            await asyncio.sleep(0)  # yield
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            results = await read_many(urls)

        assert [r.url for r in results] == urls

    @pytest.mark.asyncio
    async def test_single_failure_does_not_stop_others(self):
        urls = ["https://a.com", "https://b.com", "https://c.com"]

        async def fake_read_url(url, strategy="auto"):
            if url == "https://b.com":
                return _fail(url, error="network error")
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            results = await read_many(urls)

        assert results[0].success is True
        assert results[1].success is False
        assert results[2].success is True

    @pytest.mark.asyncio
    async def test_deduplicates_urls(self):
        urls = ["https://a.com", "https://b.com", "https://a.com"]  # a duplicated
        call_count = {}

        async def fake_read_url(url, strategy="auto"):
            call_count[url] = call_count.get(url, 0) + 1
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            results = await read_many(urls)

        # a.com fetched only once
        assert call_count.get("https://a.com", 0) == 1
        # result list still has 3 entries matching input
        assert len(results) == 3
        assert results[0].url == "https://a.com"
        assert results[2].url == "https://a.com"

    @pytest.mark.asyncio
    async def test_duplicate_results_are_same_object(self):
        urls = ["https://x.com", "https://x.com"]

        async def fake_read_url(url, strategy="auto"):
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            results = await read_many(urls)

        assert results[0].url == results[1].url

    @pytest.mark.asyncio
    async def test_concurrency_respected(self):
        """Verify semaphore limits simultaneous calls."""
        active = []
        max_active = []

        async def fake_read_url(url, strategy="auto"):
            active.append(url)
            max_active.append(len(active))
            await asyncio.sleep(0.01)
            active.remove(url)
            return _ok(url)

        urls = [f"https://site{i}.com" for i in range(10)]

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            await read_many(urls, concurrency=3)

        assert max(max_active) <= 3

    @pytest.mark.asyncio
    async def test_exception_in_read_url_caught(self):
        """Unexpected exception inside read_url must not crash read_many."""
        urls = ["https://ok.com", "https://explode.com"]

        async def fake_read_url(url, strategy="auto"):
            if "explode" in url:
                raise RuntimeError("unexpected boom")
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            results = await read_many(urls)

        assert results[0].success is True
        assert results[1].success is False
        assert results[1].error is not None

    @pytest.mark.asyncio
    async def test_empty_list_returns_empty(self):
        from web4agent.batch import read_many
        results = await read_many([])
        assert results == []

    @pytest.mark.asyncio
    async def test_strategy_passed_to_read_url(self):
        received_strategies = []

        async def fake_read_url(url, strategy="auto"):
            received_strategies.append(strategy)
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            await read_many(["https://a.com", "https://b.com"], strategy="fast")

        assert all(s == "fast" for s in received_strategies)

    @pytest.mark.asyncio
    async def test_default_concurrency_by_strategy(self):
        """Default concurrency should differ by strategy."""
        from web4agent.batch import _STRATEGY_DEFAULT_CONCURRENCY
        assert _STRATEGY_DEFAULT_CONCURRENCY["fast"] >= 10
        assert _STRATEGY_DEFAULT_CONCURRENCY["browser"] <= 5
