"""Wayback Machine (archive.org) fallback reader."""

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
    utc_now_iso,
)

logger = logging.getLogger(__name__)

_CDX_API = "http://web.archive.org/cdx/search/cdx"
_WAYBACK_BASE = "https://web.archive.org/web"

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


async def _find_snapshot(url: str, client: httpx.AsyncClient) -> str | None:
    """Query CDX API for the most recent 200-OK snapshot; return archived URL or None."""
    params = {
        "url": url,
        "output": "json",
        "limit": "1",
        "fl": "timestamp,original",
        "filter": "statuscode:200",
        "fastLatest": "true",
        "collapse": "urlkey",
    }
    try:
        resp = await client.get(_CDX_API, params=params)
        if resp.status_code >= 400:
            logger.debug("wayback CDX returned HTTP %s for %s", resp.status_code, url)
            return None
        rows = resp.json()
        if not isinstance(rows, list) or len(rows) < 2:
            logger.debug("wayback CDX: no snapshot found for %s", url)
            return None
        row = rows[1]
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            logger.debug("wayback CDX unexpected row shape %r for %s", row, url)
            return None
        timestamp, original = row[0], row[1]
        if not timestamp or not original:
            return None
        return f"{_WAYBACK_BASE}/{timestamp}/{original}"
    except Exception as exc:
        logger.debug("wayback CDX lookup failed for %s: %s", url, exc)
        return None


async def read_wayback(url: str, timeout: int = DEFAULT_TIMEOUT) -> WebReadResult:
    """
    Fetch a URL from the Wayback Machine (archive.org).

    Queries the CDX API for the most recent 200-OK snapshot, then fetches
    and extracts content from the archived page.
    """
    start = time.monotonic()
    fetched_at = utc_now_iso()

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        ) as client:
            archived_url = await _find_snapshot(url, client)
            if not archived_url:
                elapsed_ms = int((time.monotonic() - start) * 1000)
                return WebReadResult(
                    url=url,
                    success=False,
                    error="No Wayback Machine snapshot found",
                    strategy_used="wayback",
                    attempts=[
                        FetchAttempt(
                            strategy="wayback",
                            success=False,
                            error="No snapshot found",
                            elapsed_ms=elapsed_ms,
                        )
                    ],
                    fetched_at=fetched_at,
                    elapsed_ms=elapsed_ms,
                )

            logger.debug("wayback: fetching archived snapshot %s", archived_url)
            remaining = max(1, timeout - int(time.monotonic() - start))
            response = await client.get(archived_url, timeout=httpx.Timeout(remaining))
            elapsed_ms = int((time.monotonic() - start) * 1000)
            status_code = response.status_code

            ctype = response.headers.get("content-type", "")
            if "html" not in ctype.lower() and "xml" not in ctype.lower():
                return WebReadResult(
                    url=url,
                    final_url=archived_url,
                    success=False,
                    error=f"Non-HTML capture: {ctype.split(';')[0].strip()}",
                    strategy_used="wayback",
                    attempts=[
                        FetchAttempt(
                            strategy="wayback",
                            success=False,
                            status_code=status_code,
                            error="Non-HTML content-type",
                            elapsed_ms=elapsed_ms,
                        )
                    ],
                    fetched_at=fetched_at,
                    elapsed_ms=elapsed_ms,
                )

            html = response.text

            try:
                import trafilatura

                text = trafilatura.extract(html, include_links=False, include_images=False)
                meta = trafilatura.extract_metadata(html)
                title = meta.title if meta else None
            except Exception:
                text = None
                title = None

            if not text:
                text = extract_text_bs4(html)
            if not title:
                title = extract_title_bs4(html)

            markdown = html_to_markdown(html) if html else None
            success = status_code < 400 and bool(text)

            return WebReadResult(
                url=url,
                final_url=archived_url,
                title=title,
                text=text,
                markdown=markdown,
                html=html,
                status_code=status_code,
                success=success,
                strategy_used="wayback",
                attempts=[
                    FetchAttempt(
                        strategy="wayback",
                        success=success,
                        status_code=status_code,
                        elapsed_ms=elapsed_ms,
                    )
                ],
                fetched_at=fetched_at,
                elapsed_ms=elapsed_ms,
                metadata={"archived_url": archived_url},
            )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        error = type(exc).__name__
        logger.warning("read_wayback error %s: %s", url, exc)
        return WebReadResult(
            url=url,
            success=False,
            error=error,
            strategy_used="wayback",
            attempts=[
                FetchAttempt(strategy="wayback", success=False, error=error, elapsed_ms=elapsed_ms)
            ],
            fetched_at=fetched_at,
            elapsed_ms=elapsed_ms,
        )
