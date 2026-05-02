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
            patch("webweb.router.read_wayback", AsyncMock(return_value=fail)),
            patch("webweb.router.read_ddg", AsyncMock(return_value=fail)),
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")

        assert result.success is False
        assert result.error is not None


# ── new strategies dispatch ────────────────────────────────────────────────────

class TestNewStrategiesDispatch:
    @pytest.mark.asyncio
    async def test_wayback_strategy_calls_read_wayback(self):
        good = _make_result(strategy_used="wayback")
        with patch("webweb.router.read_wayback", AsyncMock(return_value=good)) as mock_wb:
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="wayback")
        mock_wb.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_ddg_strategy_calls_read_ddg(self):
        good = _make_result(strategy_used="ddg")
        with patch("webweb.router.read_ddg", AsyncMock(return_value=good)) as mock_ddg:
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="ddg")
        mock_ddg.assert_called_once_with("https://example.com")

    @pytest.mark.asyncio
    async def test_all_six_strategies_are_valid(self):
        from webweb.router import _VALID_STRATEGIES
        for strategy in ("fast", "crawl4ai", "browser", "wayback", "ddg", "auto"):
            assert strategy in _VALID_STRATEGIES


# ── extended fallback chain ────────────────────────────────────────────────────

class TestExtendedFallbackChain:
    def _make_fail(self, strategy: str) -> WebReadResult:
        return _make_result(
            text="x",
            success=False,
            error="fail",
            strategy_used=strategy,
            attempts=[FetchAttempt(strategy=strategy, success=False, error="fail")],
        )

    def _make_good(self, strategy: str) -> WebReadResult:
        return _make_result(
            text="A" * 500,
            success=True,
            strategy_used=strategy,
            attempts=[FetchAttempt(strategy=strategy, success=True)],
        )

    def _make_degraded(self, strategy: str) -> WebReadResult:
        """Succeeds but content is too short to satisfy _should_degrade."""
        return _make_result(
            text="short",
            success=True,
            status_code=200,
            strategy_used=strategy,
            attempts=[FetchAttempt(strategy=strategy, success=True)],
        )

    @pytest.mark.asyncio
    async def test_wayback_called_when_browser_fails(self):
        good_wayback = self._make_good("wayback")
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=self._make_fail("fast"))),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=self._make_fail("crawl4ai"))),
            patch("webweb.router.read_browser", AsyncMock(return_value=self._make_fail("browser"))),
            patch("webweb.router.read_wayback", AsyncMock(return_value=good_wayback)) as mock_wb,
            patch("webweb.router.read_ddg", AsyncMock()) as mock_ddg,
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        mock_wb.assert_called_once()
        mock_ddg.assert_not_called()
        assert result.success is True
        assert result.strategy_used == "wayback"

    @pytest.mark.asyncio
    async def test_wayback_called_when_browser_content_degraded(self):
        good_wayback = self._make_good("wayback")
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=self._make_fail("fast"))),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=self._make_fail("crawl4ai"))),
            patch("webweb.router.read_browser", AsyncMock(return_value=self._make_degraded("browser"))),
            patch("webweb.router.read_wayback", AsyncMock(return_value=good_wayback)) as mock_wb,
            patch("webweb.router.read_ddg", AsyncMock()),
        ):
            from webweb.router import read_url
            await read_url("https://example.com", strategy="auto")
        mock_wb.assert_called_once()

    @pytest.mark.asyncio
    async def test_ddg_called_when_wayback_fails(self):
        good_ddg = self._make_good("ddg")
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=self._make_fail("fast"))),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=self._make_fail("crawl4ai"))),
            patch("webweb.router.read_browser", AsyncMock(return_value=self._make_fail("browser"))),
            patch("webweb.router.read_wayback", AsyncMock(return_value=self._make_fail("wayback"))),
            patch("webweb.router.read_ddg", AsyncMock(return_value=good_ddg)) as mock_ddg,
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        mock_ddg.assert_called_once()
        assert result.success is True
        assert result.strategy_used == "ddg"

    @pytest.mark.asyncio
    async def test_ddg_called_when_wayback_content_degraded(self):
        good_ddg = self._make_good("ddg")
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=self._make_fail("fast"))),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=self._make_fail("crawl4ai"))),
            patch("webweb.router.read_browser", AsyncMock(return_value=self._make_fail("browser"))),
            patch("webweb.router.read_wayback", AsyncMock(return_value=self._make_degraded("wayback"))),
            patch("webweb.router.read_ddg", AsyncMock(return_value=good_ddg)) as mock_ddg,
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        mock_ddg.assert_called_once()
        assert result.success is True

    @pytest.mark.asyncio
    async def test_ddg_short_snippet_still_accepted(self):
        """DDG snippets bypass _should_degrade — accepted if success=True."""
        short_ddg = _make_result(
            text="Short snippet.",
            success=True,
            strategy_used="ddg",
            attempts=[FetchAttempt(strategy="ddg", success=True)],
        )
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=self._make_fail("fast"))),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=self._make_fail("crawl4ai"))),
            patch("webweb.router.read_browser", AsyncMock(return_value=self._make_fail("browser"))),
            patch("webweb.router.read_wayback", AsyncMock(return_value=self._make_fail("wayback"))),
            patch("webweb.router.read_ddg", AsyncMock(return_value=short_ddg)),
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        assert result.success is True
        assert result.strategy_used == "ddg"

    @pytest.mark.asyncio
    async def test_all_five_fail_returns_failure(self):
        fail = self._make_fail("any")
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=fail)),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=fail)),
            patch("webweb.router.read_browser", AsyncMock(return_value=fail)),
            patch("webweb.router.read_wayback", AsyncMock(return_value=fail)),
            patch("webweb.router.read_ddg", AsyncMock(return_value=fail)),
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        assert result.success is False
        assert result.error is not None

    @pytest.mark.asyncio
    async def test_all_five_fail_accumulates_all_attempts(self):
        fail = _make_result(
            text="x",
            success=False,
            error="fail",
            attempts=[FetchAttempt(strategy="s", success=False)],
        )
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=fail)),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=fail)),
            patch("webweb.router.read_browser", AsyncMock(return_value=fail)),
            patch("webweb.router.read_wayback", AsyncMock(return_value=fail)),
            patch("webweb.router.read_ddg", AsyncMock(return_value=fail)),
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        assert len(result.attempts) == 5

    @pytest.mark.asyncio
    async def test_wayback_not_called_when_browser_succeeds_with_good_content(self):
        """Browser with good content should short-circuit without calling wayback."""
        good_browser = self._make_good("browser")
        with (
            patch("webweb.router.read_fast", AsyncMock(return_value=self._make_fail("fast"))),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=self._make_fail("crawl4ai"))),
            patch("webweb.router.read_browser", AsyncMock(return_value=good_browser)),
            patch("webweb.router.read_wayback", AsyncMock()) as mock_wb,
            patch("webweb.router.read_ddg", AsyncMock()) as mock_ddg,
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        mock_wb.assert_not_called()
        mock_ddg.assert_not_called()
        assert result.success is True


