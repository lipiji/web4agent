"""
webweb
~~~~~~
Free, open-source, async-first web scraping toolkit for LLM agents.
"""

from .agent import agent_read_url, agent_read_urls
from .batch import read_many
from .browser import read_browser
from .crawl4ai_reader import read_crawl4ai
from .fast import read_fast
from .links import discover_links
from .models import FetchAttempt, WebReadResult
from .router import read_url

__all__ = [
    "read_url",
    "read_many",
    "read_fast",
    "read_browser",
    "read_crawl4ai",
    "discover_links",
    "agent_read_url",
    "agent_read_urls",
    "WebReadResult",
    "FetchAttempt",
]
