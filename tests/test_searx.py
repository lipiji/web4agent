"""Tests for SearXNG search + extract — httpx mocked, no real network."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web4agent.searx import _select_instances, search_searx

_SEARX_RESPONSE = {
    "query": "python web scraping",
    "number_of_results": 3,
    "results": [
        {
            "title": "Beautiful Soup Documentation",
            "url": "https://www.crummy.com/software/BeautifulSoup/",
            "content": "Beautiful Soup is a Python library for pulling data out of HTML.",
            "engine": "google",
            "engines": ["google", "duckduckgo"],
            "score": 0.95,
        },
        {
            "title": "Scrapy Tutorial",
            "url": "https://docs.scrapy.org/en/latest/intro/tutorial.html",
            "content": "Scrapy is a fast high-level web crawling framework.",
            "engine": "bing",
            "engines": ["bing"],
            "score": 0.82,
        },
    ],
}


def _mock_search_response(data=None):
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = data or _SEARX_RESPONSE
    resp.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=resp)
    return mock_client


# ── _select_instances ─────────────────────────────────────────────────────────


class TestSelectInstances:
    def test_custom_instance(self):
        instances = _select_instances("https://my-searx.example.com")
        assert instances == ["https://my-searx.example.com"]

    def test_public_pool_by_default(self):
        instances = _select_instances()
        assert len(instances) >= 3
        assert all(u.startswith("https://") for u in instances)
        assert not any(u.endswith("/search") for u in instances)


# ── search_searx ─────────────────────────────────────────────────────────────


class TestSearchSearx:
    @pytest.mark.asyncio
    async def test_returns_structured_results(self):
        with patch("web4agent.searx.httpx.AsyncClient", return_value=_mock_search_response()):
            results = await search_searx("python web scraping")

        assert len(results) == 2
        assert results[0]["title"] == "Beautiful Soup Documentation"
        assert results[0]["url"] == "https://www.crummy.com/software/BeautifulSoup/"
        assert "Beautiful Soup" in results[0]["snippet"]
        assert results[0]["engine"] == "google, duckduckgo"
        assert results[0]["score"] == 0.95

    @pytest.mark.asyncio
    async def test_respects_max_results(self):
        with patch("web4agent.searx.httpx.AsyncClient", return_value=_mock_search_response()):
            results = await search_searx("python", max_results=1)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_empty_results_on_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("connection refused"))

        with patch("web4agent.searx.httpx.AsyncClient", return_value=mock_client):
            results = await search_searx("query")

        assert results == []

    @pytest.mark.asyncio
    async def test_falls_back_to_next_instance(self):
        """When first instance fails, the second is tried."""
        # Only two instances; first fails at HTTP level, second succeeds.
        good = _mock_search_response()
        bad = _mock_search_response()
        bad.get = AsyncMock(side_effect=Exception("timeout"))

        clients = [bad, good]

        with patch("web4agent.searx._select_instances", return_value=["https://bad.searx", "https://good.searx"]):
            with patch("web4agent.searx.httpx.AsyncClient", side_effect=clients):
                results = await search_searx("query")

        assert len(results) == 2  # got results from good instance
        bad.get.assert_called_once()
        good.get.assert_called_once()

    @pytest.mark.asyncio
    async def test_uses_custom_instance_exclusively(self):
        """Custom instance should not fall back to public pool."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("down"))

        with patch("web4agent.searx.httpx.AsyncClient", return_value=mock_client):
            results = await search_searx("query", instance="https://my-searx.example.com")

        assert results == []

    @pytest.mark.asyncio
    async def test_json_payload_passed_in_query_params(self):
        with patch("web4agent.searx.httpx.AsyncClient", return_value=_mock_search_response()) as mock_cls_factory:
            # Actually just check call args directly
            pass

        mock_client_obj = _mock_search_response()
        mock_client_obj.get = AsyncMock(return_value=mock_client_obj.get.return_value)

        with patch("web4agent.searx.httpx.AsyncClient", return_value=mock_client_obj):
            await search_searx("test query", max_results=5, categories="news")

        call_args = mock_client_obj.get.call_args
        params = call_args[1].get("params", {})
        assert params["q"] == "test query"
        assert params["format"] == "json"
        assert params["categories"] == "news"

    @pytest.mark.asyncio
    async def test_handles_nonstandard_response_shape(self):
        data = {"results": [{"title": "T", "url": "https://u.com"}]}  # no engines/content/score
        with patch("web4agent.searx.httpx.AsyncClient", return_value=_mock_search_response(data)):
            results = await search_searx("q")

        assert len(results) == 1
        assert results[0]["snippet"] == ""
        assert results[0]["engine"] == ""
        assert results[0]["score"] is None
