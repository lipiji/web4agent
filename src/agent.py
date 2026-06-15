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
    Search the web and extract full content for every result.

    Uses DuckDuckGo first (reliable, free, no API key), falls back to
    SearXNG public instances.  The free equivalent of paid search APIs
    like Tavily.

    Parameters
    ----------
    query:              Search query (natural language or keywords).
    max_results:        Number of search hits to extract full content for.
    extract_strategy:   Strategy for extracting each result page.
    extract_concurrency: Max simultaneous extractions.
    instance:           Optional custom SearXNG base URL (only used as
                        fallback when DDG returns no results).

    Returns
    -------
    ``{"query": str, "results": [...], "hits": int, "extracted": int}``
    """
    import time

    from .ddg_reader import search_ddg
    from .searx import search_searx

    start = time.monotonic()

    # 1) Try DDG first — reliable, free, no rate limits
    hits = await search_ddg(query, max_results=max_results)
    search_backend = "ddg"

    # 2) Fall back to SearXNG if DDG returned nothing
    if not hits:
        hits = await search_searx(query, max_results=max_results, instance=instance)
        search_backend = "searxng"

    if not hits:
        return {
            "query": query,
            "results": [],
            "hits": 0,
            "extracted": 0,
            "search_backend": search_backend,
            "error": "No search results found",
        }

    urls = [h["url"] for h in hits if h.get("url")]
    extracted = await read_many(urls, concurrency=extract_concurrency, strategy=extract_strategy)

    results: list[dict[str, Any]] = []
    for hit, page in zip(hits, extracted):
        body = page.markdown or page.text
        if not body and page.html:
            body = extract_text_bs4(page.html)
        results.append({
            "url": hit["url"],
            "title": page.title or hit.get("title", ""),
            "content": body or hit.get("snippet", ""),
            "search_snippet": hit.get("snippet", ""),
            "extracted": page.success,
            "source": page.strategy_used,
        })

    elapsed_ms = int((time.monotonic() - start) * 1000)
    return {
        "query": query,
        "results": results,
        "hits": len(hits),
        "extracted": sum(1 for r in results if r["extracted"]),
        "search_backend": search_backend,
        "elapsed_ms": elapsed_ms,
    }
