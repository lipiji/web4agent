"""Circuit breaker for the auto-degradation chain.

Mirrors ProxyRotator's failure-threshold/cooldown pattern (see proxy.py) but
applied to fetch strategies: a tier that fails repeatedly (dependency
missing, upstream rate-limited, service down) is skipped for a cooldown
window instead of being retried — and paying its latency cost — on every
single call.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from .config import HEALTH_COOLDOWN_SECONDS, HEALTH_FAILURE_THRESHOLD

logger = logging.getLogger(__name__)


@dataclass
class _Strategy:
    name: str
    failures: int = field(default=0)
    disabled_until: float = field(default=0.0)


class StrategyHealthTracker:
    """
    Tracks consecutive failures per fetch strategy and temporarily marks a
    strategy unavailable once it crosses ``failure_threshold``, automatically
    making it available again after ``cooldown_seconds``.
    """

    def __init__(
        self,
        failure_threshold: int = HEALTH_FAILURE_THRESHOLD,
        cooldown_seconds: float = HEALTH_COOLDOWN_SECONDS,
    ) -> None:
        self._failure_threshold = failure_threshold
        self._cooldown_seconds = cooldown_seconds
        self._strategies: dict[str, _Strategy] = {}

    def _get(self, name: str) -> _Strategy:
        if name not in self._strategies:
            self._strategies[name] = _Strategy(name=name)
        return self._strategies[name]

    def is_available(self, name: str) -> bool:
        """Return False while the strategy is within its cooldown window."""
        strategy = self._strategies.get(name)
        if strategy is None:
            return True
        return not (strategy.disabled_until and time.monotonic() < strategy.disabled_until)

    def mark_failure(self, name: str) -> None:
        """Record a failed attempt; disable the strategy after the threshold."""
        strategy = self._get(name)
        strategy.failures += 1
        if strategy.failures >= self._failure_threshold:
            strategy.disabled_until = time.monotonic() + self._cooldown_seconds
            logger.warning(
                "Strategy %r disabled for %.0fs after %d consecutive failures",
                name, self._cooldown_seconds, strategy.failures,
            )

    def mark_success(self, name: str) -> None:
        """Reset failure count and clear cooldown for a strategy that just worked."""
        strategy = self._get(name)
        strategy.failures = 0
        strategy.disabled_until = 0.0

    def status(self) -> list[dict]:
        """Return per-strategy status for diagnostics (used by `web4agent doctor`)."""
        now = time.monotonic()
        return [
            {
                "strategy": s.name,
                "failures": s.failures,
                "available": not (s.disabled_until and now < s.disabled_until),
                "cooldown_remaining_s": round(max(0.0, s.disabled_until - now), 1) if s.disabled_until else 0.0,
            }
            for s in self._strategies.values()
        ]

    def reset(self) -> None:
        """Clear all tracked state. Mainly useful for tests."""
        self._strategies.clear()


# Process-wide tracker shared by the auto-degradation router.
default_tracker = StrategyHealthTracker()
