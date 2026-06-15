"""Configuration with environment variable support."""

from __future__ import annotations

import os


def _env_int(key: str, default: int) -> int:
    val = os.environ.get(key, "")
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    val = os.environ.get(key, "").strip().lower()
    if not val:
        return default
    return val in ("true", "1", "yes", "on")


DEFAULT_TIMEOUT: int = _env_int("WRT_TIMEOUT", 20)
FAST_CONCURRENCY: int = _env_int("WRT_FAST_CONCURRENCY", 50)
CRAWL4AI_CONCURRENCY: int = _env_int("WRT_CRAWL4AI_CONCURRENCY", 10)
BROWSER_CONCURRENCY: int = _env_int("WRT_BROWSER_CONCURRENCY", 3)
MIN_TEXT_LENGTH: int = _env_int("WRT_MIN_TEXT_LENGTH", 300)

USER_AGENT: str = os.environ.get(
    "WRT_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
)

AGENT_MAX_CONTENT_CHARS: int = _env_int("WRT_AGENT_MAX_CONTENT_CHARS", 8000)

USE_EXTENDED_FALLBACKS: bool = _env_bool("WRT_EXTENDED_FALLBACKS", True)
