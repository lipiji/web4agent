"""
web4agent
~~~~~~
Free, open-source, async-first web scraping toolkit for LLM agents.
"""

from .agent import agent_read_url, agent_read_urls, agent_search
from .batch import read_many
from .browser import read_browser
from .crawl4ai_reader import read_crawl4ai
from .ddg_reader import read_ddg, search_ddg
from .fast import read_fast
from .links import discover_links
from .models import FetchAttempt, WebReadResult
from .proxy import ProxyRotator
from .router import read_url
from .searx import search_and_extract, search_searx
from .wayback_reader import read_wayback

__all__ = [
    "read_url",
    "read_many",
    "read_fast",
    "read_browser",
    "read_crawl4ai",
    "read_wayback",
    "read_ddg",
    "discover_links",
    "search_searx",
    "search_and_extract",
    "agent_read_url",
    "agent_read_urls",
    "agent_search",
    "search_ddg",
    "WebReadResult",
    "FetchAttempt",
    "ProxyRotator",
]
