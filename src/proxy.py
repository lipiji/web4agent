"""Proxy rotation with automatic failure tracking."""

from __future__ import annotations

import logging
import random
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

_FAILURE_THRESHOLD = 3


@dataclass
class _Slot:
    url: str
    failures: int = field(default=0)
    active: bool = field(default=True)


class ProxyRotator:
    """
    Rotates over a list of proxy URLs, disabling ones that fail repeatedly.

    Proxy format: ``"http://user:pass@host:port"`` or ``"socks5://host:port"``

    Example::

        rotator = ProxyRotator(["http://p1:8080", "http://p2:8080"])

        proxy = rotator.next()
        try:
            result = await read_url(url, proxy=proxy)
            rotator.mark_success(proxy)
        except Exception:
            rotator.mark_failed(proxy)
    """

    def __init__(self, proxies: list[str], mode: str = "round_robin") -> None:
        if mode not in ("round_robin", "random"):
            raise ValueError(f"mode must be 'round_robin' or 'random', got {mode!r}")
        self._slots = [_Slot(url=p) for p in proxies]
        self._mode = mode
        self._cursor = 0

    # ── internal ──────────────────────────────────────────────────────────────

    def _active(self) -> list[_Slot]:
        active = [s for s in self._slots if s.active]
        if not active:
            logger.warning("All proxies exhausted — resetting failure counts")
            for s in self._slots:
                s.failures = 0
                s.active = True
            active = self._slots[:]
        return active

    # ── public API ────────────────────────────────────────────────────────────

    def next(self) -> str | None:
        """Return the next proxy URL, or ``None`` when the list is empty."""
        if not self._slots:
            return None
        active = self._active()
        if self._mode == "random":
            return random.choice(active).url
        slot = active[self._cursor % len(active)]
        self._cursor = (self._cursor + 1) % len(active)
        return slot.url

    def mark_failed(self, proxy_url: str) -> None:
        """Increment failure count; disable the proxy after repeated failures."""
        for i, s in enumerate(self._slots):
            if s.url == proxy_url:
                s.failures += 1
                if s.failures >= _FAILURE_THRESHOLD:
                    s.active = False
                    logger.warning("Proxy disabled (%d failures): %s", _FAILURE_THRESHOLD, proxy_url)
                    # Reset cursor so it stays in the remaining active range.
                    if i <= self._cursor:
                        self._cursor = 0
                return

    def mark_success(self, proxy_url: str) -> None:
        """Reset failure count for a proxy that just worked."""
        for s in self._slots:
            if s.url == proxy_url:
                s.failures = 0
                s.active = True
                return

    def stats(self) -> list[dict]:
        """Return per-proxy status for inspection."""
        return [{"proxy": s.url, "failures": s.failures, "active": s.active} for s in self._slots]
