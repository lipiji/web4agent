"""Fast async HTTP fetch using httpx + trafilatura."""

from __future__ import annotations

import logging
import time

import httpx

from .config import DEFAULT_TIMEOUT, USER_AGENT
from .models import FetchAttempt, WebReadResult
from .utils import (
    extract_text_bs4,
    extract_title_bs4,
    html_to_markdown,
    looks_like_js_page,
    utc_now_iso,
)

logger = logging.getLogger(__name__)

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
}


def _trafilatura_extract(html: str) -> tuple[str | None, str | None]:
    """Return (text, title) from trafilatura, or (None, None) on failure."""
    try:
        import trafilatura

        text = trafilatura.extract(html, include_links=False, include_images=False)
        meta = trafilatura.extract_metadata(html)
        title = meta.title if meta else None
        return text, title
    except Exception as exc:
        logger.debug("trafilatura failed: %s", exc)
        return None, None


async def read_fast(url: str, timeout: int = DEFAULT_TIMEOUT) -> WebReadResult:
    """
    Fetch a URL with httpx and extract main content via trafilatura.

    Falls back to BeautifulSoup if trafilatura yields nothing.
    """
    start = time.monotonic()
    fetched_at = utc_now_iso()

    async with httpx.AsyncClient(
        headers=_HEADERS,
        timeout=httpx.Timeout(timeout),
        follow_redirects=True,
        verify=False,  # avoid cert errors on some sites; users can patch
    ) as client:
        try:
            response = await client.get(url)
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status_code = response.status_code

            # Detect encoding
            content_type = response.headers.get("content-type", "")
            if "charset=" in content_type:
                encoding = content_type.split("charset=")[-1].split(";")[0].strip()
            else:
                encoding = getattr(response, "apparent_encoding", None) or "utf-8"

            try:
                html = response.content.decode(encoding, errors="replace")
            except (LookupError, UnicodeDecodeError):
                html = response.text

            final_url = str(response.url)

            # --- content extraction ---
            text, title = _trafilatura_extract(html)

            if not text:
                logger.debug("trafilatura empty for %s, falling back to BS4", url)
                text = extract_text_bs4(html)

            if not title:
                title = extract_title_bs4(html)

            markdown = html_to_markdown(html) if html else None

            success = status_code < 400 and bool(text)
            attempt = FetchAttempt(
                strategy="fast",
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
                strategy_used="fast",
                attempts=[attempt],
                fetched_at=fetched_at,
                elapsed_ms=elapsed_ms,
            )

        except httpx.TimeoutException as exc:
            elapsed_ms = int((time.monotonic() - start) * 1000)
            error = f"Timeout after {timeout}s: {exc}"
            logger.warning("read_fast timeout %s: %s", url, error)
            return WebReadResult(
                url=url,
                success=False,
                error=error,
                strategy_used="fast",
                attempts=[
                    FetchAttempt(strategy="fast", success=False, error=error, elapsed_ms=elapsed_ms)
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
                attempts=[
                    FetchAttempt(strategy="fast", success=False, error=error, elapsed_ms=elapsed_ms)
                ],
                fetched_at=fetched_at,
                elapsed_ms=elapsed_ms,
            )
