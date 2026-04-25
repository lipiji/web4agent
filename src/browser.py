"""Playwright-based dynamic page reader with browser instance reuse."""

from __future__ import annotations

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from typing import Any

from .config import BROWSER_CONCURRENCY, DEFAULT_TIMEOUT, USER_AGENT
from .models import FetchAttempt, WebReadResult
from .utils import (
    extract_text_bs4,
    extract_title_bs4,
    html_to_markdown,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

# ── Singleton browser manager ──────────────────────────────────────────────────

class _BrowserManager:
    """Holds a single Playwright browser instance, shared across calls."""

    def __init__(self) -> None:
        self._playwright: Any = None
        self._browser: Any = None
        self._lock = asyncio.Lock()
        self._semaphore = asyncio.Semaphore(BROWSER_CONCURRENCY)

    async def _ensure_browser(self) -> Any:
        async with self._lock:
            if self._browser is None or not self._browser.is_connected():
                try:
                    from playwright.async_api import async_playwright
                except ImportError as exc:
                    raise RuntimeError(
                        "Playwright is not installed. "
                        "Run: pip install 'webweb[browser]' && playwright install chromium"
                    ) from exc

                self._playwright = await async_playwright().start()
                self._browser = await self._playwright.chromium.launch(
                    headless=True,
                    args=[
                        "--no-sandbox",
                        "--disable-dev-shm-usage",
                        "--disable-blink-features=AutomationControlled",
                    ],
                )
                logger.debug("Playwright browser launched")
        return self._browser

    @asynccontextmanager
    async def acquire_page(self, user_agent: str):
        """Acquire a semaphore slot, yield a fresh page, and clean up on exit."""
        async with self._semaphore:
            browser = await self._ensure_browser()
            context = await browser.new_context(
                user_agent=user_agent,
                java_script_enabled=True,
            )
            page = await context.new_page()
            try:
                yield page
            finally:
                await page.close()
                await context.close()

    async def close(self) -> None:
        async with self._lock:
            if self._browser:
                await self._browser.close()
                self._browser = None
            if self._playwright:
                await self._playwright.stop()
                self._playwright = None
            logger.debug("Playwright browser closed")


_manager = _BrowserManager()


async def close_browser() -> None:
    """Explicitly close the shared browser instance."""
    await _manager.close()


# ── Main reader ────────────────────────────────────────────────────────────────

async def read_browser(
    url: str,
    wait_until: str = "networkidle",
    timeout: int = DEFAULT_TIMEOUT,
    screenshot: bool = False,
) -> WebReadResult:
    """
    Render a page with Playwright, extract content from the rendered DOM.

    Browser instance is reused across calls. Concurrency is limited to
    BROWSER_CONCURRENCY (default 3) simultaneous pages.
    """
    start = time.monotonic()
    fetched_at = utc_now_iso()

    try:
        async with _manager.acquire_page(USER_AGENT) as page:
            try:
                response = await page.goto(
                    url,
                    wait_until=wait_until,
                    timeout=timeout * 1000,
                )
                status_code = response.status if response else None

                # Scroll to bottom to trigger lazy loading
                await page.evaluate(
                    """() => {
                        return new Promise((resolve) => {
                            let distance = 0;
                            const step = 300;
                            const timer = setInterval(() => {
                                window.scrollBy(0, step);
                                distance += step;
                                if (distance >= document.body.scrollHeight) {
                                    clearInterval(timer);
                                    resolve();
                                }
                            }, 80);
                        });
                    }"""
                )

                # Give lazy content a moment to render
                await asyncio.sleep(0.5)

                html = await page.content()
                final_url = page.url

                elapsed_ms = int((time.monotonic() - start) * 1000)

                # Extract content
                try:
                    import trafilatura
                    text = trafilatura.extract(html, include_links=False)
                    meta = trafilatura.extract_metadata(html)
                    title = meta.title if meta else None
                except Exception:
                    text = None
                    title = None

                if not text:
                    text = extract_text_bs4(html)
                if not title:
                    title = extract_title_bs4(html)

                markdown = html_to_markdown(html)

                metadata: dict = {}
                if screenshot:
                    import base64
                    png = await page.screenshot(full_page=True)
                    metadata["screenshot_b64"] = base64.b64encode(png).decode()

                success = bool(text) and (status_code is None or status_code < 400)
                attempt = FetchAttempt(
                    strategy="browser",
                    success=success,
                    status_code=status_code,
                    elapsed_ms=elapsed_ms,
                )

                return WebReadResult(
                    url=url,
                    final_url=final_url,
                    title=title,
                    text=text,
                    markdown=markdown,
                    html=html,
                    status_code=status_code,
                    success=success,
                    strategy_used="browser",
                    attempts=[attempt],
                    fetched_at=fetched_at,
                    elapsed_ms=elapsed_ms,
                    metadata=metadata,
                )

            except Exception as exc:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                error = f"{type(exc).__name__}: {exc}"
                logger.warning("read_browser error %s: %s", url, error)
                return WebReadResult(
                    url=url,
                    success=False,
                    error=error,
                    strategy_used="browser",
                    attempts=[
                        FetchAttempt(
                            strategy="browser",
                            success=False,
                            error=error,
                            elapsed_ms=elapsed_ms,
                        )
                    ],
                    fetched_at=fetched_at,
                    elapsed_ms=elapsed_ms,
                )

    except RuntimeError as exc:
        error = str(exc)
        return WebReadResult(
            url=url,
            success=False,
            error=error,
            strategy_used="browser",
            attempts=[FetchAttempt(strategy="browser", success=False, error=error)],
            fetched_at=fetched_at,
        )
