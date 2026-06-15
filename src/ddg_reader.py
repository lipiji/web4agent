"""DuckDuckGo HTML search fallback reader (no API key required)."""

from __future__ import annotations

import logging
import re
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx

from .config import DEFAULT_TIMEOUT, USER_AGENT
from .models import FetchAttempt, WebReadResult
from .utils import utc_now_iso

logger = logging.getLogger(__name__)

_DDG_HTML = "https://html.duckduckgo.com/html/"
_MIN_SNIPPET_CHARS = 30

_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://duckduckgo.com/",
}


def _norm_host(host: str) -> str:
    host = host.lower()
    return host.removeprefix("www.")


def _url_to_query(url: str) -> str:
    """Extract domain + path keywords from a URL to form a DDG search query."""
    parsed = urlparse(url)
    host = _norm_host(parsed.netloc)
    path = unquote(parsed.path.strip("/"))
    parts = re.split(r"[/\-_+.,;:%#!&?=]+", path)
    keywords = [w.strip() for w in parts if len(w.strip()) > 2 and not w.strip().isdigit()]
    if host and keywords:
        return f"{host} {' '.join(keywords[:5])}"
    if keywords:
        return " ".join(keywords[:5])
    return host or url


def _extract_href_host(a_tag) -> str:
    """Resolve actual destination hostname from a DDG result link (handles /l/?uddg= redirects)."""
    if not a_tag or not a_tag.get("href"):
        return ""
    href = a_tag["href"]
    try:
        parsed = urlparse(href)
        if parsed.path.startswith("/l/"):
            qs = parse_qs(parsed.query)
            real = qs.get("uddg", [None])[0]
            if real:
                return _norm_host(urlparse(unquote(real)).netloc)
        return _norm_host(parsed.netloc)
    except Exception:
        return ""


def _parse_ddg_results(html: str, target_url: str) -> tuple[str | None, str | None, str | None]:
    """
    Parse DDG HTML results page; return (title, snippet, matched_href).

    Prefers a result whose resolved href host matches target_url's host;
    falls back to the first result with a valid snippet.
    """
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        results = soup.select(".result")

        if not results:
            return None, None, None

        target_host = _norm_host(urlparse(target_url).netloc)

        best: tuple[str | None, str | None, str | None] = (None, None, None)

        for result in results:
            snippet_tag = result.select_one(".result__snippet")
            title_tag = result.select_one(".result__title")
            a_tag = result.select_one("a.result__a")

            if not snippet_tag:
                continue

            snippet = snippet_tag.get_text(" ", strip=True)
            if len(snippet.strip()) < _MIN_SNIPPET_CHARS:
                continue

            title = title_tag.get_text(strip=True) if title_tag else None
            href = a_tag["href"] if a_tag and a_tag.get("href") else ""
            href_host = _extract_href_host(a_tag)

            if target_host and (href_host == target_host or href_host.endswith("." + target_host)):
                return title, snippet, href

            if best[1] is None:
                best = (title, snippet, href)

        return best

    except Exception as exc:
        logger.debug("DDG result parsing failed: %s", exc)
        return None, None, None


async def read_ddg(url: str, timeout: int = DEFAULT_TIMEOUT) -> WebReadResult:
    """
    Search DuckDuckGo for a URL and return the best matching snippet.

    Uses the free DDG HTML endpoint — no API key required. Returns a short
    snippet rather than full page content, so this strategy is most useful
    as a last-resort fallback for agent context.
    """
    start = time.monotonic()
    fetched_at = utc_now_iso()

    try:
        async with httpx.AsyncClient(
            headers=_HEADERS,
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        ) as client:
            query = _url_to_query(url)
            logger.debug("ddg: searching for %r (from %s)", query, url)
            response = await client.post(
                _DDG_HTML,
                data={"q": query, "b": "", "kl": "us-en"},
            )
            elapsed_ms = int((time.monotonic() - start) * 1000)

        title, snippet, matched_href = _parse_ddg_results(response.text, url)

        if not snippet:
            return WebReadResult(
                url=url,
                success=False,
                error="No DDG results found",
                strategy_used="ddg",
                attempts=[
                    FetchAttempt(
                        strategy="ddg",
                        success=False,
                        status_code=response.status_code,
                        error="No results",
                        elapsed_ms=elapsed_ms,
                    )
                ],
                fetched_at=fetched_at,
                elapsed_ms=elapsed_ms,
            )

        logger.debug("ddg: got snippet (%d chars) for %s", len(snippet), url)

        return WebReadResult(
            url=url,
            title=title,
            text=snippet,
            success=True,
            strategy_used="ddg",
            attempts=[
                FetchAttempt(
                    strategy="ddg",
                    success=True,
                    status_code=response.status_code,
                    elapsed_ms=elapsed_ms,
                )
            ],
            fetched_at=fetched_at,
            elapsed_ms=elapsed_ms,
            metadata={
                "snippet_only": True,
                "matched_url": matched_href,
                "snippet_length": len(snippet),
            },
        )

    except Exception as exc:
        elapsed_ms = int((time.monotonic() - start) * 1000)
        error = f"{type(exc).__name__}: {exc}"
        logger.warning("read_ddg error %s: %s", url, exc)
        return WebReadResult(
            url=url,
            success=False,
            error=error,
            strategy_used="ddg",
            attempts=[
                FetchAttempt(strategy="ddg", success=False, error=error, elapsed_ms=elapsed_ms)
            ],
            fetched_at=fetched_at,
            elapsed_ms=elapsed_ms,
        )
