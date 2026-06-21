"""Tests for the doctor diagnostics module."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from web4agent.doctor import _check_dependencies, format_report, run_doctor


class TestCheckDependencies:
    def test_returns_entry_per_optional_dep(self):
        deps = _check_dependencies()
        names = {d["name"] for d in deps}
        assert "crawl4ai" in names

    def test_each_entry_has_installed_flag(self):
        deps = _check_dependencies()
        for d in deps:
            assert isinstance(d["installed"], bool)

    def test_detects_installed_stdlib_module(self):
        with patch("web4agent.doctor._OPTIONAL_DEPS", {"json (stdlib)": "json"}):
            deps = _check_dependencies()
        assert deps == [{"name": "json (stdlib)", "module": "json", "installed": True}]

    def test_detects_missing_module(self):
        with patch("web4agent.doctor._OPTIONAL_DEPS", {"nope": "definitely_not_a_real_module_xyz"}):
            deps = _check_dependencies()
        assert deps == [{"name": "nope", "module": "definitely_not_a_real_module_xyz", "installed": False}]


class TestRunDoctor:
    @pytest.mark.asyncio
    async def test_report_has_all_sections(self):
        fake_connectivity = [{"target": "wayback", "url": "https://archive.org", "reachable": True}]
        with patch("web4agent.doctor._check_connectivity", AsyncMock(return_value=fake_connectivity)):
            report = await run_doctor()
        assert "dependencies" in report
        assert "connectivity" in report
        assert "circuit_breakers" in report

    @pytest.mark.asyncio
    async def test_connectivity_failure_is_reported_not_raised(self):
        from web4agent.doctor import _check_connectivity

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(side_effect=ConnectionError("boom"))
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            results = await _check_connectivity()

        assert all(r["reachable"] is False for r in results)
        assert all("boom" in r["error"] for r in results)

    @pytest.mark.asyncio
    async def test_connectivity_checks_run_concurrently(self):
        """Two slow targets should take ~1 round-trip, not 2 sequential ones."""
        import asyncio
        import time

        from web4agent.doctor import _check_connectivity

        async def slow_head(*args, **kwargs):
            await asyncio.sleep(0.1)
            return MagicMock(status_code=200)

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(side_effect=slow_head)
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            start = time.monotonic()
            results = await _check_connectivity()
            elapsed = time.monotonic() - start

        assert len(results) == 2
        assert elapsed < 0.2

    @pytest.mark.asyncio
    async def test_connectivity_success_path(self):
        from web4agent.doctor import _check_connectivity

        resp = MagicMock(status_code=200)
        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.head = AsyncMock(return_value=resp)
            mock_client_cls.return_value.__aenter__.return_value = mock_client
            results = await _check_connectivity()

        assert all(r["reachable"] is True for r in results)


class TestFormatReport:
    def test_human_readable_output_contains_sections(self):
        report = {
            "dependencies": [{"name": "crawl4ai", "module": "crawl4ai", "installed": False}],
            "connectivity": [{"target": "wayback", "url": "https://archive.org", "reachable": True}],
            "circuit_breakers": [],
        }
        text = format_report(report)
        assert "Dependencies:" in text
        assert "Connectivity:" in text
        assert "Circuit breakers:" in text
        assert "MISSING" in text
        assert "OK" in text

    def test_open_breaker_shown_with_cooldown(self):
        report = {
            "dependencies": [],
            "connectivity": [],
            "circuit_breakers": [
                {"strategy": "ddg", "failures": 3, "available": False, "cooldown_remaining_s": 12.0}
            ],
        }
        text = format_report(report)
        assert "OPEN" in text
        assert "retry in 12.0s" in text

    def test_no_breakers_tripped_message(self):
        report = {"dependencies": [], "connectivity": [], "circuit_breakers": []}
        text = format_report(report)
        assert "nothing tripped" in text
