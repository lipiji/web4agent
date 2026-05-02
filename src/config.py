"""Configuration with environment variable support."""

from __future__ import annotations

import os

DEFAULT_TIMEOUT: int = int(os.environ.get("WRT_TIMEOUT", "20"))
FAST_CONCURRENCY: int = int(os.environ.get("WRT_FAST_CONCURRENCY", "50"))
CRAWL4AI_CONCURRENCY: int = int(os.environ.get("WRT_CRAWL4AI_CONCURRENCY", "10"))
BROWSER_CONCURRENCY: int = int(os.environ.get("WRT_BROWSER_CONCURRENCY", "3"))
MIN_TEXT_LENGTH: int = int(os.environ.get("WRT_MIN_TEXT_LENGTH", "300"))

USER_AGENT: str = os.environ.get(
    "WRT_USER_AGENT",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36",
)

# Max content length returned to agent context (characters)
AGENT_MAX_CONTENT_CHARS: int = int(os.environ.get("WRT_AGENT_MAX_CONTENT_CHARS", "8000"))

# Whether to use Wayback Machine + DuckDuckGo as final fallbacks in auto mode
USE_EXTENDED_FALLBACKS: bool = os.environ.get("WRT_EXTENDED_FALLBACKS", "true").lower() == "true"
