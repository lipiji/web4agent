"""Tests for read_browser — Playwright mocked, no real browser."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web4agent.models import WebReadResult


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
        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/")

        assert isinstance(result, WebReadResult)

    @pytest.mark.asyncio
    async def test_strategy_used_is_browser(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/")

        assert result.strategy_used == "browser"

    @pytest.mark.asyncio
    async def test_title_extracted(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/")

        # trafilatura may prefer <h1> over <title>; either is valid
        assert result.title is not None
        assert result.title in ("Browser Page", "Dynamic Content")

    @pytest.mark.asyncio
    async def test_html_stored(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/")

        assert result.html is not None
        assert "Dynamic Content" in result.html

    @pytest.mark.asyncio
    async def test_attempt_recorded(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/")

        assert len(result.attempts) == 1
        assert result.attempts[0].strategy == "browser"

    @pytest.mark.asyncio
    async def test_page_closed_after_fetch(self):
        mock_browser, mock_context, mock_page = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            await read_browser("https://example.com/")

        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_page_closed_even_on_error(self):
        mock_browser, mock_context, mock_page = _make_playwright_mocks()
        mock_page.goto = AsyncMock(side_effect=Exception("navigation failed"))

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/")

        mock_page.close.assert_called_once()
        mock_context.close.assert_called_once()
        assert result.success is False

    @pytest.mark.asyncio
    async def test_playwright_not_installed_returns_error(self):
        import sys

        # Simulate playwright not installed
        with patch("web4agent.browser._manager._ensure_browser",
                   AsyncMock(side_effect=RuntimeError("Playwright is not installed"))):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/")

        assert result.success is False
        assert result.error is not None
        assert "Playwright" in result.error or "not installed" in result.error.lower()

    @pytest.mark.asyncio
    async def test_navigation_error_returns_structured_result(self):
        mock_browser, _, mock_page = _make_playwright_mocks()
        mock_page.goto = AsyncMock(side_effect=Exception("net::ERR_CONNECTION_REFUSED"))

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/")

        assert result.success is False
        assert result.error is not None
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    @pytest.mark.asyncio
    async def test_auto_scroll_called(self):
        mock_browser, _, mock_page = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            await read_browser("https://example.com/")

        mock_page.evaluate.assert_called_once()
        scroll_script = mock_page.evaluate.call_args[0][0]
        assert "scrollBy" in scroll_script or "scroll" in scroll_script.lower()

    @pytest.mark.asyncio
    async def test_screenshot_captured_when_requested(self):
        mock_browser, _, mock_page = _make_playwright_mocks()
        mock_page.screenshot = AsyncMock(return_value=b"PNG_BYTES")

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            result = await read_browser("https://example.com/", screenshot=True)

        assert "screenshot_b64" in result.metadata
        mock_page.screenshot.assert_called_once_with(full_page=True)

    @pytest.mark.asyncio
    async def test_proxy_forwarded_to_new_context(self):
        mock_browser, mock_context, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            await read_browser("https://example.com/", proxy="http://p:8080")

        call_kwargs = mock_browser.new_context.call_args[1]
        assert call_kwargs.get("proxy") == {"server": "http://p:8080"}

    @pytest.mark.asyncio
    async def test_no_proxy_passes_none_to_context(self):
        mock_browser, mock_context, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            await read_browser("https://example.com/")

        call_kwargs = mock_browser.new_context.call_args[1]
        assert call_kwargs.get("proxy") is None

    @pytest.mark.asyncio
    async def test_canvas_noise_script_injected(self):
        mock_browser, mock_context, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            from web4agent.browser import read_browser
            await read_browser("https://example.com/")

        mock_context.add_init_script.assert_called_once()
        script_arg = mock_context.add_init_script.call_args[0][0]
        assert "canvas" in script_arg.lower() or "getContext" in script_arg


# ── Helper functions ────────────────────────────────────────────────────────────

class TestGetUa:
    def test_returns_string(self):
        from web4agent.browser import _get_ua
        ua = _get_ua()
        assert isinstance(ua, str)
        assert len(ua) > 0

    def test_contains_chrome(self):
        from web4agent.browser import _get_ua
        ua = _get_ua()
        assert "Chrome" in ua or "Mozilla" in ua

    def test_fallback_when_browserforge_absent(self):
        from web4agent.browser import _get_ua
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "browserforge" in name:
                raise ImportError("no browserforge")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            ua = _get_ua()
        assert "Chrome" in ua


class TestImportPlaywright:
    def test_returns_callable(self):
        from web4agent.browser import _import_playwright
        fn = _import_playwright()
        assert callable(fn)

    def test_raises_runtime_error_when_nothing_installed(self):
        from web4agent.browser import _import_playwright
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "playwright" in name or "patchright" in name:
                raise ImportError("not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with pytest.raises(RuntimeError, match="No browser driver found"):
                _import_playwright()

    def test_falls_back_to_playwright_when_patchright_missing(self):
        from web4agent.browser import _import_playwright
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if "patchright" in name:
                raise ImportError("no patchright")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            fn = _import_playwright()
        assert callable(fn)


class TestCloseBrowser:
    @pytest.mark.asyncio
    async def test_close_browser_calls_manager_close(self):
        with patch("web4agent.browser._manager.close", AsyncMock()) as mock_close:
            from web4agent.browser import close_browser
            await close_browser()
        mock_close.assert_called_once()


# ── _BrowserManager internals ─────────────────────────────────────────────────


class TestBrowserManager:
    def _make_pw_mocks(self):
        mock_browser = MagicMock()
        mock_browser.is_connected = MagicMock(return_value=True)

        mock_pw = AsyncMock()
        mock_pw.chromium.launch = AsyncMock(return_value=mock_browser)

        mock_pw_cm = MagicMock()
        mock_pw_cm.start = AsyncMock(return_value=mock_pw)

        mock_async_playwright_fn = MagicMock(return_value=mock_pw_cm)
        return mock_async_playwright_fn, mock_pw, mock_browser

    @pytest.mark.asyncio
    async def test_ensure_browser_launches_when_none(self):
        from web4agent.browser import _BrowserManager
        manager = _BrowserManager()
        mock_fn, mock_pw, mock_browser = self._make_pw_mocks()

        with patch("web4agent.browser._import_playwright", return_value=mock_fn):
            browser = await manager._ensure_browser()

        assert browser is mock_browser
        mock_pw.chromium.launch.assert_called_once()

    @pytest.mark.asyncio
    async def test_ensure_browser_reconnects_when_disconnected(self):
        from web4agent.browser import _BrowserManager
        manager = _BrowserManager()

        old_playwright = AsyncMock()
        old_playwright.stop = AsyncMock()
        old_browser = MagicMock()
        old_browser.is_connected = MagicMock(return_value=False)
        manager._playwright = old_playwright
        manager._browser = old_browser

        mock_fn, _, new_browser = self._make_pw_mocks()

        with patch("web4agent.browser._import_playwright", return_value=mock_fn):
            browser = await manager._ensure_browser()

        old_playwright.stop.assert_called_once()
        assert browser is new_browser

    @pytest.mark.asyncio
    async def test_ensure_browser_handles_playwright_stop_exception(self):
        """Exception from old playwright.stop() should be swallowed and reconnect succeeds."""
        from web4agent.browser import _BrowserManager
        manager = _BrowserManager()

        old_playwright = AsyncMock()
        old_playwright.stop = AsyncMock(side_effect=Exception("stop failed"))
        old_browser = MagicMock()
        old_browser.is_connected = MagicMock(return_value=False)
        manager._playwright = old_playwright
        manager._browser = old_browser

        mock_fn, _, new_browser = self._make_pw_mocks()

        with patch("web4agent.browser._import_playwright", return_value=mock_fn):
            browser = await manager._ensure_browser()

        assert browser is new_browser

    @pytest.mark.asyncio
    async def test_ensure_browser_reuses_connected_browser(self):
        from web4agent.browser import _BrowserManager
        manager = _BrowserManager()

        existing = MagicMock()
        existing.is_connected = MagicMock(return_value=True)
        manager._browser = existing

        browser = await manager._ensure_browser()
        assert browser is existing

    @pytest.mark.asyncio
    async def test_close_clears_browser_and_playwright(self):
        from web4agent.browser import _BrowserManager
        manager = _BrowserManager()

        mock_browser = AsyncMock()
        mock_browser.close = AsyncMock()
        mock_playwright = AsyncMock()
        mock_playwright.stop = AsyncMock()
        manager._browser = mock_browser
        manager._playwright = mock_playwright

        await manager.close()

        mock_browser.close.assert_called_once()
        mock_playwright.stop.assert_called_once()
        assert manager._browser is None
        assert manager._playwright is None

    @pytest.mark.asyncio
    async def test_close_when_nothing_open(self):
        from web4agent.browser import _BrowserManager
        manager = _BrowserManager()
        await manager.close()  # should not raise


# ── read_browser fallback paths ───────────────────────────────────────────────


class TestReadBrowserFallbacks:
    @pytest.mark.asyncio
    async def test_trafilatura_exception_falls_back_gracefully(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            with patch("trafilatura.extract", side_effect=Exception("traf broke")):
                from web4agent.browser import read_browser
                result = await read_browser("https://example.com/")

        assert isinstance(result, WebReadResult)

    @pytest.mark.asyncio
    async def test_bs4_text_fallback_when_trafilatura_returns_none(self):
        mock_browser, _, _ = _make_playwright_mocks()

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            with patch("trafilatura.extract", return_value=None):
                with patch("trafilatura.extract_metadata", return_value=None):
                    from web4agent.browser import read_browser
                    result = await read_browser("https://example.com/")

        assert isinstance(result, WebReadResult)

    @pytest.mark.asyncio
    async def test_trafilatura_md_exception_handled(self):
        """When markdown extraction raises, traf_md stays None and html_to_markdown is used."""
        mock_browser, _, _ = _make_playwright_mocks()

        extract_calls = {"n": 0}

        def extract_side_effect(*a, **kw):
            n = extract_calls["n"]
            extract_calls["n"] += 1
            if n == 0:
                return "Some extracted text content here"
            raise Exception("md boom")

        import trafilatura as traf_mod

        with patch("web4agent.browser._manager._ensure_browser", AsyncMock(return_value=mock_browser)):
            with patch.object(traf_mod, "extract", side_effect=extract_side_effect):
                with patch.object(traf_mod, "extract_metadata", return_value=None):
                    from web4agent.browser import read_browser
                    result = await read_browser("https://example.com/")

        assert isinstance(result, WebReadResult)


# ── _get_ua browserforge path ─────────────────────────────────────────────────


class TestGetUaBrowserforge:
    def test_returns_browserforge_ua_when_available(self):
        fake_ua = "Mozilla/5.0 (Windows NT 10.0) Chrome/120 BrowserForge"
        fake_hdrs = {"User-Agent": fake_ua}
        mock_gen = MagicMock()
        mock_gen.generate.return_value = fake_hdrs
        mock_class = MagicMock(return_value=mock_gen)

        import sys
        fake_bf_module = MagicMock()
        fake_bf_module.HeaderGenerator = mock_class

        with patch.dict(sys.modules, {"browserforge": MagicMock(), "browserforge.headers": fake_bf_module}):
            from web4agent.browser import _get_ua
            ua = _get_ua()

        assert isinstance(ua, str)
        assert len(ua) > 0
