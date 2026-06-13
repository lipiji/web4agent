"""Tests for link discovery — pure logic (no network)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web4agent.links import _is_valid_href, _normalize, discover_links


# ── _is_valid_href ─────────────────────────────────────────────────────────────

class TestIsValidHref:
    def test_empty_string(self):
        assert _is_valid_href("") is False

    def test_whitespace_only(self):
        assert _is_valid_href("   ") is False

    def test_anchor_only(self):
        assert _is_valid_href("#section") is False

    def test_mailto(self):
        assert _is_valid_href("mailto:foo@bar.com") is False

    def test_javascript(self):
        assert _is_valid_href("javascript:void(0)") is False

    def test_javascript_mixed_case(self):
        assert _is_valid_href("JavaScript:void(0)") is False

    def test_tel(self):
        assert _is_valid_href("tel:+1234567890") is False

    def test_data_uri(self):
        assert _is_valid_href("data:image/png;base64,abc") is False

    def test_https_url(self):
        assert _is_valid_href("https://example.com") is True

    def test_http_url(self):
        assert _is_valid_href("http://example.com/page") is True

    def test_absolute_path(self):
        assert _is_valid_href("/about") is True

    def test_relative_path(self):
        assert _is_valid_href("../up") is True

    def test_relative_same_dir(self):
        assert _is_valid_href("page.html") is True


# ── _normalize ─────────────────────────────────────────────────────────────────

class TestNormalize:
    def test_absolute_url_unchanged(self):
        result = _normalize("https://other.com/page", "https://base.com/")
        assert result == "https://other.com/page"

    def test_root_relative(self):
        result = _normalize("/about", "https://example.com/home")
        assert result == "https://example.com/about"

    def test_relative_path(self):
        result = _normalize("page.html", "https://example.com/dir/")
        assert result == "https://example.com/dir/page.html"

    def test_parent_relative(self):
        result = _normalize("../other", "https://example.com/a/b/c")
        assert result is not None
        assert "example.com" in result
        assert ".." not in result

    def test_strips_fragment(self):
        result = _normalize("https://example.com/page#section", "https://example.com/")
        assert result is not None
        assert "#" not in result
        assert result == "https://example.com/page"

    def test_fragment_only_href(self):
        result = _normalize("#top", "https://example.com/page")
        # Fragment-only link normalizes to the page URL itself (no fragment)
        assert result is not None
        assert "#" not in result

    def test_empty_href(self):
        result = _normalize("", "https://example.com/")
        # Empty resolves to base URL or None — must not raise
        assert result is None or isinstance(result, str)


# ── discover_links (mocked HTTP) ───────────────────────────────────────────────

SAMPLE_HTML = """
<html>
<body>
  <a href="/page1">Page 1</a>
  <a href="/page2">Page 2</a>
  <a href="https://other.com/external">External</a>
  <a href="mailto:x@y.com">Email</a>
  <a href="javascript:void(0)">JS</a>
  <a href="#anchor">Anchor</a>
  <a href="/page1">Page 1 duplicate</a>
</body>
</html>
"""


def _mock_response(html: str, url: str = "https://example.com/", status: int = 200):
    resp = MagicMock()
    resp.text = html
    resp.url = url
    resp.status_code = status
    return resp


@pytest.mark.asyncio
async def test_discover_links_same_domain():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_mock_response(SAMPLE_HTML))

    with patch("web4agent.links.httpx.AsyncClient", return_value=mock_client):
        links = await discover_links("https://example.com/", same_domain=True)

    # /page1, /page2 should be included (same domain)
    assert any("page1" in l for l in links)
    assert any("page2" in l for l in links)
    # external link excluded
    assert not any("other.com" in l for l in links)


@pytest.mark.asyncio
async def test_discover_links_include_external():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_mock_response(SAMPLE_HTML))

    with patch("web4agent.links.httpx.AsyncClient", return_value=mock_client):
        links = await discover_links("https://example.com/", same_domain=False)

    assert any("other.com" in l for l in links)


@pytest.mark.asyncio
async def test_discover_links_deduplication():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_mock_response(SAMPLE_HTML))

    with patch("web4agent.links.httpx.AsyncClient", return_value=mock_client):
        links = await discover_links("https://example.com/", same_domain=True)

    # /page1 appears twice in HTML but should appear once in results
    page1_links = [l for l in links if "page1" in l]
    assert len(page1_links) == 1


@pytest.mark.asyncio
async def test_discover_links_filters_invalid():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_mock_response(SAMPLE_HTML))

    with patch("web4agent.links.httpx.AsyncClient", return_value=mock_client):
        links = await discover_links("https://example.com/", same_domain=False)

    for link in links:
        assert not link.startswith("mailto:")
        assert not link.startswith("javascript:")
        assert "#" not in link


@pytest.mark.asyncio
async def test_discover_links_max_links():
    many_links = "".join(f'<a href="/page{i}">P{i}</a>' for i in range(50))
    html = f"<html><body>{many_links}</body></html>"

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=_mock_response(html))

    with patch("web4agent.links.httpx.AsyncClient", return_value=mock_client):
        links = await discover_links("https://example.com/", max_links=5)

    assert len(links) <= 5


@pytest.mark.asyncio
async def test_discover_links_fetch_error_returns_empty():
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=Exception("network error"))

    with patch("web4agent.links.httpx.AsyncClient", return_value=mock_client):
        links = await discover_links("https://example.com/")

    assert links == []
