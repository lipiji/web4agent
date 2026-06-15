"""Slim agent-facing interface returning LLM-context-friendly dicts."""

from __future__ import annotations

from typing import Any

from .batch import read_many
from .config import AGENT_MAX_CONTENT_CHARS
from .models import WebReadResult
from .router import read_url
from .utils import extract_text_bs4, truncate


def _slim(result: WebReadResult) -> dict:
    """Convert a WebReadResult into a compact dict for LLM context."""
    content = result.markdown or result.text
    if not content and result.html:
        extracted = extract_text_bs4(result.html)
        content = extracted or ""
    return {
        "url": result.url,
        "title": result.title,
        "content": truncate(content, AGENT_MAX_CONTENT_CHARS),
        "success": result.success,
        "strategy_used": result.strategy_used,
        "error": result.error,
    }


async def agent_read_url(
    url: str,
    strategy: str = "auto",
    proxy: str | None = None,
) -> dict:
    """
    Fetch a single URL and return a slim dict suitable for LLM context.

    Parameters
    ----------
    url:      URL to fetch.
    strategy: ``'fast'``, ``'crawl4ai'``, ``'browser'``, or ``'auto'``.
    proxy:    Optional proxy URL, e.g. ``"http://user:pass@host:port"``.
    """
    result = await read_url(url, strategy=strategy, proxy=proxy)
    return _slim(result)


async def agent_read_urls(
    urls: list[str],
    concurrency: int = 10,
    strategy: str = "auto",
    proxies: list[str] | None = None,
    proxy_mode: str = "round_robin",
) -> dict:
    """
    Fetch multiple URLs concurrently and return a summary dict.

    Parameters
    ----------
    urls:       List of URLs to fetch.
    concurrency: Max simultaneous requests.
    strategy:   Fetch strategy for each URL.
    proxies:    Optional proxy list to rotate across requests.
    proxy_mode: ``"round_robin"`` (default) or ``"random"``.

    Returns
    -------
    ``{"results": [...], "total": int, "succeeded": int, "failed": int}``
    """
    results = await read_many(
        urls,
        concurrency=concurrency,
        strategy=strategy,
        proxies=proxies,
        proxy_mode=proxy_mode,
    )
    slim_list = [_slim(r) for r in results]
    succeeded = sum(1 for r in results if r.success)
    return {
        "results": slim_list,
        "total": len(results),
        "succeeded": succeeded,
        "failed": len(results) - succeeded,
    }


async def agent_search(
    query: str,
    *,
    max_results: int = 10,
    extract_strategy: str = "auto",
    extract_concurrency: int = 5,
    instance: str | None = None,
) -> dict[str, Any]:
    """
    Search the web via SearXNG and extract full content for every result.

    The free, self-hostable equivalent of paid search APIs like Tavily.
    SearXNG aggregates Google, Bing, DuckDuckGo, Wikipedia and more.

    Parameters
    ----------
    query:              Search query (natural language or keywords).
    max_results:        Number of search hits to extract full content for.
    extract_strategy:   Strategy for extracting each result page.
    extract_concurrency: Max simultaneous extractions.
    instance:           Optional custom SearXNG base URL.  Uses a rotating
                        pool of public instances when omitted.

    Returns
    -------
    ``{"query": str, "results": [...], "hits": int, "extracted": int}``
    """
    from .searx import search_and_extract

    return await search_and_extract(
        query,
        instance=instance,
        max_results=max_results,
        extract_strategy=extract_strategy,
        extract_concurrency=extract_concurrency,
    )
