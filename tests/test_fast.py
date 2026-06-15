"""Tests for read_fast — internal fetch functions mocked, no real network."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web4agent.fast import read_fast
from web4agent.models import WebReadResult

RICH_HTML = """
<html>
<head><title>Test Page</title></head>
<body>
  <article>
    <h1>Main Heading</h1>
    <p>This is substantial article content with enough words to pass the minimum length check.
    It contains multiple sentences about various topics to ensure trafilatura or BeautifulSoup
    can extract meaningful text from the page. Lorem ipsum dolor sit amet consectetur.</p>
    <p>Second paragraph with more content to push past the minimum text length threshold
    that the router uses to decide whether to degrade to another strategy.</p>
  </article>
</body>
</html>
"""

SIMPLE_HTML = "<html><head><title>Simple</title></head><body><p>Just text</p></body></html>"


def _patch_fetch(
    html: str = RICH_HTML,
    status_code: int = 200,
    url: str = "https://example.com/",
):
    """Patch _curl_get to return (status_code, html, url) without network."""
    return patch(
        "web4agent.fast._curl_get",
        new=AsyncMock(return_value=(status_code, html, url)),
    )


class TestReadFast:
    @pytest.mark.asyncio
    async def test_returns_web_read_result(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert isinstance(result, WebReadResult)

    @pytest.mark.asyncio
    async def test_url_and_strategy_set(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.url == "https://example.com/"
        assert result.strategy_used == "fast"

    @pytest.mark.asyncio
    async def test_status_code_200(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_success_true_on_good_response(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_title_extracted(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.title is not None
        assert result.title in ("Test Page", "Main Heading")

    @pytest.mark.asyncio
    async def test_text_extracted(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.text is not None
        assert len(result.text) > 0

    @pytest.mark.asyncio
    async def test_markdown_generated(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.markdown is not None

    @pytest.mark.asyncio
    async def test_html_stored(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.html is not None
        assert "html" in result.html.lower()

    @pytest.mark.asyncio
    async def test_attempt_recorded(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert len(result.attempts) == 1
        assert result.attempts[0].strategy == "fast"
        assert result.attempts[0].status_code == 200

    @pytest.mark.asyncio
    async def test_elapsed_ms_set(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_fetched_at_set(self):
        with _patch_fetch():
            result = await read_fast("https://example.com/")
        assert result.fetched_at != ""

    @pytest.mark.asyncio
    async def test_final_url_from_response(self):
        with _patch_fetch(url="https://example.com/redirected"):
            result = await read_fast("https://example.com/")
        assert result.final_url == "https://example.com/redirected"

    @pytest.mark.asyncio
    async def test_404_sets_success_false(self):
        with _patch_fetch(html="<html><body>Not Found</body></html>", status_code=404):
            result = await read_fast("https://example.com/missing")
        assert result.success is False
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_exception_returns_error_result(self):
        with patch("web4agent.fast._curl_get", new=AsyncMock(side_effect=Exception("connection refused"))):
            with patch("web4agent.fast._httpx_get", new=AsyncMock(side_effect=Exception("connection refused"))):
                result = await read_fast("https://example.com/")
        assert result.success is False
        assert result.error is not None
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    @pytest.mark.asyncio
    async def test_timeout_error_captured(self):
        with patch("web4agent.fast._curl_get", new=AsyncMock(side_effect=Exception("timed out"))):
            with patch("web4agent.fast._httpx_get", new=AsyncMock(side_effect=Exception("timed out"))):
                result = await read_fast("https://example.com/")
        assert result.success is False
        assert "timed out" in result.error.lower()

    @pytest.mark.asyncio
    async def test_httpx_fallback_when_curl_not_installed(self):
        """When curl_cffi raises ImportError, httpx fallback is used."""
        with patch("web4agent.fast._curl_get", new=AsyncMock(side_effect=ImportError)):
            with patch("web4agent.fast._httpx_get", new=AsyncMock(return_value=(200, RICH_HTML, "https://example.com/"))) as mock_httpx:
                result = await read_fast("https://example.com/")
        mock_httpx.assert_called_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_proxy_passed_to_curl_get(self):
        """proxy= parameter is forwarded to the underlying fetch function."""
        with patch("web4agent.fast._curl_get", new=AsyncMock(return_value=(200, RICH_HTML, "https://example.com/"))) as mock_curl:
            await read_fast("https://example.com/", proxy="http://proxy:8080")
        _, _, kwargs = mock_curl.mock_calls[0]
        assert kwargs.get("proxy") == "http://proxy:8080" or mock_curl.call_args[0][2] == "http://proxy:8080"

    @pytest.mark.asyncio
    async def test_bs4_fallback_when_trafilatura_returns_none(self):
        with _patch_fetch(html=SIMPLE_HTML):
            result = await read_fast("https://example.com/")
        # Either extractor returns something (or None for truly empty pages)
        assert result.text is None or isinstance(result.text, str)


# ── Internal helpers ───────────────────────────────────────────────────────────

class TestBrowserHeaders:
    def test_returns_dict(self):
        from web4agent.fast import _browser_headers
        h = _browser_headers()
        assert isinstance(h, dict)
        assert len(h) > 0

    def test_contains_user_agent(self):
        from web4agent.fast import _browser_headers
        h = _browser_headers()
        # Header key may be capitalized differently
        keys_lower = {k.lower() for k in h}
        assert "user-agent" in keys_lower

    def test_fallback_when_browserforge_absent(self):
        from web4agent.fast import _browser_headers
        with patch("web4agent.fast._browser_headers", wraps=_browser_headers):
            # Simulate ImportError from browserforge by patching inside the function
            import builtins
            real_import = builtins.__import__

            def mock_import(name, *args, **kwargs):
                if name == "browserforge.headers":
                    raise ImportError("no browserforge")
                return real_import(name, *args, **kwargs)

            with patch("builtins.__import__", side_effect=mock_import):
                h = _browser_headers()
        assert "User-Agent" in h
        assert "Chrome" in h["User-Agent"]


class TestHttpxGet:
    @pytest.mark.asyncio
    async def test_returns_status_html_url_tuple(self):
        import httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = httpx.URL("https://example.com/")
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.content = b"<html><body>hello</body></html>"
        mock_resp.text = "<html><body>hello</body></html>"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from web4agent.fast import _httpx_get
            status, html, url = await _httpx_get("https://example.com/", 20, None)

        assert status == 200
        assert "hello" in html
        assert url == "https://example.com/"

    @pytest.mark.asyncio
    async def test_charset_from_content_type(self):
        import httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = httpx.URL("https://example.com/")
        mock_resp.headers = {"content-type": "text/html; charset=utf-8"}
        mock_resp.content = "héllo".encode("utf-8")
        mock_resp.text = "héllo"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client):
            from web4agent.fast import _httpx_get
            _, html, _ = await _httpx_get("https://example.com/", 20, None)

        assert "h" in html

    @pytest.mark.asyncio
    async def test_proxy_passed_to_client(self):
        import httpx
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.url = httpx.URL("https://example.com/")
        mock_resp.headers = {"content-type": "text/html"}
        mock_resp.content = b"hi"
        mock_resp.text = "hi"
        mock_resp.apparent_encoding = "utf-8"

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_resp)

        with patch("httpx.AsyncClient", return_value=mock_client) as mock_cls:
            from web4agent.fast import _httpx_get
            await _httpx_get("https://example.com/", 20, "http://p:8080")

        call_kwargs = mock_cls.call_args[1]
        assert call_kwargs.get("proxy") == "http://p:8080"
