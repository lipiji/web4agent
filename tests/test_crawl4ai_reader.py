"""Tests for read_crawl4ai — crawl4ai mocked via sys.modules."""

from __future__ import annotations

import sys
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web4agent.models import WebReadResult


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_crawl_result(
    success: bool = True,
    markdown_text: str = "# Heading\n\nContent " * 30,
    html: str = "<html><head><title>Crawl Page</title></head><body></body></html>",
    url: str = "https://example.com/",
    error_message: str | None = None,
) -> MagicMock:
    result = MagicMock()
    result.success = success
    result.url = url
    result.html = html
    result.error_message = error_message
    md = MagicMock()
    md.raw_markdown = markdown_text
    md.fit_markdown = markdown_text
    result.markdown = md
    return result


def _make_mock_crawl4ai_modules(crawler_result: MagicMock):
    """Build fake crawl4ai + submodule mocks and return (modules_dict, mock_crawler)."""
    mock_crawler = AsyncMock()
    mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
    mock_crawler.__aexit__ = AsyncMock(return_value=False)
    mock_crawler.arun = AsyncMock(return_value=crawler_result)

    mock_crawler_cls = MagicMock(return_value=mock_crawler)

    crawl4ai_mod = ModuleType("crawl4ai")
    crawl4ai_mod.AsyncWebCrawler = mock_crawler_cls
    crawl4ai_mod.BrowserConfig = MagicMock()
    crawl4ai_mod.CrawlerRunConfig = MagicMock()

    md_mod = ModuleType("crawl4ai.markdown_generation_strategy")
    md_mod.DefaultMarkdownGenerator = MagicMock()

    return {
        "crawl4ai": crawl4ai_mod,
        "crawl4ai.markdown_generation_strategy": md_mod,
    }, mock_crawler


class TestReadCrawl4ai:
    @pytest.mark.asyncio
    async def test_crawl4ai_not_installed_returns_error(self):
        """ImportError must produce a structured failure result, not raise."""
        # Remove crawl4ai from sys.modules so the lazy import fails
        saved = {k: sys.modules.pop(k) for k in list(sys.modules) if k.startswith("crawl4ai")}
        try:
            with patch.dict("sys.modules", {"crawl4ai": None, "crawl4ai.markdown_generation_strategy": None}):
                import importlib
                import web4agent.crawl4ai_reader as mod
                importlib.reload(mod)
                result = await mod.read_crawl4ai("https://example.com/")
        finally:
            sys.modules.update(saved)

        assert result.success is False
        assert result.error is not None
        assert result.strategy_used == "crawl4ai"

    @pytest.mark.asyncio
    async def test_successful_fetch(self):
        mods, _ = _make_mock_crawl4ai_modules(_make_crawl_result())
        with patch.dict("sys.modules", mods):
            import importlib
            import web4agent.crawl4ai_reader as mod
            importlib.reload(mod)
            result = await mod.read_crawl4ai("https://example.com/")

        assert isinstance(result, WebReadResult)
        assert result.success is True
        assert result.strategy_used == "crawl4ai"

    @pytest.mark.asyncio
    async def test_markdown_extracted(self):
        mods, _ = _make_mock_crawl4ai_modules(
            _make_crawl_result(markdown_text="# My Page\n\nHello world content")
        )
        with patch.dict("sys.modules", mods):
            import importlib
            import web4agent.crawl4ai_reader as mod
            importlib.reload(mod)
            result = await mod.read_crawl4ai("https://example.com/")

        assert result.markdown is not None
        assert "My Page" in result.markdown

    @pytest.mark.asyncio
    async def test_title_extracted_from_html(self):
        mods, _ = _make_mock_crawl4ai_modules(
            _make_crawl_result(html="<html><head><title>Crawl4AI Title</title></head></html>")
        )
        with patch.dict("sys.modules", mods):
            import importlib
            import web4agent.crawl4ai_reader as mod
            importlib.reload(mod)
            result = await mod.read_crawl4ai("https://example.com/")

        assert result.title == "Crawl4AI Title"

    @pytest.mark.asyncio
    async def test_crawl_failure_returns_error(self):
        mods, _ = _make_mock_crawl4ai_modules(
            _make_crawl_result(success=False, error_message="Page blocked")
        )
        with patch.dict("sys.modules", mods):
            import importlib
            import web4agent.crawl4ai_reader as mod
            importlib.reload(mod)
            result = await mod.read_crawl4ai("https://example.com/")

        assert result.success is False
        assert result.error is not None
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    @pytest.mark.asyncio
    async def test_exception_returns_structured_error(self):
        mock_crawler = AsyncMock()
        mock_crawler.__aenter__ = AsyncMock(return_value=mock_crawler)
        mock_crawler.__aexit__ = AsyncMock(return_value=False)
        mock_crawler.arun = AsyncMock(side_effect=RuntimeError("crawler crashed"))

        crawl4ai_mod = ModuleType("crawl4ai")
        crawl4ai_mod.AsyncWebCrawler = MagicMock(return_value=mock_crawler)
        crawl4ai_mod.BrowserConfig = MagicMock()
        crawl4ai_mod.CrawlerRunConfig = MagicMock()
        md_mod = ModuleType("crawl4ai.markdown_generation_strategy")
        md_mod.DefaultMarkdownGenerator = MagicMock()

        with patch.dict("sys.modules", {"crawl4ai": crawl4ai_mod, "crawl4ai.markdown_generation_strategy": md_mod}):
            import importlib
            import web4agent.crawl4ai_reader as mod
            importlib.reload(mod)
            result = await mod.read_crawl4ai("https://example.com/")

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_elapsed_ms_set(self):
        mods, _ = _make_mock_crawl4ai_modules(_make_crawl_result())
        with patch.dict("sys.modules", mods):
            import importlib
            import web4agent.crawl4ai_reader as mod
            importlib.reload(mod)
            result = await mod.read_crawl4ai("https://example.com/")

        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_fetched_at_is_set(self):
        mods, _ = _make_mock_crawl4ai_modules(_make_crawl_result())
        with patch.dict("sys.modules", mods):
            import importlib
            import web4agent.crawl4ai_reader as mod
            importlib.reload(mod)
            result = await mod.read_crawl4ai("https://example.com/")

        assert result.fetched_at != ""

    @pytest.mark.asyncio
    async def test_attempt_recorded(self):
        mods, _ = _make_mock_crawl4ai_modules(_make_crawl_result())
        with patch.dict("sys.modules", mods):
            import importlib
            import web4agent.crawl4ai_reader as mod
            importlib.reload(mod)
            result = await mod.read_crawl4ai("https://example.com/")

        assert len(result.attempts) == 1
        assert result.attempts[0].strategy == "crawl4ai"
