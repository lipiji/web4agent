"""Crawl4AI-based reader for LLM-friendly Markdown output."""

from __future__ import annotations

import logging
import time

from .models import FetchAttempt, WebReadResult
from .utils import extract_title_bs4, utc_now_iso

logger = logging.getLogger(__name__)


async def read_crawl4ai(url: str) -> WebReadResult:
    """
    Fetch a URL using Crawl4AI's AsyncWebCrawler.

    Returns LLM-friendly Markdown preserving headings, links, and tables.
    Returns a structured error result if crawl4ai is not installed.
    """
    start = time.monotonic()
    fetched_at = utc_now_iso()

    try:
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
        from crawl4ai.markdown_generation_strategy import DefaultMarkdownGenerator
    except ImportError as exc:
        error = (
            "crawl4ai is not installed. "
            "Run: pip install 'webweb[crawl4ai]'"
        )
        logger.warning(error)
        return WebReadResult(
            url=url,
            success=False,
            error=error,
            strategy_used="crawl4ai",
            attempts=[FetchAttempt(strategy="crawl4ai", success=False, error=error)],
            fetched_at=fetched_at,
        )

    try:
        browser_cfg = BrowserConfig(headless=True, verbose=False)
        run_cfg = CrawlerRunConfig(
            markdown_generator=DefaultMarkdownGenerator(
                options={"ignore_links": False}
            )
        )

        async with AsyncWebCrawler(config=browser_cfg) as crawler:
            result = await crawler.arun(url=url, config=run_cfg)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        if not result.success:
            error = result.error_message or "crawl4ai returned failure"
            return WebReadResult(
                url=url,
                success=False,
                error=error,
                strategy_used="crawl4ai",
                attempts=[FetchAttempt(strategy="crawl4ai", success=False, error=error, elapsed_ms=elapsed_ms)],
                fetched_at=fetched_at,
                elapsed_ms=elapsed_ms,
            )

        html = result.html or ""
        markdown = (
            result.markdown.raw_markdown
            if hasattr(result.markdown, "raw_markdown")
            else str(result.markdown or "")
        )
        text = (
            result.markdown.fit_markdown
            if hasattr(result.markdown, "fit_markdown")
            else markdown
        )

        title = extract_title_bs4(html) if html else None

        attempt = FetchAttempt(
            strategy="crawl4ai",
            success=True,
            status_code=200,
            elapsed_ms=elapsed_ms,
        )

        return WebReadResult(
            url=url,
            final_url=result.url or url,
            title=title,
            text=text,
            markdown=markdown,
            html=html,
            status_code=200,
            success=True,
            strategy_used="crawl4ai",
            attempts=[attempt],
            fetched_at=fetched_at,
            elapsed_ms=elapsed_ms,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("read_crawl4ai error %s: %s", url, error)
        return WebReadResult(
            url=url,
            success=False,
            error=error,
            strategy_used="crawl4ai",
            attempts=[FetchAttempt(strategy="crawl4ai", success=False, error=error, elapsed_ms=elapsed_ms)],
            fetched_at=fetched_at,
            elapsed_ms=elapsed_ms,
        )
