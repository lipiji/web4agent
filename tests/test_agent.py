"""Tests for the agent-facing slim interface."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from webweb.models import FetchAttempt, WebReadResult
from webweb.utils import utc_now_iso


def _ok(url: str, title: str = "Page Title", text: str = "A" * 400, markdown: str = "# Heading\n\nContent") -> WebReadResult:
    return WebReadResult(
        url=url,
        final_url=url,
        title=title,
        text=text,
        markdown=markdown,
        status_code=200,
        success=True,
        strategy_used="fast",
        fetched_at=utc_now_iso(),
        elapsed_ms=50,
        attempts=[FetchAttempt(strategy="fast", success=True, status_code=200)],
    )


def _fail(url: str, error: str = "timeout") -> WebReadResult:
    return WebReadResult(
        url=url,
        success=False,
        error=error,
        strategy_used="fast",
        fetched_at=utc_now_iso(),
        attempts=[FetchAttempt(strategy="fast", success=False, error=error)],
    )


class TestAgentReadUrl:
    @pytest.mark.asyncio
    async def test_returns_dict(self):
        with patch("webweb.agent.read_url", AsyncMock(return_value=_ok("https://x.com"))):
            from webweb.agent import agent_read_url
            result = await agent_read_url("https://x.com")
        assert isinstance(result, dict)

    @pytest.mark.asyncio
    async def test_slim_keys_present(self):
        with patch("webweb.agent.read_url", AsyncMock(return_value=_ok("https://x.com"))):
            from webweb.agent import agent_read_url
            result = await agent_read_url("https://x.com")
        assert "url" in result
        assert "title" in result
        assert "content" in result
        assert "success" in result
        assert "strategy_used" in result
        assert "error" in result

    @pytest.mark.asyncio
    async def test_no_html_in_output(self):
        r = _ok("https://x.com")
        r = r.model_copy(update={"html": "<html>lots of html...</html>"})
        with patch("webweb.agent.read_url", AsyncMock(return_value=r)):
            from webweb.agent import agent_read_url
            result = await agent_read_url("https://x.com")
        assert "html" not in result

    @pytest.mark.asyncio
    async def test_content_uses_markdown_over_text(self):
        r = _ok("https://x.com", markdown="# Markdown Content", text="Plain text")
        with patch("webweb.agent.read_url", AsyncMock(return_value=r)):
            from webweb.agent import agent_read_url
            result = await agent_read_url("https://x.com")
        assert result["content"] is not None
        assert "Markdown" in result["content"]

    @pytest.mark.asyncio
    async def test_content_falls_back_to_text(self):
        r = _ok("https://x.com", markdown=None, text="Plain text content")
        r = r.model_copy(update={"markdown": None})
        with patch("webweb.agent.read_url", AsyncMock(return_value=r)):
            from webweb.agent import agent_read_url
            result = await agent_read_url("https://x.com")
        assert "Plain text" in (result["content"] or "")

    @pytest.mark.asyncio
    async def test_content_truncated(self):
        long_content = "x" * 20000
        r = _ok("https://x.com", markdown=long_content)
        with patch("webweb.agent.read_url", AsyncMock(return_value=r)):
            from webweb.agent import agent_read_url
            result = await agent_read_url("https://x.com")
        from webweb.config import AGENT_MAX_CONTENT_CHARS
        assert result["content"] is not None
        assert len(result["content"]) <= AGENT_MAX_CONTENT_CHARS + 50  # allow for ellipsis

    @pytest.mark.asyncio
    async def test_failure_result(self):
        with patch("webweb.agent.read_url", AsyncMock(return_value=_fail("https://x.com", "DNS error"))):
            from webweb.agent import agent_read_url
            result = await agent_read_url("https://x.com")
        assert result["success"] is False
        assert result["error"] == "DNS error"

    @pytest.mark.asyncio
    async def test_strategy_forwarded(self):
        with patch("webweb.agent.read_url", AsyncMock(return_value=_ok("https://x.com"))) as mock:
            from webweb.agent import agent_read_url
            await agent_read_url("https://x.com", strategy="browser")
        mock.assert_called_once_with("https://x.com", strategy="browser")


class TestAgentReadUrls:
    @pytest.mark.asyncio
    async def test_returns_summary_dict(self):
        results = [_ok("https://a.com"), _ok("https://b.com")]
        with patch("webweb.agent.read_many", AsyncMock(return_value=results)):
            from webweb.agent import agent_read_urls
            summary = await agent_read_urls(["https://a.com", "https://b.com"])
        assert "results" in summary
        assert "total" in summary
        assert "succeeded" in summary
        assert "failed" in summary

    @pytest.mark.asyncio
    async def test_counts_correct(self):
        results = [_ok("https://a.com"), _fail("https://b.com"), _ok("https://c.com")]
        with patch("webweb.agent.read_many", AsyncMock(return_value=results)):
            from webweb.agent import agent_read_urls
            summary = await agent_read_urls(["https://a.com", "https://b.com", "https://c.com"])
        assert summary["total"] == 3
        assert summary["succeeded"] == 2
        assert summary["failed"] == 1

    @pytest.mark.asyncio
    async def test_results_list_length_matches(self):
        urls = ["https://a.com", "https://b.com"]
        results = [_ok(u) for u in urls]
        with patch("webweb.agent.read_many", AsyncMock(return_value=results)):
            from webweb.agent import agent_read_urls
            summary = await agent_read_urls(urls)
        assert len(summary["results"]) == 2

    @pytest.mark.asyncio
    async def test_each_result_is_slim_dict(self):
        urls = ["https://a.com"]
        results = [_ok("https://a.com")]
        with patch("webweb.agent.read_many", AsyncMock(return_value=results)):
            from webweb.agent import agent_read_urls
            summary = await agent_read_urls(urls)
        item = summary["results"][0]
        assert "html" not in item
        assert "attempts" not in item
        assert "content" in item

    @pytest.mark.asyncio
    async def test_empty_urls_list(self):
        with patch("webweb.agent.read_many", AsyncMock(return_value=[])):
            from webweb.agent import agent_read_urls
            summary = await agent_read_urls([])
        assert summary["total"] == 0
        assert summary["succeeded"] == 0
        assert summary["failed"] == 0
