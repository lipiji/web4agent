"""Async HTTP fetch with TLS impersonation and realistic browser headers."""

from __future__ import annotations

import logging
import time

from .config import DEFAULT_TIMEOUT
from .models import FetchAttempt, WebReadResult
from .utils import (
    extract_text_bs4,
    extract_title_bs4,
    html_to_markdown,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

_IMPERSONATE = "chrome"


def _browser_headers() -> dict[str, str]:
    """Return realistic browser headers, using browserforge when available."""
    try:
        from browserforge.headers import HeaderGenerator

        return dict(HeaderGenerator(browser="chrome", os="windows", locale="en-US,en").generate())
    except ImportError:
        return {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0.0.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
        }


def _trafilatura_extract(html: str) -> tuple[str | None, str | None, str | None]:
    """Return (text, title, markdown). markdown uses trafilatura's own cleaner output."""
    try:
        import trafilatura

        text = trafilatura.extract(html, include_links=False, include_images=False)
        markdown = trafilatura.extract(html, output_format="markdown", include_links=True, include_images=False)
        meta = trafilatura.extract_metadata(html)
        return text, (meta.title if meta else None), markdown
    except Exception as exc:
        logger.debug("trafilatura failed: %s", exc)
        return None, None, None


async def _curl_get(
    url: str, timeout: int, proxy: str | None
) -> tuple[int, str, str]:
    """Fetch via curl_cffi with TLS impersonation. Raises ImportError if not installed."""
    from curl_cffi.requests import AsyncSession

    proxy_map = {"http": proxy, "https": proxy} if proxy else None
    async with AsyncSession(impersonate=_IMPERSONATE, verify=False) as session:
        resp = await session.get(
            url,
            headers=_browser_headers(),
            timeout=timeout,
            allow_redirects=True,
            proxies=proxy_map,
        )
        return resp.status_code, resp.text, str(resp.url)


async def _httpx_get(
    url: str, timeout: int, proxy: str | None
) -> tuple[int, str, str]:
    """Fetch via httpx as fallback when curl_cffi is not installed."""
    import httpx

    async with httpx.AsyncClient(
        headers=_browser_headers(),
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        verify=False,
        proxy=proxy,
    ) as client:
        resp = await client.get(url)
        ct = resp.headers.get("content-type", "")
        encoding = (
            ct.split("charset=")[-1].split(";")[0].strip()
            if "charset=" in ct
            else getattr(resp, "apparent_encoding", None) or "utf-8"
        )
        try:
            html = resp.content.decode(encoding, errors="replace")
        except (LookupError, UnicodeDecodeError):
            html = resp.text
        return resp.status_code, html, str(resp.url)


async def read_fast(
    url: str,
    timeout: int = DEFAULT_TIMEOUT,
    proxy: str | None = None,
) -> WebReadResult:
    """
    Fetch a URL and extract main content as text and Markdown.

    Prefers curl_cffi (TLS impersonation) when installed, falls back to httpx.

    Parameters
    ----------
    url:     Target URL.
    timeout: Request timeout in seconds.
    proxy:   Optional proxy URL, e.g. ``"http://user:pass@host:port"``.
    """
    start = time.monotonic()
    fetched_at = utc_now_iso()

    try:
        try:
            status_code, html, final_url = await _curl_get(url, timeout, proxy)
        except ImportError:
            status_code, html, final_url = await _httpx_get(url, timeout, proxy)

        elapsed_ms = int((time.monotonic() - start) * 1000)

        text, title, traf_markdown = _trafilatura_extract(html)
        if not text:
            logger.debug("trafilatura empty for %s, falling back to BS4", url)
            text = extract_text_bs4(html)
        if not title:
            title = extract_title_bs4(html)

        markdown = traf_markdown or (html_to_markdown(html) if html else None)
        success = status_code < 400 and bool(text)

        return WebReadResult(
            url=url,
            final_url=final_url,
            title=title,
            text=text,
            markdown=markdown,
            html=html,
            status_code=status_code,
            success=success,
            strategy_used="fast",
            attempts=[
                FetchAttempt(
                    strategy="fast",
                    success=success,
                    status_code=status_code,
                    elapsed_ms=elapsed_ms,
                )
            ],
            fetched_at=fetched_at,
            elapsed_ms=elapsed_ms,
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("read_fast error %s: %s", url, error)
        return WebReadResult(
            url=url,
            success=False,
            error=error,
            strategy_used="fast",
            attempts=[FetchAttempt(strategy="fast", success=False, error=error, elapsed_ms=elapsed_ms)],
            fetched_at=fetched_at,
            elapsed_ms=elapsed_ms,
        )
