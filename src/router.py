"""Strategy router: auto-degradation across fast -> crawl4ai -> browser."""

from __future__ import annotations

import logging

from .browser import read_browser
from .config import MIN_TEXT_LENGTH
from .crawl4ai_reader import read_crawl4ai
from .fast import read_fast
from .models import WebReadResult
from .utils import looks_like_js_page

logger = logging.getLogger(__name__)

_VALID_STRATEGIES = {"fast", "browser", "crawl4ai", "auto"}


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
    auto      – fast → crawl4ai → browser (degrades on failure/empty content)
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}. Choose from {_VALID_STRATEGIES}.")

    if strategy == "fast":
        return await read_fast(url)

    if strategy == "crawl4ai":
        return await read_crawl4ai(url)

    if strategy == "browser":
        return await read_browser(url)

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

    logger.debug(
        "auto strategy: crawl4ai insufficient, trying browser for %s", url
    )
    browser_result = await read_browser(url)
    result = _merge_attempts(result, browser_result)

    # Return the best available result (browser last, so it wins if successful)
    if browser_result.success:
        return result

    # All strategies failed — return merged result with original error preserved
    return result.model_copy(
        update={
            "success": False,
            "error": (
                result.error
                or c4ai_result.error
                or browser_result.error
                or "All strategies failed"
            ),
        }
    )
