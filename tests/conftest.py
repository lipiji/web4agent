"""Shared pytest fixtures."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _reset_strategy_health_tracker():
    """Reset the process-wide circuit breaker between tests.

    router.py's auto chain shares a module-level StrategyHealthTracker;
    without resetting it, failures recorded by one test could trip the
    breaker and silently skip a strategy mocked by a later test.
    """
    from web4agent.health import default_tracker

    default_tracker.reset()
    yield
    default_tracker.reset()
