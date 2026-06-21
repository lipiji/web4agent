"""Tests for StrategyHealthTracker (circuit breaker for the auto chain)."""

from __future__ import annotations

from unittest.mock import patch

from web4agent.health import StrategyHealthTracker


class TestStrategyHealthTrackerBasics:
    def test_unknown_strategy_is_available(self):
        t = StrategyHealthTracker()
        assert t.is_available("crawl4ai") is True

    def test_single_failure_keeps_available(self):
        t = StrategyHealthTracker(failure_threshold=3)
        t.mark_failure("crawl4ai")
        assert t.is_available("crawl4ai") is True

    def test_disabled_after_threshold(self):
        t = StrategyHealthTracker(failure_threshold=3, cooldown_seconds=60)
        for _ in range(3):
            t.mark_failure("crawl4ai")
        assert t.is_available("crawl4ai") is False

    def test_other_strategies_unaffected(self):
        t = StrategyHealthTracker(failure_threshold=3)
        for _ in range(3):
            t.mark_failure("crawl4ai")
        assert t.is_available("browser") is True

    def test_mark_success_resets_failures(self):
        t = StrategyHealthTracker(failure_threshold=3)
        t.mark_failure("crawl4ai")
        t.mark_failure("crawl4ai")
        t.mark_success("crawl4ai")
        assert t._strategies["crawl4ai"].failures == 0
        assert t.is_available("crawl4ai") is True

    def test_mark_success_clears_disabled_state(self):
        t = StrategyHealthTracker(failure_threshold=2, cooldown_seconds=60)
        t.mark_failure("ddg")
        t.mark_failure("ddg")
        assert t.is_available("ddg") is False
        t.mark_success("ddg")
        assert t.is_available("ddg") is True


class TestCooldownExpiry:
    def test_available_again_after_cooldown_elapses(self):
        t = StrategyHealthTracker(failure_threshold=1, cooldown_seconds=10)
        with patch("web4agent.health.time.monotonic", return_value=100.0):
            t.mark_failure("wayback")
            assert t.is_available("wayback") is False
        with patch("web4agent.health.time.monotonic", return_value=111.0):
            assert t.is_available("wayback") is True

    def test_still_disabled_before_cooldown_elapses(self):
        t = StrategyHealthTracker(failure_threshold=1, cooldown_seconds=10)
        with patch("web4agent.health.time.monotonic", return_value=100.0):
            t.mark_failure("wayback")
        with patch("web4agent.health.time.monotonic", return_value=105.0):
            assert t.is_available("wayback") is False


class TestStatus:
    def test_empty_tracker_returns_empty_list(self):
        t = StrategyHealthTracker()
        assert t.status() == []

    def test_status_reports_failures_and_availability(self):
        t = StrategyHealthTracker(failure_threshold=5)
        t.mark_failure("crawl4ai")
        t.mark_failure("crawl4ai")
        status = t.status()
        assert len(status) == 1
        assert status[0]["strategy"] == "crawl4ai"
        assert status[0]["failures"] == 2
        assert status[0]["available"] is True

    def test_status_shows_disabled_with_cooldown_remaining(self):
        t = StrategyHealthTracker(failure_threshold=1, cooldown_seconds=30)
        with patch("web4agent.health.time.monotonic", return_value=100.0):
            t.mark_failure("ddg")
        with patch("web4agent.health.time.monotonic", return_value=110.0):
            status = t.status()
        entry = next(s for s in status if s["strategy"] == "ddg")
        assert entry["available"] is False
        assert entry["cooldown_remaining_s"] == 20.0


class TestReset:
    def test_reset_clears_all_state(self):
        t = StrategyHealthTracker(failure_threshold=1)
        t.mark_failure("crawl4ai")
        t.reset()
        assert t.status() == []
        assert t.is_available("crawl4ai") is True


class TestDefaultTracker:
    def test_default_tracker_is_strategy_health_tracker(self):
        from web4agent.health import default_tracker
        assert isinstance(default_tracker, StrategyHealthTracker)