# ── USE_EXTENDED_FALLBACKS=False ──────────────────────────────────────────────

class TestExtendedFallbacksDisabled:
    def _make_fail(self, strategy: str) -> WebReadResult:
        return _make_result(
            text="x",
            success=False,
            error="fail",
            strategy_used=strategy,
            attempts=[FetchAttempt(strategy=strategy, success=False, error="fail")],
        )

    def _make_good(self, strategy: str) -> WebReadResult:
        return _make_result(
            text="A" * 500,
            success=True,
            strategy_used=strategy,
            attempts=[FetchAttempt(strategy=strategy, success=True)],
        )

    @pytest.mark.asyncio
    async def test_wayback_not_called_when_extended_disabled(self):
        fail = self._make_fail("browser")
        with (
            patch("webweb.router.USE_EXTENDED_FALLBACKS", False),
            patch("webweb.router.read_fast", AsyncMock(return_value=fail)),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=fail)),
            patch("webweb.router.read_browser", AsyncMock(return_value=fail)),
            patch("webweb.router.read_wayback", AsyncMock()) as mock_wb,
            patch("webweb.router.read_ddg", AsyncMock()) as mock_ddg,
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        mock_wb.assert_not_called()
        mock_ddg.assert_not_called()
        assert result.success is False

    @pytest.mark.asyncio
    async def test_partial_success_returned_when_extended_disabled(self):
        """If browser degraded but success=True, return it rather than force failure."""
        partial = _make_result(
            text="short",
            success=True,
            status_code=200,
            strategy_used="browser",
            attempts=[FetchAttempt(strategy="browser", success=True)],
        )
        with (
            patch("webweb.router.USE_EXTENDED_FALLBACKS", False),
            patch("webweb.router.read_fast", AsyncMock(return_value=self._make_fail("fast"))),
            patch("webweb.router.read_crawl4ai", AsyncMock(return_value=self._make_fail("crawl4ai"))),
            patch("webweb.router.read_browser", AsyncMock(return_value=partial)),
            patch("webweb.router.read_wayback", AsyncMock()),
            patch("webweb.router.read_ddg", AsyncMock()),
        ):
            from webweb.router import read_url
            result = await read_url("https://example.com", strategy="auto")
        # Should return the partial success rather than failing
        assert result.success is True
