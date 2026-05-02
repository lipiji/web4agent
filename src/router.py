"""Strategy router: auto-degradation across fast -> crawl4ai -> browser -> wayback -> ddg."""

from __future__ import annotations

import logging

from .browser import read_browser
from .config import MIN_TEXT_LENGTH, USE_EXTENDED_FALLBACKS
from .crawl4ai_reader import read_crawl4ai
from .ddg_reader import read_ddg
from .fast import read_fast
from .models import WebReadResult
from .utils import looks_like_js_page
from .wayback_reader import read_wayback

logger = logging.getLogger(__name__)

_VALID_STRATEGIES = {"fast", "browser", "crawl4ai", "wayback", "ddg", "auto"}


def _should_degrade(result: WebReadResult) -> bool:
    """Return True if the result is insufficient and we should try next strategy."""
    if not result.success:
        return True
    if result.status_code is not None and result.status_code >= 400:
        return True
    text = result.text or ""
    if len(text.strip()) < MIN_TEXT_LENGTH:
        return True
    if result.html and looks_like_js_page(result.html, result.text):
        return True
    return False


def _merge_attempts(base: WebReadResult, extra: WebReadResult) -> WebReadResult:
    """Combine attempts from two results, prefer extra if it succeeded."""
    combined_attempts = base.attempts + extra.attempts
    winner = extra if extra.success else base
    return winner.model_copy(update={"attempts": combined_attempts})


async def read_url(url: str, strategy: str = "auto") -> WebReadResult:
    """
    Fetch a URL with the given strategy.

    strategy values
    ---------------
    fast      – httpx only
    crawl4ai  – Crawl4AI only
    browser   – Playwright only
    wayback   – archive.org Wayback Machine only
    ddg       – DuckDuckGo search snippet only
    auto      – fast → crawl4ai → browser → wayback → ddg (degrades on failure/empty content)
                Set WRT_EXTENDED_FALLBACKS=false to stop at browser.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}. Choose from {_VALID_STRATEGIES}.")

    if strategy == "fast":
        return await read_fast(url)

    if strategy == "crawl4ai":
        return await read_crawl4ai(url)

    if strategy == "browser":
        return await read_browser(url)

    if strategy == "wayback":
        return await read_wayback(url)

    if strategy == "ddg":
        return await read_ddg(url)

    # ── auto ──────────────────────────────────────────────────────────────────
    logger.debug("auto strategy: trying fast for %s", url)
    result = await read_fast(url)

    if not _should_degrade(result):
        return result

    logger.debug(
        "auto strategy: fast insufficient (%s chars, success=%s), trying crawl4ai for %s",
        len(result.text or ""),
        result.success,
        url,
    )
    c4ai_result = await read_crawl4ai(url)
    result = _merge_attempts(result, c4ai_result)

    if not _should_degrade(c4ai_result):
        return result

    logger.debug("auto strategy: crawl4ai insufficient, trying browser for %s", url)
    browser_result = await read_browser(url)
    result = _merge_attempts(result, browser_result)

    if not _should_degrade(browser_result):
        return result

    if not USE_EXTENDED_FALLBACKS:
        if result.success:
            return result
        return result.model_copy(
            update={
                "success": False,
                "error": result.error or c4ai_result.error or browser_result.error or "All strategies failed",
            }
        )

    # ── extended fallbacks ────────────────────────────────────────────────────
    logger.debug("auto strategy: browser insufficient, trying wayback for %s", url)
    wayback_result = await read_wayback(url)
    result = _merge_attempts(result, wayback_result)

    if not _should_degrade(wayback_result):
        return result

    logger.debug("auto strategy: wayback unavailable, trying ddg for %s", url)
    ddg_result = await read_ddg(url)
    result = _merge_attempts(result, ddg_result)

    # ddg snippets are intentionally short; accept any successful result
    if ddg_result.success:
        return result

    return result.model_copy(
        update={
            "success": False,
            "error": (
                result.error
                or c4ai_result.error
                or browser_result.error
                or wayback_result.error
                or ddg_result.error
                or "All strategies failed"
            ),
        }
    )
