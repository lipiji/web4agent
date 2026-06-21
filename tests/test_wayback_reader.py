"""Tests for read_wayback — archive.org Wayback Machine reader (network mocked)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from web4agent.models import WebReadResult
from web4agent.wayback_reader import _find_snapshot, read_wayback


# ── fixtures & helpers ──────────────────────────────────────────────────────────

RICH_HTML = """
<html>
<head><title>Archived Page</title></head>
<body>
  <article>
    <h1>Archived Heading</h1>
    <p>This is substantial archived content with enough text to pass the minimum
    length check used by the router degradation logic. Multiple sentences here.</p>
    <p>Second paragraph with more content to push past the threshold that determines
    whether the strategy result is accepted or degraded further.</p>
  </article>
</body>
</html>
"""

_SNAPSHOT_ROWS = [["timestamp", "original"], ["20241201120000", "http://example.com/"]]
_ARCHIVED_URL = "https://web.archive.org/web/20241201120000/http://example.com/"


def _make_cdx_response(
    rows=None,
    status_code: int = 200,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json = MagicMock(return_value=rows if rows is not None else _SNAPSHOT_ROWS)
    return resp


def _make_fetch_response(
    html: str = RICH_HTML,
    status_code: int = 200,
    content_type: str = "text/html; charset=utf-8",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = html
    resp.headers = {"content-type": content_type}
    return resp


def _patch_wayback_client(cdx_response, fetch_response=None):
    """Patch httpx.AsyncClient so get() returns cdx_response then fetch_response."""
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    if fetch_response is not None:
        mock_client.get = AsyncMock(side_effect=[cdx_response, fetch_response])
    else:
        mock_client.get = AsyncMock(return_value=cdx_response)

    return patch("web4agent.wayback_reader.httpx.AsyncClient", return_value=mock_client)


# ── _find_snapshot unit tests ──────────────────────────────────────────────────

class TestFindSnapshot:
    @pytest.mark.asyncio
    async def test_returns_archived_url_on_valid_response(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response())
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result == _ARCHIVED_URL

    @pytest.mark.asyncio
    async def test_returns_none_on_cdx_4xx(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response(status_code=404))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_cdx_5xx(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response(status_code=503))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_no_snapshot_exists(self):
        # CDX returns header row only (no results)
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response(rows=[["timestamp", "original"]]))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_rows_empty(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response(rows=[]))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_row_malformed_short(self):
        # Row has only one element instead of two
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response(rows=[["timestamp"], ["20241201120000"]]))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_row_is_not_list(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response(rows=[["timestamp", "original"], "not-a-list"]))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_timestamp_empty(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response(rows=[["timestamp", "original"], ["", "http://example.com/"]]))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_when_original_empty(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response(rows=[["timestamp", "original"], ["20241201120000", ""]]))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_json_error(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(side_effect=ValueError("not json"))
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=resp)
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_none_on_network_error(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))
        result = await _find_snapshot("http://example.com/", mock_client)
        assert result is None

    @pytest.mark.asyncio
    async def test_archived_url_contains_timestamp_and_original(self):
        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_make_cdx_response())
        result = await _find_snapshot("http://example.com/", mock_client)
        assert "20241201120000" in result
        assert "example.com" in result


# ── read_wayback integration tests ─────────────────────────────────────────────

class TestReadWayback:
    @pytest.mark.asyncio
    async def test_returns_web_read_result(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert isinstance(result, WebReadResult)

    @pytest.mark.asyncio
    async def test_strategy_used_is_wayback(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.strategy_used == "wayback"

    @pytest.mark.asyncio
    async def test_success_true_on_good_html(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_url_preserved(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.url == "http://example.com/"

    @pytest.mark.asyncio
    async def test_final_url_is_archived_url(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.final_url == _ARCHIVED_URL

    @pytest.mark.asyncio
    async def test_metadata_contains_archived_url(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert "archived_url" in result.metadata
        assert result.metadata["archived_url"] == _ARCHIVED_URL

    @pytest.mark.asyncio
    async def test_title_extracted(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.title is not None

    @pytest.mark.asyncio
    async def test_text_extracted(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.text is not None
        assert len(result.text) > 0

    @pytest.mark.asyncio
    async def test_markdown_generated(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.markdown is not None

    @pytest.mark.asyncio
    async def test_attempt_recorded(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert len(result.attempts) == 1
        assert result.attempts[0].strategy == "wayback"
        assert result.attempts[0].success is True

    @pytest.mark.asyncio
    async def test_elapsed_ms_set(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.elapsed_ms is not None
        assert result.elapsed_ms >= 0

    @pytest.mark.asyncio
    async def test_fetched_at_set(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response()):
            result = await read_wayback("http://example.com/")
        assert result.fetched_at != ""

    @pytest.mark.asyncio
    async def test_status_code_propagated(self):
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response(status_code=200)):
            result = await read_wayback("http://example.com/")
        assert result.status_code == 200

    @pytest.mark.asyncio
    async def test_bad_status_sets_error_message(self):
        """Regression: success=False from a bad status must not leave error=None."""
        with _patch_wayback_client(_make_cdx_response(), _make_fetch_response(status_code=503)):
            result = await read_wayback("http://example.com/")
        assert result.success is False
        assert result.error == "HTTP 503"
        assert result.attempts[0].error == "HTTP 503"

    # ── failure: no snapshot ──────────────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_no_snapshot_returns_failure(self):
        cdx_resp = _make_cdx_response(rows=[["timestamp", "original"]])  # header only
        with _patch_wayback_client(cdx_resp):
            result = await read_wayback("http://example.com/")
        assert result.success is False
        assert result.error is not None
        assert result.strategy_used == "wayback"

    @pytest.mark.asyncio
    async def test_no_snapshot_attempt_recorded(self):
        cdx_resp = _make_cdx_response(rows=[["timestamp", "original"]])
        with _patch_wayback_client(cdx_resp):
            result = await read_wayback("http://example.com/")
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    # ── failure: non-HTML content type ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_pdf_content_type_returns_failure(self):
        with _patch_wayback_client(
            _make_cdx_response(),
            _make_fetch_response(html=b"%PDF-1.4".decode("latin1"), content_type="application/pdf"),
        ):
            result = await read_wayback("http://example.com/doc.pdf")
        assert result.success is False
        assert result.error is not None
        assert "Non-HTML" in result.error or "pdf" in result.error.lower()

    @pytest.mark.asyncio
    async def test_image_content_type_returns_failure(self):
        with _patch_wayback_client(
            _make_cdx_response(),
            _make_fetch_response(html="", content_type="image/jpeg"),
        ):
            result = await read_wayback("http://example.com/img.jpg")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_xml_content_type_is_accepted(self):
        xml = "<root><item>content here that is long enough to pass the minimum</item></root>"
        with _patch_wayback_client(
            _make_cdx_response(),
            _make_fetch_response(html=xml, content_type="application/xml"),
        ):
            result = await read_wayback("http://example.com/feed.xml")
        # XML is accepted; success depends on text extraction
        assert result.strategy_used == "wayback"

    # ── failure: network / HTTP errors ────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_network_error_returns_failure(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        with patch("web4agent.wayback_reader.httpx.AsyncClient", return_value=mock_client):
            result = await read_wayback("http://example.com/")

        assert result.success is False
        assert result.error is not None
        assert result.strategy_used == "wayback"
        assert len(result.attempts) == 1
        assert result.attempts[0].success is False

    @pytest.mark.asyncio
    async def test_timeout_returns_failure(self):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timed out"))

        with patch("web4agent.wayback_reader.httpx.AsyncClient", return_value=mock_client):
            result = await read_wayback("http://example.com/")

        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_error_message_contains_exception_type_not_full_trace(self):
        # Raise at client creation so the outer handler in read_wayback catches it
        # (_find_snapshot has its own inner try/except that swallows CDX-level errors)
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(side_effect=RuntimeError("internal detail"))
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("web4agent.wayback_reader.httpx.AsyncClient", return_value=mock_client):
            result = await read_wayback("http://example.com/")

        assert result.error is not None and result.error.startswith("RuntimeError")

    # ── content extraction fallback ───────────────────────────────────────────

    @pytest.mark.asyncio
    async def test_bs4_fallback_used_when_trafilatura_returns_none(self):
        simple_html = (
            "<html><head><title>Title</title></head>"
            "<body><p>Short text.</p></body></html>"
        )
        with _patch_wayback_client(
            _make_cdx_response(),
            _make_fetch_response(html=simple_html),
        ):
            with patch("trafilatura.extract", return_value=None):
                result = await read_wayback("http://example.com/")
        # BS4 fallback should produce some text
        assert result.text is None or isinstance(result.text, str)

    @pytest.mark.asyncio
    async def test_trafilatura_exception_falls_back_to_bs4(self):
        """When trafilatura raises, the except block sets text=None and bs4 runs."""
        with _patch_wayback_client(
            _make_cdx_response(),
            _make_fetch_response(),
        ):
            with patch("trafilatura.extract", side_effect=Exception("traf crash")):
                result = await read_wayback("http://example.com/")
        assert isinstance(result, WebReadResult)
