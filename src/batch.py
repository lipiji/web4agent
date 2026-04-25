"""Concurrent batch URL reading with asyncio.Semaphore."""

from __future__ import annotations

import asyncio
import logging

from .config import BROWSER_CONCURRENCY, FAST_CONCURRENCY
from .models import FetchAttempt, WebReadResult
from .router import read_url
from .utils import utc_now_iso

logger = logging.getLogger(__name__)

_STRATEGY_DEFAULT_CONCURRENCY = {
    "fast": FAST_CONCURRENCY,
    "crawl4ai": 10,
    "browser": BROWSER_CONCURRENCY,
    "auto": 10,
}


async def read_many(
    urls: list[str],
    concurrency: int | None = None,
    strategy: str = "auto",
) -> list[WebReadResult]:
    """
    Fetch multiple URLs concurrently, preserving input order.

    Parameters
    ----------
    urls:        List of URLs to fetch (duplicates deduplicated for fetching,
                 but output list matches input order).
    concurrency: Max simultaneous requests. Defaults per strategy if None.
    strategy:    Passed to read_url for each URL.
    """
    if concurrency is None:
        concurrency = _STRATEGY_DEFAULT_CONCURRENCY.get(strategy, 10)

    # Deduplicate while preserving order; track indices
    seen: dict[str, int] = {}  # url -> index in deduplicated list
    deduped: list[str] = []
    for url in urls:
        if url not in seen:
            seen[url] = len(deduped)
            deduped.append(url)

    semaphore = asyncio.Semaphore(concurrency)

    async def _fetch(url: str) -> WebReadResult:
        async with semaphore:
            try:
                return await read_url(url, strategy=strategy)
            except Exception as exc:
                logger.error("Unexpected error fetching %s: %s", url, exc)
                error = f"{type(exc).__name__}: {exc}"
                return WebReadResult(
                    url=url,
                    success=False,
                    error=error,
                    strategy_used=strategy,
                    attempts=[FetchAttempt(strategy=strategy, success=False, error=error)],
                    fetched_at=utc_now_iso(),
                )

    logger.info(
        "read_many: %d URLs (%d unique), concurrency=%d, strategy=%s",
        len(urls),
        len(deduped),
        concurrency,
        strategy,
    )

    tasks = [asyncio.create_task(_fetch(url)) for url in deduped]
    deduped_results = await asyncio.gather(*tasks)

    # Map results back to original (possibly duplicate) URL list
    cache: dict[str, WebReadResult] = {url: deduped_results[i] for url, i in seen.items()}
    return [cache[url] for url in urls]
