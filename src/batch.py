"""Concurrent batch URL reading with asyncio.Semaphore."""

from __future__ import annotations

import asyncio
import logging

from .config import BROWSER_CONCURRENCY, FAST_CONCURRENCY
from .models import FetchAttempt, WebReadResult
from .router import read_url
from .utils import utc_now_iso

logger = logging.getLogger(__name__)

_VALID_STRATEGIES = {"fast", "crawl4ai", "browser", "wayback", "ddg", "auto"}

_STRATEGY_DEFAULT_CONCURRENCY = {
    "fast": FAST_CONCURRENCY,
    "crawl4ai": 10,
    "browser": BROWSER_CONCURRENCY,
    "wayback": 5,
    "ddg": 5,
    "auto": 10,
}


async def read_many(
    urls: list[str],
    concurrency: int | None = None,
    strategy: str = "auto",
    proxies: list[str] | None = None,
    proxy_mode: str = "round_robin",
) -> list[WebReadResult]:
    """
    Fetch multiple URLs concurrently, preserving input order.

    Parameters
    ----------
    urls:        List of URLs to fetch (duplicates deduplicated for fetching,
                 output list matches input order).
    concurrency: Max simultaneous requests. Defaults per strategy if None.
    strategy:    Passed to read_url for each URL.
    proxies:     Optional list of proxy URLs to rotate across requests.
                 Format: ``["http://host:port", "socks5://host:port"]``
    proxy_mode:  ``"round_robin"`` (default) or ``"random"``.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}. Choose from {_VALID_STRATEGIES}.")

    if concurrency is None:
        concurrency = _STRATEGY_DEFAULT_CONCURRENCY.get(strategy, 10)
    concurrency = max(concurrency, 1)

    rotator = None
    if proxies:
        from .proxy import ProxyRotator
        rotator = ProxyRotator(proxies, mode=proxy_mode)

    # Deduplicate while preserving order.
    seen: dict[str, int] = {}
    deduped: list[str] = []
    for url in urls:
        if url not in seen:
            seen[url] = len(deduped)
            deduped.append(url)

    semaphore = asyncio.Semaphore(concurrency)

    async def _fetch(url: str) -> WebReadResult:
        async with semaphore:
            proxy = rotator.next() if rotator else None
            try:
                result = await read_url(url, strategy=strategy, proxy=proxy)
                if rotator and proxy:
                    if result.success:
                        rotator.mark_success(proxy)
                    else:
                        rotator.mark_failed(proxy)
                return result
            except Exception as exc:
                logger.error("Unexpected error fetching %s: %s", url, exc)
                if proxy and rotator:
                    rotator.mark_failed(proxy)
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
        "read_many: %d URLs (%d unique), concurrency=%d, strategy=%s, proxies=%d",
        len(urls),
        len(deduped),
        concurrency,
        strategy,
        len(proxies) if proxies else 0,
    )

    tasks = [asyncio.create_task(_fetch(url)) for url in deduped]
    deduped_results = await asyncio.gather(*tasks)

    cache: dict[str, WebReadResult] = {url: deduped_results[i] for url, i in seen.items()}
    return [cache[url] for url in urls]
