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
    _resolve_ddg_href,
    _url_to_query,
    read_ddg,
    search_ddg,
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
    async def test_query_extracts_domain_and_keywords(self):
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
        query = data.get("q", "")
        assert "example.com" in query
        assert "target" in query
        # Should NOT contain the full raw URL (scheme, slashes)
        assert "https://" not in query


# ── search_ddg ─────────────────────────────────────────────────────────────────


_MULTI_RESULTS = [
    {"title": "First Result", "href": "https://first.com/article", "snippet": GOOD_SNIPPET},
    {"title": "Second Result", "href": "https://second.com/page", "snippet": GOOD_SNIPPET},
    {"title": "Short Snippet", "href": "https://third.com", "snippet": "tiny"},  # filtered
]
_DDG_HTML_MULTI = _make_ddg_html(_MULTI_RESULTS)


class TestSearchDdg:
    @pytest.mark.asyncio
    async def test_returns_structured_results(self):
        with _mock_ddg_client(_DDG_HTML_MULTI):
            results = await search_ddg("test query")

        assert len(results) == 2  # third filtered by min snippet length
        assert results[0]["title"] == "First Result"
        assert results[0]["url"] == "https://first.com/article"
        assert GOOD_SNIPPET in results[0]["snippet"]

    @pytest.mark.asyncio
    async def test_respects_max_results(self):
        with _mock_ddg_client(_DDG_HTML_MULTI):
            results = await search_ddg("test", max_results=1)

        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_empty_on_http_error(self):
        with _mock_ddg_client("", status_code=500):
            results = await search_ddg("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_on_network_error(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.post = AsyncMock(side_effect=Exception("network error"))

        with patch("web4agent.ddg_reader.httpx.AsyncClient", return_value=mock_client):
            results = await search_ddg("test query")
        assert results == []

    @pytest.mark.asyncio
    async def test_empty_on_empty_results_page(self):
        with _mock_ddg_client(_DDG_HTML_EMPTY):
            results = await search_ddg("rareterm")
        assert results == []

    def test_resolve_ddg_href_uddg_redirect(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            '<a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Fpage">link</a>',
            "html.parser",
        )
        tag = soup.find("a")
        assert _resolve_ddg_href(tag) == "https://example.com/page"

    def test_resolve_ddg_href_direct(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            '<a class="result__a" href="https://direct.com/page">link</a>',
            "html.parser",
        )
        tag = soup.find("a")
        assert _resolve_ddg_href(tag) == "https://direct.com/page"

    def test_resolve_ddg_href_none_or_empty(self):
        assert _resolve_ddg_href(None) == ""
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<a class="other">no href</a>', "html.parser")
        assert _resolve_ddg_href(soup.find("a")) == ""

    @pytest.mark.asyncio
    async def test_empty_on_bs4_parse_exception(self):
        with _mock_ddg_client(_DDG_HTML_MULTI):
            with patch("bs4.BeautifulSoup", side_effect=Exception("parse failed")):
                results = await search_ddg("test")
        assert results == []

    @pytest.mark.asyncio
    async def test_skips_result_with_no_url(self):
        """Result nodes where _resolve_ddg_href returns '' are skipped."""
        html = _make_ddg_html([
            {"title": "No URL Result", "href": "https://valid.com/", "snippet": GOOD_SNIPPET},
        ])
        from web4agent.ddg_reader import _resolve_ddg_href as orig_resolve

        call_count = {"n": 0}

        def patched_resolve(a_tag):
            if call_count["n"] == 0:
                call_count["n"] += 1
                return ""  # simulate no URL for first result
            return orig_resolve(a_tag)

        with _mock_ddg_client(html):
            with patch("web4agent.ddg_reader._resolve_ddg_href", side_effect=patched_resolve):
                results = await search_ddg("test")

        assert results == []


class TestUrlToQuery:
    def test_host_and_keywords(self):
        result = _url_to_query("https://example.com/page/about/python")
        assert "example.com" in result
        assert "python" in result

    def test_keywords_only_no_host(self):
        result = _url_to_query("/page/about/python-tutorial")
        assert "example.com" not in result
        assert "python" in result or "tutorial" in result

    def test_host_only_no_keywords(self):
        result = _url_to_query("https://example.com/")
        assert "example.com" in result

    def test_fallback_to_raw_url(self):
        result = _url_to_query("ftp://a.b")
        assert len(result) > 0


class TestExtractHrefHostException:
    def test_exception_returns_empty(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<a href="https://example.com/">link</a>', "html.parser")
        a = soup.find("a")
        with patch("web4agent.ddg_reader.urlparse", side_effect=Exception("urlparse broke")):
            result = _extract_href_host(a)
        assert result == ""


class TestResolveDdgHrefException:
    def test_exception_returns_empty(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup('<a href="https://example.com/">link</a>', "html.parser")
        a = soup.find("a")
        with patch("web4agent.ddg_reader.urlparse", side_effect=Exception("parse broke")):
            result = _resolve_ddg_href(a)
        assert result == ""


class TestParseDdgResultsEdgeCases:
    def test_result_without_snippet_tag_is_skipped(self):
        html = """
        <html><body>
          <div class="result">
            <h2 class="result__title"><a class="result__a" href="/l/?uddg=https%3A%2F%2Fex.com%2F">Title</a></h2>
          </div>
        </body></html>
        """
        title, snippet, href = _parse_ddg_results(html, "https://ex.com/")
        assert snippet is None

    def test_bs4_exception_returns_none_triple(self):
        with patch("bs4.BeautifulSoup", side_effect=Exception("bs4 broke")):
            title, snippet, href = _parse_ddg_results("<html></html>", "https://ex.com/")
        assert title is None
        assert snippet is None
        assert href is None
