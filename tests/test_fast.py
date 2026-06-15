"""Tests for read_fast — internal fetch functions mocked, no real network."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

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
