"""Tests for read_ddg — DuckDuckGo HTML search fallback (network mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch
from urllib.parse import quote

import httpx
import pytest

from web4agent.ddg_reader import (
    _extract_href_host,
    _norm_host,
    _parse_ddg_results,
    read_ddg,
)
from web4agent.models import WebReadResult


# ── DDG HTML fixtures ──────────────────────────────────────────────────────────

def _make_ddg_html(results: list[dict]) -> str:
    """Build minimal DDG HTML results page from a list of {title, href, snippet} dicts."""
    items = []
    for r in results:
        encoded = quote(r["href"], safe="")
        items.append(f"""
        <div class="result">
          <h2 class="result__title">
            <a class="result__a" href="/l/?uddg={encoded}">{r["title"]}</a>
          </h2>
          <div class="result__snippet">{r["snippet"]}</div>
          <a class="result__url" href="{r["href"]}">{r["href"]}</a>
        </div>
        """)
    return f"<html><body>{''.join(items)}</body></html>"


GOOD_SNIPPET = "This is a sufficiently long snippet about the page content that exceeds the minimum threshold."

_SAMPLE_RESULTS = [
    {
        "title": "Example Domain",
        "href": "https://example.com/page",
        "snippet": GOOD_SNIPPET,
    }
]

_DDG_HTML_ONE_RESULT = _make_ddg_html(_SAMPLE_RESULTS)
_DDG_HTML_EMPTY = "<html><body><p>No results.</p></body></html>"
_DDG_HTML_NO_SNIPPET = _make_ddg_html([{
    "title": "No Snippet",
    "href": "https://other.com/",
    "snippet": "",
}])


def _mock_ddg_client(html: str, status_code: int = 200):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.post = AsyncMock(return_value=resp)

    return patch("web4agent.ddg_reader.httpx.AsyncClient", return_value=mock_client)


# ── _norm_host unit tests ──────────────────────────────────────────────────────

class TestNormHost:
    def test_strips_www_prefix(self):
        assert _norm_host("www.example.com") == "example.com"

    def test_lowercases(self):
        assert _norm_host("WWW.EXAMPLE.COM") == "example.com"

    def test_no_www_unchanged(self):
        assert _norm_host("example.com") == "example.com"

    def test_subdomain_not_stripped(self):
        assert _norm_host("news.example.com") == "news.example.com"

    def test_double_www_strips_one(self):
        # Only the leading "www." prefix is removed, not characters
        assert _norm_host("www.www.example.com") == "www.example.com"

    def test_empty_string(self):
        assert _norm_host("") == ""


# ── _extract_href_host unit tests ──────────────────────────────────────────────

class TestExtractHrefHost:
    def test_regular_url(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<a href="https://example.com/page">link</a>', "html.parser")
        a = soup.find("a")
        assert _extract_href_host(a) == "example.com"

    def test_ddg_redirect_url(self):
        real = quote("https://example.com/path", safe="")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(f'<a href="/l/?uddg={real}">link</a>', "html.parser")
        a = soup.find("a")
        assert _extract_href_host(a) == "example.com"

    def test_ddg_redirect_with_www(self):
        real = quote("https://www.example.com/", safe="")
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(f'<a href="/l/?uddg={real}">link</a>', "html.parser")
        a = soup.find("a")
        assert _extract_href_host(a) == "example.com"

    def test_none_tag_returns_empty(self):
        assert _extract_href_host(None) == ""

    def test_tag_without_href_returns_empty(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<a>no href</a>', "html.parser")
        a = soup.find("a")
        assert _extract_href_host(a) == ""

    def test_normalizes_host_to_lowercase(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<a href="https://WWW.EXAMPLE.COM/">link</a>', "html.parser")
        a = soup.find("a")
        assert _extract_href_host(a) == "example.com"


# ── _parse_ddg_results unit tests ─────────────────────────────────────────────

class TestParseDdgResults:
    def test_returns_none_triple_on_empty_html(self):
        title, snippet, href = _parse_ddg_results(_DDG_HTML_EMPTY, "https://example.com/")
        assert title is None
        assert snippet is None
        assert href is None

    def test_returns_first_result(self):
        title, snippet, href = _parse_ddg_results(_DDG_HTML_ONE_RESULT, "https://other.com/")
        assert snippet == GOOD_SNIPPET
        assert title == "Example Domain"

    def test_prefers_matching_host(self):
        html = _make_ddg_html([
            {
                "title": "Unrelated Site",
                "href": "https://unrelated.com/",
                "snippet": "Unrelated snippet text that is long enough to pass the minimum threshold easily.",
            },
            {
                "title": "Target Page",
                "href": "https://example.com/target",
                "snippet": "This is the correct result for the target URL with enough content.",
            },
        ])
        title, snippet, href = _parse_ddg_results(html, "https://example.com/target")
        assert title == "Target Page"

    def test_skips_short_snippets(self):
        html = _make_ddg_html([
            {
                "title": "Short",
                "href": "https://example.com/",
                "snippet": "Too short.",
            },
            {
                "title": "Long Enough",
                "href": "https://other.com/",
                "snippet": GOOD_SNIPPET,
            },
        ])
        title, snippet, href = _parse_ddg_results(html, "https://nonexistent.com/")
        assert title == "Long Enough"

    def test_all_short_snippets_returns_none_triple(self):
        html = _make_ddg_html([
            {"title": "Short", "href": "https://example.com/", "snippet": "Tiny."},
        ])
        title, snippet, href = _parse_ddg_results(html, "https://example.com/")
        assert snippet is None

    def test_returns_href_for_matched_result(self):
        title, snippet, href = _parse_ddg_results(_DDG_HTML_ONE_RESULT, "https://other.com/")
        assert href is not None

    def test_www_host_matches_non_www_target(self):
        html = _make_ddg_html([
            {
                "title": "WWW Site",
                "href": "https://www.example.com/",
                "snippet": "Content from www subdomain that exceeds the minimum length requirement.",
            },
        ])
        title, snippet, href = _parse_ddg_results(html, "https://example.com/")
        # www.example.com should match example.com target
        assert title == "WWW Site"

    def test_handles_malformed_html_gracefully(self):
        title, snippet, href = _parse_ddg_results("<not valid >> html <<<", "https://example.com/")
        # Should not raise; may return None values
        assert isinstance(title, (str, type(None)))
        assert isinstance(snippet, (str, type(None)))


# ── read_ddg integration tests ─────────────────────────────────────────────────

class TestReadDdg:
    @pytest.mark.asyncio
    async def test_returns_web_read_result(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert isinstance(result, WebReadResult)

    @pytest.mark.asyncio
    async def test_strategy_used_is_ddg(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.strategy_used == "ddg"

    @pytest.mark.asyncio
    async def test_success_true_when_snippet_found(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_text_contains_snippet(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.text == GOOD_SNIPPET

    @pytest.mark.asyncio
    async def test_title_set(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.title == "Example Domain"

    @pytest.mark.asyncio
    async def test_url_preserved(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.url == "https://example.com/page"

    @pytest.mark.asyncio
    async def test_metadata_snippet_only_flag(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.metadata.get("snippet_only") is True

    @pytest.mark.asyncio
    async def test_metadata_snippet_length(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.metadata.get("snippet_length") == len(GOOD_SNIPPET)

    @pytest.mark.asyncio
    async def test_metadata_matched_url_set(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert "matched_url" in result.metadata

    @pytest.mark.asyncio
    async def test_attempt_recorded(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert len(result.attempts) == 1
        assert result.attempts[0].strategy == "ddg"
        assert result.attempts[0].success is True

    @pytest.mark.asyncio
    async def test_elapsed_ms_set(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_fetched_at_set(self):
        with _mock_ddg_client(_DDG_HTML_ONE_RESULT):
            result = await read_ddg("https://example.com/page")
        assert result.fetched_at != ""

    # ── failure: no results ────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_results_returns_failure(self):
        with _mock_ddg_client(_DDG_HTML_EMPTY):
            result = await read_ddg("https://example.com/page")
        assert result.success is False
        assert result.error is not None
        assert result.strategy_used == "ddg"

    @pytest.mark.asyncio
    async def test_no_results_attempt_recorded(self):
        with _mock_ddg_client(_DDG_HTML_EMPTY):
            result = await read_ddg("https://example.com/page")
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    @pytest.mark.asyncio
    async def test_all_snippets_too_short_returns_failure(self):
        html = _make_ddg_html([
            {"title": "S", "href": "https://example.com/", "snippet": "Short."},
        ])
        with _mock_ddg_client(html):
            result = await read_ddg("https://example.com/")
        assert result.success is False

    # ── failure: network / HTTP errors ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_network_error_returns_failure(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("web4agent.ddg_reader.httpx.AsyncClient", return_value=mock_client):
            result = await read_ddg("https://example.com/")

        assert result.success is False
        assert result.error is not None
        assert result.strategy_used == "ddg"
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with patch("web4agent.ddg_reader.httpx.AsyncClient", return_value=mock_client):
            result = await read_ddg("https://example.com/")

        assert result.success is False

    @pytest.mark.asyncio
    async def test_error_message_is_exception_type_only(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=RuntimeError("secret internal detail"))

        with patch("web4agent.ddg_reader.httpx.AsyncClient", return_value=mock_client):
            result = await read_ddg("https://example.com/")

        assert result.error is not None and result.error.startswith("RuntimeError")

    # ── matching behaviour ─────────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_prefers_result_matching_target_domain(self):
        html = _make_ddg_html([
            {
                "title": "Unrelated",
                "href": "https://unrelated.com/",
                "snippet": "Unrelated snippet that is sufficiently long to pass the minimum length check.",
            },
            {
                "title": "Target",
                "href": "https://example.com/target-page",
                "snippet": "This is the correct snippet for example.com and is long enough.",
            },
        ])
        with _mock_ddg_client(html):
            result = await read_ddg("https://example.com/target-page")
        assert result.title == "Target"

    @pytest.mark.asyncio
    async def test_falls_back_to_first_result_when_no_match(self):
        html = _make_ddg_html([
            {
                "title": "First Result",
                "href": "https://unrelated.com/",
                "snippet": GOOD_SNIPPET,
            },
            {
                "title": "Second Result",
                "href": "https://also-unrelated.com/",
                "snippet": "Second snippet that is also long enough to exceed the minimum.",
            },
        ])
        with _mock_ddg_client(html):
            result = await read_ddg("https://nowhere.com/")
        assert result.title == "First Result"

    @pytest.mark.asyncio
    async def test_post_method_used(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = _DDG_HTML_ONE_RESULT
        mock_client.post = AsyncMock(return_value=resp)

        with patch("web4agent.ddg_reader.httpx.AsyncClient", return_value=mock_client):
            await read_ddg("https://example.com/")

        mock_client.post.assert_called_once()
        call_kwargs = mock_client.post.call_args
        # Should POST to the DDG HTML endpoint
        assert "html.duckduckgo.com" in call_kwargs[0][0]

    @pytest.mark.asyncio
    async def test_query_includes_url(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        resp = MagicMock()
        resp.status_code = 200
        resp.text = _DDG_HTML_ONE_RESULT
        mock_client.post = AsyncMock(return_value=resp)

        with patch("web4agent.ddg_reader.httpx.AsyncClient", return_value=mock_client):
            await read_ddg("https://example.com/target")

        call_kwargs = mock_client.post.call_args[1]
        data = call_kwargs.get("data", {})
        assert "https://example.com/target" in data.get("q", "")
