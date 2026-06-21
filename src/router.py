"""Strategy router: auto-degradation across fast -> crawl4ai -> browser -> wayback -> ddg."""

from __future__ import annotations

import logging

from .browser import read_browser
from .config import MIN_TEXT_LENGTH, USE_EXTENDED_FALLBACKS
from .crawl4ai_reader import read_crawl4ai
from .ddg_reader import read_ddg
from .fast import read_fast
from .health import default_tracker as health_tracker
from .models import FetchAttempt, WebReadResult
from .utils import looks_like_js_page, utc_now_iso
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


def _skipped_result(url: str, strategy: str) -> WebReadResult:
    """Stand-in result for a tier the circuit breaker is currently skipping."""
    error = f"{strategy} skipped: circuit breaker open (repeated recent failures)"
    return WebReadResult(
        url=url,
        success=False,
        error=error,
        strategy_used=strategy,
        attempts=[FetchAttempt(strategy=strategy, success=False, error=error)],
        fetched_at=utc_now_iso(),
    )


async def _try_strategy(name: str, call, url: str) -> WebReadResult:
    """Run a fallback tier through the circuit breaker, recording the outcome."""
    if not health_tracker.is_available(name):
        logger.debug("auto strategy: %s skipped (circuit breaker open)", name)
        return _skipped_result(url, name)
    result = await call()
    if result.success:
        health_tracker.mark_success(name)
    else:
        health_tracker.mark_failure(name)
    return result


def _merge_attempts(base: WebReadResult, extra: WebReadResult) -> WebReadResult:
    """Combine attempts from two results, prefer extra if it succeeded."""
    combined_attempts = base.attempts + extra.attempts
    if extra.success:
        return extra.model_copy(update={"attempts": combined_attempts})
    # Keep the best non-error result; propagate error from extra if base has none.
    error = base.error or extra.error
    return base.model_copy(update={"attempts": combined_attempts, "error": error})


async def read_url(
    url: str,
    strategy: str = "auto",
    proxy: str | None = None,
) -> WebReadResult:
    """
    Fetch a URL with the given strategy.

    strategy values
    ---------------
    fast      – httpx / curl_cffi only
    crawl4ai  – Crawl4AI only
    browser   – headless browser only
    wayback   – archive.org Wayback Machine only
    ddg       – DuckDuckGo search snippet only
    auto      – fast → crawl4ai → browser → wayback → ddg
                (degrades on failure or sparse content)

    Parameters
    ----------
    url:      Target URL.
    strategy: Fetch strategy (see above).
    proxy:    Optional proxy URL, e.g. ``"http://user:pass@host:port"``.
              Applied to fast and browser strategies.
    """
    if strategy not in _VALID_STRATEGIES:
        raise ValueError(f"Unknown strategy {strategy!r}. Choose from {_VALID_STRATEGIES}.")

    if strategy == "fast":
        return await read_fast(url, proxy=proxy)

    if strategy == "crawl4ai":
        return await read_crawl4ai(url)

    if strategy == "browser":
        return await read_browser(url, proxy=proxy)

    if strategy == "wayback":
        return await read_wayback(url)

    if strategy == "ddg":
        return await read_ddg(url)

    # ── auto ──────────────────────────────────────────────────────────────────
    logger.debug("auto strategy: trying fast for %s", url)
    result = await _try_strategy("fast", lambda: read_fast(url, proxy=proxy), url)

    if not _should_degrade(result):
        return result

    logger.debug(
        "auto strategy: fast insufficient (%s chars, success=%s), trying crawl4ai for %s",
        len(result.text or ""),
        result.success,
        url,
    )
    c4ai_result = await _try_strategy("crawl4ai", lambda: read_crawl4ai(url), url)
    result = _merge_attempts(result, c4ai_result)

    if not _should_degrade(c4ai_result):
        return result

    logger.debug("auto strategy: crawl4ai insufficient, trying browser for %s", url)
    browser_result = await _try_strategy("browser", lambda: read_browser(url, proxy=proxy), url)
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
    wayback_result = await _try_strategy("wayback", lambda: read_wayback(url), url)
    result = _merge_attempts(result, wayback_result)

    if not _should_degrade(wayback_result):
        return result

    logger.debug("auto strategy: wayback unavailable, trying ddg for %s", url)
    ddg_result = await _try_strategy("ddg", lambda: read_ddg(url), url)
    result = _merge_attempts(result, ddg_result)

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
