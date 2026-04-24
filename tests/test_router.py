"""Tests for strategy router and auto-degradation logic."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from webweb.models import FetchAttempt, WebReadResult
from webweb.router import _merge_attempts, _should_degrade


# ── helpers ────────────────────────────────────────────────────────────────────

def _make_result(**kwargs) -> WebReadResult:
    defaults = dict(
        url="https://example.com",
        fetched_at="t",
        success=True,
        text="x" * 400,
        status_code=200,
        attempts=[FetchAttempt(strategy="fast", success=True, status_code=200)],
    )
    defaults.update(kwargs)
    return WebReadResult(**defaults)


# ── _should_degrade ────────────────────────────────────────────────────────────

class TestShouldDegrade:
    def test_false_when_success_and_good_text(self):
        r = _make_result(text="A" * 400, success=True, status_code=200)
        assert _should_degrade(r) is False

    def test_true_when_success_false(self):
        r = _make_result(success=False, text=None)
        assert _should_degrade(r) is True

    def test_true_on_4xx(self):
        r = _make_result(status_code=404)
        assert _should_degrade(r) is True

    def test_true_on_5xx(self):
        r = _make_result(status_code=500)
        assert _should_degrade(r) is True

    def test_true_on_short_text(self):
        r = _make_result(text="too short", success=True)
        assert _should_degrade(r) is True

    def test_true_on_empty_text(self):
        r = _make_result(text="", success=True)
        assert _should_degrade(r) is True

    def test_true_on_none_text(self):
        r = _make_result(text=None, success=True)
        assert _should_degrade(r) is True

    def test_true_on_js_shell(self):
        spa_html = '<html><body><div id="root"></div></body></html>'
        r = _make_result(html=spa_html, text="x" * 400)
        assert _should_degrade(r) is True

    def test_no_degrade_when_status_none(self):
        r = _make_result(status_code=None, text="A" * 400, success=True)
        assert _should_degrade(r) is False

    def test_boundary_text_length(self):
        from webweb.config import MIN_TEXT_LENGTH
        r = _make_result(text="A" * MIN_TEXT_LENGTH, success=True, status_code=200)
        assert _should_degrade(r) is False
        r2 = _make_result(text="A" * (MIN_TEXT_LENGTH - 1), success=True, status_code=200)
        assert _should_degrade(r2) is True


# ── _merge_attempts ────────────────────────────────────────────────────────────

class TestMergeAttempts:
    def test_combines_attempt_lists(self):
        a1 = FetchAttempt(strategy="fast", success=False)
        a2 = FetchAttempt(strategy="crawl4ai", success=True)
        base = _make_result(attempts=[a1])
        extra = _make_result(attempts=[a2], strategy_used="crawl4ai")
        merged = _merge_attempts(base, extra)
        assert len(merged.attempts) == 2

    def test_winner_is_extra_when_extra_succeeds(self):
        base = _make_result(success=False, text=None, attempts=[])
        extra = _make_result(success=True, text="A" * 400, strategy_used="crawl4ai", attempts=[])
        merged = _merge_attempts(base, extra)
        assert merged.strategy_used == "crawl4ai"

    def test_winner_is_base_when_extra_fails(self):
        base = _make_result(success=True, strategy_used="fast", text="A" * 400, attempts=[])
        extra = _make_result(success=False, text=None, strategy_used="crawl4ai", attempts=[])
        merged = _merge_attempts(base, extra)
        assert merged.strategy_used == "fast"

    def test_original_not_mutated(self):
        a1 = FetchAttempt(strategy="fast", success=False)
        a2 = FetchAttempt(strategy="crawl4ai", success=True)
        base = _make_result(attempts=[a1])
        extra = _make_result(attempts=[a2])
        _merge_attempts(base, extra)
        assert len(base.attempts) == 1


# ── read_url dispatch ──────────────────────────────────────────────────────────

class TestReadUrlDispatch:
    @pytest.mark.asyncio
    async def test_fast_strategy_calls_read_fast(self):
        good = _make_result(strategy_used="fast")
        with patch("webweb.router.read_fast", AsyncMock(return_value=good)) as mock_fast:
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="fast")
        mock_fast.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_browser_strategy_calls_read_browser(self):
        good = _make_result(strategy_used="browser")
        with patch("webweb.router.read_browser", AsyncMock(return_value=good)) as mock_b:
            from webweb.router import read_url
            await read_url("https://example.com", strategy="browser")
        mock_b.assert_called_once()

    @pytest.mark.asyncio
    async def test_crawl4ai_strategy_calls_read_crawl4ai(self):
        good = _make_result(strategy_used="crawl4ai")
        with patch("webweb.router.read_crawl4ai", AsyncMock(return_value=good)) as mock_c:
            from webweb.router import read_url
            await read_url("https://example.com", strategy="crawl4ai")
        mock_c.assert_called_once()

    @pytest.mark.asyncio
    async def test_invalid_strategy_raises(self):
        from webweb.router import read_url
        with pytest.raises(ValueError, match="Unknown strategy"):
            await read_url("https://example.com", strategy="invalid")


# ── auto degradation ───────────────────────────────────────────────────────────

class TestAutoDegradation:
    @pytest.mark.asyncio
    async def test_auto_stops_at_fast_when_good(self):
        good = _make_result(text="A" * 400, success=True, status_code=200)
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=good)) as mock_fast,
            patch("webweb.router.read_crawl4ai", AsyncMock()) as mock_c4ai,
            patch("webweb.router.read_browser", AsyncMock()) as mock_browser,
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")

        mock_fast.assert_called_once()
        mock_c4ai.assert_not_called()
        mock_browser.assert_not_called()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_auto_degrades_fast_to_crawl4ai(self):
        short = _make_result(text="short", success=True, status_code=200, attempts=[
            FetchAttempt(strategy="fast", success=True),
        ])
        good_c4ai = _make_result(text="A" * 500, strategy_used="crawl4ai", success=True, attempts=[
            FetchAttempt(strategy="crawl4ai", success=True),
        ])
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=short)),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=good_c4ai)) as mock_c4ai,
            patch("webweb.router.read_browser", AsyncMock()) as mock_browser,
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")

        mock_c4ai.assert_called_once()
        mock_browser.assert_not_called()
        assert result.success is True
        assert len(result.attempts) == 2

    @pytest.mark.asyncio
    async def test_auto_degrades_all_the_way_to_browser(self):
        fail = _make_result(text="x", success=False, attempts=[
            FetchAttempt(strategy="fast", success=False),
        ])
        fail_c4ai = _make_result(text="x", success=False, attempts=[
            FetchAttempt(strategy="crawl4ai", success=False),
        ])
        good_browser = _make_result(text="A" * 500, strategy_used="browser", success=True, attempts=[
            FetchAttempt(strategy="browser", success=True),
        ])
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=fail)),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=fail_c4ai)),
            patch("webweb.router.read_browser", AsyncMock(return_value=good_browser)),
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")

        assert result.success is True
        assert len(result.attempts) == 3

    @pytest.mark.asyncio
    async def test_auto_all_fail_returns_failure(self):
        fail = _make_result(text="x", success=False, error="oops", attempts=[
            FetchAttempt(strategy="fast", success=False, error="oops"),
        ])
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=fail)),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=fail)),
            patch("webweb.router.read_browser", AsyncMock(return_value=fail)),
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")

        assert result.success is False
        assert result.error is not None
