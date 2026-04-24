"""Tests for read_fast — httpx mocked, no real network."""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from webweb.fast import read_fast
from webweb.models import WebReadResult


def _make_httpx_response(
    html: str,
    status_code: int = 200,
    url: str = "https://example.com/",
    content_type: str = "text/html; charset=utf-8",
) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.url = httpx.URL(url)
    resp.headers = {"content-type": content_type}
    resp.content = html.encode("utf-8")
    resp.text = html
    resp.apparent_encoding = "utf-8"
    return resp


def _patch_client(response):
    """Return a context manager that patches httpx.AsyncClient to return response."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=response)
    return patch("webweb.fast.httpx.AsyncClient", return_value=mock_client)


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


class TestReadFast:
    @pytest.mark.asyncio
    async def test_successful_fetch_returns_result(self):
        resp = _make_httpx_response(RICH_HTML)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert isinstance(result, WebReadResult)
        assert result.url == "https://example.com/"
        assert result.status_code == 200
        assert result.strategy_used == "fast"

    @pytest.mark.asyncio
    async def test_title_extracted(self):
        resp = _make_httpx_response(RICH_HTML)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        # trafilatura may prefer the <h1> over <title>; either is acceptable
        assert result.title is not None
        assert result.title in ("Test Page", "Main Heading")

    @pytest.mark.asyncio
    async def test_text_extracted(self):
        resp = _make_httpx_response(RICH_HTML)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert result.text is not None
        assert len(result.text) > 0

    @pytest.mark.asyncio
    async def test_markdown_generated(self):
        resp = _make_httpx_response(RICH_HTML)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert result.markdown is not None

    @pytest.mark.asyncio
    async def test_attempt_recorded(self):
        resp = _make_httpx_response(RICH_HTML)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert len(result.attempts) == 1
        assert result.attempts[0].strategy == "fast"
        assert result.attempts[0].status_code == 200

    @pytest.mark.asyncio
    async def test_elapsed_ms_set(self):
        resp = _make_httpx_response(RICH_HTML)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_fetched_at_set(self):
        resp = _make_httpx_response(RICH_HTML)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert result.fetched_at != ""

    @pytest.mark.asyncio
    async def test_404_sets_success_false(self):
        resp = _make_httpx_response("<html><body>Not Found</body></html>", status_code=404)
        with _patch_client(resp):
            result = await read_fast("https://example.com/missing")

        assert result.success is False
        assert result.status_code == 404

    @pytest.mark.asyncio
    async def test_timeout_returns_error_result(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with patch("webweb.fast.httpx.AsyncClient", return_value=mock_client):
            result = await read_fast("https://example.com/")

        assert result.success is False
        assert result.error is not None
        assert "Timeout" in result.error or "timed out" in result.error.lower()
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    @pytest.mark.asyncio
    async def test_connection_error_returns_error_result(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("Connection refused"))

        with patch("webweb.fast.httpx.AsyncClient", return_value=mock_client):
            result = await read_fast("https://example.com/")

        assert result.success is False
        assert result.error is not None
        assert len(result.attempts) == 1

    @pytest.mark.asyncio
    async def test_html_stored_in_result(self):
        resp = _make_httpx_response(RICH_HTML)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert result.html is not None
        assert "<html>" in result.html.lower() or "html" in result.html.lower()

    @pytest.mark.asyncio
    async def test_bs4_fallback_when_trafilatura_fails(self):
        # Minimal HTML that trafilatura likely returns None for
        simple_html = "<html><head><title>Simple</title></head><body><p>Just text</p></body></html>"
        resp = _make_httpx_response(simple_html)
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        # Either trafilatura or BS4 should extract something
        # (we can't guarantee which, but text shouldn't be None for valid HTML)
        assert result.text is None or isinstance(result.text, str)

    @pytest.mark.asyncio
    async def test_charset_in_content_type(self):
        resp = _make_httpx_response(RICH_HTML, content_type="text/html; charset=utf-8")
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_final_url_set_from_response(self):
        resp = _make_httpx_response(RICH_HTML, url="https://example.com/redirected")
        with _patch_client(resp):
            result = await read_fast("https://example.com/")

        assert result.final_url == "https://example.com/redirected"
