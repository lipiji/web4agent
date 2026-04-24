"""Link discovery: extract and filter hrefs from a page."""

from __future__ import annotations

import logging
import re
from urllib.parse import urljoin, urlparse

import httpx

from .config import DEFAULT_TIMEOUT, USER_AGENT

logger = logging.getLogger(__name__)

_SKIP_SCHEMES = {"mailto:", "javascript:", "tel:", "data:", "#"}


def _is_valid_href(href: str) -> bool:
    if not href or not href.strip():
        return False
    stripped = href.strip()
    if stripped.startswith("#"):
        return False
    for prefix in _SKIP_SCHEMES:
        if stripped.lower().startswith(prefix):
            return False
    return True


def _normalize(href: str, base_url: str) -> str | None:
    """Resolve relative href against base_url; return None if unparseable."""
    try:
        full = urljoin(base_url, href.strip())
        parsed = urlparse(full)
        # Strip fragment
        return parsed._replace(fragment="").geturl()
    except Exception:
        return None


async def discover_links(
    url: str,
    same_domain: bool = True,
    max_links: int = 100,
) -> list[str]:
    """
    Fetch *url* and return href links found on the page.

    Parameters
    ----------
    url:         Page to scan.
    same_domain: If True, only return links whose hostname matches *url*.
    max_links:   Maximum number of links returned.
    """
    headers = {
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    }

    try:
        async with httpx.AsyncClient(
            headers=headers,
            timeout=httpx.Timeout(DEFAULT_TIMEOUT),
            follow_redirects=True,
            verify=False,
        ) as client:
            response = await client.get(url)
            html = response.text
            final_url = str(response.url)
    except Exception as exc:
        logger.warning("discover_links fetch failed for %s: %s", url, exc)
        return []

    try:
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(html, "html.parser")
        anchors = soup.find_all("a", href=True)
    except Exception as exc:
        logger.warning("discover_links parse failed: %s", exc)
        return []

    base_host = urlparse(final_url).netloc

    seen: set[str] = set()
    results: list[str] = []

    for a in anchors:
        raw = a["href"]
        if not _is_valid_href(raw):
            continue
        normalized = _normalize(raw, final_url)
        if normalized is None:
            continue
        if normalized in seen:
            continue
        if same_domain:
            link_host = urlparse(normalized).netloc
            if link_host != base_host:
                continue
        seen.add(normalized)
        results.append(normalized)
        if len(results) >= max_links:
            break

    logger.debug("discover_links: found %d links on %s", len(results), url)
    return results
