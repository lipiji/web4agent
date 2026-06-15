"""SearXNG-powered web search — free, self-hostable, no API key required."""

from __future__ import annotations

import logging
import time
from collections.abc import Sequence
from typing import Any

import httpx

from .config import DEFAULT_TIMEOUT
from .fast import _browser_headers
from .utils import utc_now_iso

logger = logging.getLogger(__name__)

_PUBLIC_INSTANCES = [
    "https://searx.be",
    "https://search.sapti.me",
    "https://search.bus-hit.me",
    "https://searx.tiekoetter.com",
    "https://search.rowie.at",
]

_SEARCH_PATH = "/search"
_MAX_REDIRECTS = 3


def _select_instances(custom: str | None = None) -> list[str]:
    """Return ordered instance list — explicit custom first, then public pool."""
    if custom:
        return [custom]
    return list(_PUBLIC_INSTANCES)  # copy so caller may mutate


async def search_searx(
    query: str,
    *,
    instance: str | None = None,
    max_results: int = 10,
    timeout: int = DEFAULT_TIMEOUT,
    categories: str = "general",
) -> list[dict[str, Any]]:
    """
    Search via a SearXNG instance and return structured results.

    Parameters
    ----------
    query:       Search query string.
    instance:    SearXNG base URL. Uses public pool when omitted.
    max_results: Maximum results to return (<= request.engines).
    timeout:     Total request timeout in seconds.
    categories:  SearXNG category filter (``"general"``, ``"news"``, ``"science"``, …).

    Returns
    -------
    ``[{title, url, snippet, engine, score}, …]`` — empty list on failure.
    """
    instances = _select_instances(instance)
    headers = _browser_headers()
    headers["Accept"] = "application/json, text/html;q=0.9"

    for i, base_url in enumerate(instances):
        searx_url = f"{base_url.rstrip('/')}{_SEARCH_PATH}"
        params: dict[str, str | int] = {
            "q": query,
            "format": "json",
            "categories": categories,
        }
        try:
            async with httpx.AsyncClient(
                headers=headers,
                timeout=httpx.Timeout(timeout),
                follow_redirects=True,
                max_redirects=_MAX_REDIRECTS,
            ) as client:
                resp = await client.get(searx_url, params=params)
                resp.raise_for_status()
                data = resp.json()
        except Exception as exc:
            logger.debug("searx instance %s failed: %s", base_url, exc)
            if i < len(instances) - 1:
                continue  # try next instance
            logger.warning("All SearXNG instances exhausted for query %r", query)
            return []

        results: list[dict[str, Any]] = []
        for r in data.get("results", []):
            results.append({
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", "") or r.get("snippet", ""),
                "engine": ", ".join(r["engines"]) if isinstance(r.get("engines"), Sequence) else r.get("engine", ""),
                "score": r.get("score"),
            })
            if len(results) >= max_results:
                break
        return results

    return []


async def search_and_extract(
    query: str,
    *,
    instance: str | None = None,
    max_results: int = 10,
    extract_strategy: str = "auto",
    extract_concurrency: int = 5,
    search_timeout: int = DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """
    Full search → extract pipeline.  Searches via SearXNG, then fetches full
    page content for every result URL.  This is the free equivalent of paid
    tools like Tavily Search.

    Parameters
    ----------
    query:              Search query.
    instance:           SearXNG base URL (optional).
    max_results:        Number of search hits to extract.
    extract_strategy:   Strategy passed to the batch reader for each hit URL.
    extract_concurrency: Max simultaneous extractions.
    search_timeout:     Timeout for the SearXNG call.

    Returns
    -------
    ``{"query": str, "results": [...], "hits": int, "extracted": int}``
    """
    start = time.monotonic()

    search_hits = await search_searx(
        query,
        instance=instance,
        max_results=max_results,
        timeout=search_timeout,
    )
    if not search_hits:
        return {
            "query": query,
            "results": [],
            "hits": 0,
            "extracted": 0,
            "error": "No search results found",
        }

    urls = [h["url"] for h in search_hits]

    # Lazy import to avoid circular dependency
    from .batch import read_many

    extracted = await read_many(urls, concurrency=extract_concurrency, strategy=extract_strategy)

    results: list[dict[str, Any]] = []
    for hit, page in zip(search_hits, extracted):
        # Prefer extracted markdown, fall back to search snippet
        body = page.markdown or page.text
        if not body and page.html:
            from .utils import extract_text_bs4

            body = extract_text_bs4(page.html)
        content = body or hit["snippet"] or ""
        results.append({
            "url": hit["url"],
            "title": page.title or hit["title"],
            "content": content,
            "search_snippet": hit["snippet"],
            "search_engine": hit.get("engine"),
            "extracted": page.success,
            "source": page.strategy_used,
        })

    elapsed_ms = int((time.monotonic() - start) * 1000)
    extracted_count = sum(1 for r in results if r["extracted"])

    return {
        "query": query,
        "results": results,
        "hits": len(search_hits),
        "extracted": extracted_count,
        "elapsed_ms": elapsed_ms,
    }
