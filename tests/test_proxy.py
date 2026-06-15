"""Tests for ProxyRotator."""

from __future__ import annotations

import pytest

from web4agent.proxy import ProxyRotator, _FAILURE_THRESHOLD


class TestProxyRotatorInit:
    def test_round_robin_is_default_mode(self):
        r = ProxyRotator(["http://p1:8080"])
        assert r._mode == "round_robin"

    def test_random_mode_accepted(self):
        r = ProxyRotator(["http://p1:8080"], mode="random")
        assert r._mode == "random"

    def test_invalid_mode_raises(self):
        with pytest.raises(ValueError, match="mode must be"):
            ProxyRotator(["http://p1:8080"], mode="invalid")

    def test_empty_list_accepted(self):
        r = ProxyRotator([])
        assert r.next() is None


class TestProxyRotatorRoundRobin:
    def test_cycles_through_proxies(self):
        r = ProxyRotator(["http://p1", "http://p2", "http://p3"])
        results = [r.next() for _ in range(6)]
        assert results[:3] == ["http://p1", "http://p2", "http://p3"]
        assert results[3:] == ["http://p1", "http://p2", "http://p3"]

    def test_single_proxy_always_returns_same(self):
        r = ProxyRotator(["http://p1"])
        assert r.next() == "http://p1"
        assert r.next() == "http://p1"

    def test_returns_none_on_empty_list(self):
        r = ProxyRotator([])
        assert r.next() is None


class TestProxyRotatorRandom:
    def test_always_returns_from_list(self):
        proxies = ["http://p1", "http://p2", "http://p3"]
        r = ProxyRotator(proxies, mode="random")
        for _ in range(20):
            assert r.next() in proxies


class TestProxyRotatorFailureTracking:
    def test_mark_failed_increments_count(self):
        r = ProxyRotator(["http://p1"])
        r.mark_failed("http://p1")
        assert r._slots[0].failures == 1

    def test_proxy_disabled_after_threshold(self):
        r = ProxyRotator(["http://p1", "http://p2"])
        for _ in range(_FAILURE_THRESHOLD):
            r.mark_failed("http://p1")
        assert r._slots[0].active is False

    def test_disabled_proxy_skipped_in_rotation(self):
        r = ProxyRotator(["http://p1", "http://p2"])
        for _ in range(_FAILURE_THRESHOLD):
            r.mark_failed("http://p1")
        # Only p2 should come out now
        results = {r.next() for _ in range(6)}
        assert results == {"http://p2"}

    def test_mark_success_resets_failures(self):
        r = ProxyRotator(["http://p1"])
        r.mark_failed("http://p1")
        r.mark_failed("http://p1")
        r.mark_success("http://p1")
        assert r._slots[0].failures == 0
        assert r._slots[0].active is True

    def test_mark_success_reactivates_disabled_proxy(self):
        r = ProxyRotator(["http://p1", "http://p2"])
        for _ in range(_FAILURE_THRESHOLD):
            r.mark_failed("http://p1")
        assert r._slots[0].active is False
        r.mark_success("http://p1")
        assert r._slots[0].active is True

    def test_mark_failed_on_unknown_proxy_is_noop(self):
        r = ProxyRotator(["http://p1"])
        r.mark_failed("http://unknown")  # should not raise
        assert r._slots[0].failures == 0

    def test_mark_success_on_unknown_proxy_is_noop(self):
        r = ProxyRotator(["http://p1"])
        r.mark_success("http://unknown")  # should not raise
        assert r._slots[0].failures == 0


class TestProxyRotatorReset:
    def test_all_proxies_exhausted_triggers_reset(self):
        """When all proxies are disabled, the rotator resets and returns a proxy."""
        r = ProxyRotator(["http://p1", "http://p2"])
        for proxy in ["http://p1", "http://p2"]:
            for _ in range(_FAILURE_THRESHOLD):
                r.mark_failed(proxy)

        # All disabled — next() should reset and still return something
        result = r.next()
        assert result is not None
        assert result in ("http://p1", "http://p2")
        # Failures reset
        assert all(s.failures == 0 for s in r._slots)
        assert all(s.active for s in r._slots)


class TestProxyRotatorStats:
    def test_stats_returns_list_of_dicts(self):
        r = ProxyRotator(["http://p1", "http://p2"])
        stats = r.stats()
        assert isinstance(stats, list)
        assert len(stats) == 2

    def test_stats_keys(self):
        r = ProxyRotator(["http://p1"])
        stat = r.stats()[0]
        assert "proxy" in stat
        assert "failures" in stat
        assert "active" in stat

    def test_stats_reflects_failures(self):
        r = ProxyRotator(["http://p1"])
        r.mark_failed("http://p1")
        assert r.stats()[0]["failures"] == 1

    def test_stats_reflects_disabled(self):
        r = ProxyRotator(["http://p1"])
        for _ in range(_FAILURE_THRESHOLD):
            r.mark_failed("http://p1")
        assert r.stats()[0]["active"] is False
