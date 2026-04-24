"""Tests for read_browser — Playwright mocked, no real browser."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from webweb.models import WebReadResult


RICH_HTML = """
<html>
<head><title>Browser Page</title></head>
<body>
  <article>
    <h1>Dynamic Content</h1>
    <p>This content was rendered by JavaScript and contains enough text to satisfy
    the minimum length requirement for a successful page fetch result. More words here.</p>
    <p>Additional paragraph with more content to ensure we exceed the threshold.</p>
  </article>
</body>
</html>
"""


def _make_playwright_mocks(html: str = RICH_HTML, status: int = 200, url: str = "https://example.com/"):
    """Build a stack of Playwright async mocks."""
    mock_response = MagicMock()
    mock_response.status = status

    mock_page = AsyncMock()
    mock_page.goto = AsyncMock(return_value=mock_response)
    mock_page.content = AsyncMock(return_value=html)
    mock_page.url = url
    mock_page.evaluate = AsyncMock(return_value=None)
    mock_page.close = AsyncMock()

    mock_context = AsyncMock()
    mock_context.new_page = AsyncMock(return_value=mock_page)
    mock_context.close = AsyncMock()

    mock_browser = MagicMock()
    mock_browser.is_connected = MagicMock(return_value=True)
    mock_browser.new_context = AsyncMock(return_value=mock_context)

    return mock_browser, mock_context, mock_page


class TestReadBrowser:
    @pytest.mark.asyncio
    async def test_returns_web_read_result(self):
        mock_browser, _, _ = _make_playwright_mocks()

        # Patch the manager's _ensure_browser directly
        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            result = await read_browser("https://example.com/")

        assert isinstance(result, WebReadResult)

    @pytest.mark.asyncio
    async def test_strategy_used_is_browser(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            result = await read_browser("https://example.com/")

        assert result.strategy_used == "browser"

    @pytest.mark.asyncio
    async def test_title_extracted(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            result = await read_browser("https://example.com/")

        # trafilatura may prefer <h1> over <title>; either is valid
        assert result.title is not None
        assert result.title in ("Browser Page", "Dynamic Content")

    @pytest.mark.asyncio
    async def test_html_stored(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            result = await read_browser("https://example.com/")

        assert result.html is not None
        assert "Dynamic Content" in result.html

    @pytest.mark.asyncio
    async def test_attempt_recorded(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            result = await read_browser("https://example.com/")

        assert len(result.attempts) == 1
        assert result.attempts[0].strategy == "browser"

    @pytest.mark.asyncio
    async def test_page_closed_after_fetch(self):
        mock_browser, mock_context, mock_page = _make_playwright_mocks()

        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            await read_browser("https://example.com/")

        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_page_closed_even_on_error(self):
        mock_browser, mock_context, mock_page = _make_playwright_mocks()
        mock_page.goto = AsyncMock(side_effect=Exception("navigation failed"))

        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            result = await read_browser("https://example.com/")

        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()
        assert result.success is False

    @pytest.mark.asyncio
    async def test_playwright_not_installed_returns_error(self):
        import sys

        # Simulate playwright not installed
        with patch("webweb.browser._manager._ensure_browser",
                   AsyncMock(side_effect=RuntimeError("Playwright is not installed"))):
            from webweb.browser import read_browser
            result = await read_browser("https://example.com/")

        assert result.success is False
        assert result.error is not None
        assert "Playwright" in result.error or "not installed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_navigation_error_returns_structured_result(self):
        mock_browser, _, mock_page = _make_playwright_mocks()
        mock_page.goto = AsyncMock(side_effect=Exception("net::ERR_CONNECTION_REFUSED"))

        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            result = await read_browser("https://example.com/")

        assert result.success is False
        assert result.error is not None
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    @pytest.mark.asyncio
    async def test_auto_scroll_called(self):
        mock_browser, _, mock_page = _make_playwright_mocks()

        with patch("webweb.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from webweb.browser import read_browser
            await read_browser("https://example.com/")

        # evaluate should have been called for the scroll script
        mock_page.evaluate.assert_called_once()
        scroll_script = mock_page.evaluate.call_args[0][0]
        assert "scrollBy" in scroll_script or "scroll" in scroll_script.lower()
