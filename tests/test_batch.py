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
        urls = ["https://a.com", "https://b.com", "https://c.com"]

        async def fake_read_url(url, strategy="auto", proxy=None):
            await asyncio.sleep(0)
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            results = await read_many(urls)

        assert [r.url for r in results] == urls

    @pytest.mark.asyncio
    async def test_single_failure_does_not_stop_others(self):
        urls = ["https://a.com", "https://b.com", "https://c.com"]

        async def fake_read_url(url, strategy="auto", proxy=None):
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
        urls = ["https://a.com", "https://b.com", "https://a.com"]
        call_count: dict[str, int] = {}

        async def fake_read_url(url, strategy="auto", proxy=None):
            call_count[url] = call_count.get(url, 0) + 1
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            results = await read_many(urls)

        assert call_count.get("https://a.com", 0) == 1
        assert len(results) == 3
        assert results[0].url == "https://a.com"
        assert results[2].url == "https://a.com"

    @pytest.mark.asyncio
    async def test_duplicate_results_are_same_object(self):
        urls = ["https://x.com", "https://x.com"]

        async def fake_read_url(url, strategy="auto", proxy=None):
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            results = await read_many(urls)

        assert results[0].url == results[1].url

    @pytest.mark.asyncio
    async def test_concurrency_respected(self):
        active: list[str] = []
        max_active: list[int] = []

        async def fake_read_url(url, strategy="auto", proxy=None):
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
        urls = ["https://ok.com", "https://explode.com"]

        async def fake_read_url(url, strategy="auto", proxy=None):
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
        received: list[str] = []

        async def fake_read_url(url, strategy="auto", proxy=None):
            received.append(strategy)
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            await read_many(["https://a.com", "https://b.com"], strategy="fast")

        assert all(s == "fast" for s in received)

    @pytest.mark.asyncio
    async def test_default_concurrency_by_strategy(self):
        from web4agent.batch import _STRATEGY_DEFAULT_CONCURRENCY
        assert _STRATEGY_DEFAULT_CONCURRENCY["fast"] >= 10
        assert _STRATEGY_DEFAULT_CONCURRENCY["browser"] <= 5

    # ── proxy rotation ─────────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_proxies_distributed_across_requests(self):
        """Each request receives a proxy from the list."""
        received_proxies: list[str | None] = []

        async def fake_read_url(url, strategy="auto", proxy=None):
            received_proxies.append(proxy)
            return _ok(url)

        urls = ["https://a.com", "https://b.com", "https://c.com"]
        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            await read_many(urls, proxies=["http://p1:8080", "http://p2:8080"])

        assert all(p is not None for p in received_proxies)
        # at least one proxy from the list was used
        assert any(p in ("http://p1:8080", "http://p2:8080") for p in received_proxies)

    @pytest.mark.asyncio
    async def test_no_proxies_passes_none(self):
        received_proxies: list[str | None] = []

        async def fake_read_url(url, strategy="auto", proxy=None):
            received_proxies.append(proxy)
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            from web4agent.batch import read_many
            await read_many(["https://a.com"], proxies=None)

        assert received_proxies[0] is None

    @pytest.mark.asyncio
    async def test_proxy_mark_success_on_success(self):
        """mark_success is called when result.success is True and proxy is set."""
        from unittest.mock import MagicMock
        from web4agent.proxy import ProxyRotator

        real_rotator = ProxyRotator(["http://p1:8080"])
        real_rotator.mark_success = MagicMock(wraps=real_rotator.mark_success)

        async def fake_read_url(url, strategy="auto", proxy=None):
            return _ok(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            with patch("web4agent.proxy.ProxyRotator", return_value=real_rotator):
                from web4agent.batch import read_many
                await read_many(["https://a.com"], proxies=["http://p1:8080"])

        real_rotator.mark_success.assert_called()

    @pytest.mark.asyncio
    async def test_proxy_mark_failed_on_failure(self):
        """mark_failed is called when result.success is False and proxy is set."""
        from unittest.mock import MagicMock
        from web4agent.proxy import ProxyRotator

        real_rotator = ProxyRotator(["http://p1:8080"])
        real_rotator.mark_failed = MagicMock(wraps=real_rotator.mark_failed)

        async def fake_read_url(url, strategy="auto", proxy=None):
            return _fail(url)

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            with patch("web4agent.proxy.ProxyRotator", return_value=real_rotator):
                from web4agent.batch import read_many
                await read_many(["https://a.com"], proxies=["http://p1:8080"])

        real_rotator.mark_failed.assert_called()

    @pytest.mark.asyncio
    async def test_proxy_mark_failed_on_exception(self):
        """mark_failed is called when read_url raises an exception and proxy is set."""
        from unittest.mock import MagicMock
        from web4agent.proxy import ProxyRotator

        real_rotator = ProxyRotator(["http://p1:8080"])
        real_rotator.mark_failed = MagicMock(wraps=real_rotator.mark_failed)

        async def fake_read_url(url, strategy="auto", proxy=None):
            raise RuntimeError("boom")

        with patch("web4agent.batch.read_url", side_effect=fake_read_url):
            with patch("web4agent.proxy.ProxyRotator", return_value=real_rotator):
                from web4agent.batch import read_many
                results = await read_many(["https://a.com"], proxies=["http://p1:8080"])

        assert results[0].success is False
        real_rotator.mark_failed.assert_called()
