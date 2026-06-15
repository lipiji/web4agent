"""Shared utility helpers."""

from __future__ import annotations

import datetime
import logging
import re

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    """Return current UTC time as ISO-8601 string."""
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def looks_like_js_page(html: str, text: str | None) -> bool:
    """Heuristic: returns True if page content looks JS-rendered / mostly empty."""
    if not text or len(text.strip()) < 100:
        return True
    # Common SPA shell patterns
    js_patterns = [
        r"<div[^>]+id=['\"]root['\"]>\s*</div>",
        r"<div[^>]+id=['\"]app['\"]>\s*</div>",
        r"<noscript>.*?</noscript>",
    ]
    for pat in js_patterns:
        if re.search(pat, html, re.IGNORECASE | re.DOTALL):
            return True
    return False


def truncate(text: str | None, max_chars: int) -> str | None:
    """Truncate text to max_chars, appending ellipsis if truncated."""
    if text is None:
        return None
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n\n… [truncated]"


def extract_title_bs4(html: str) -> str | None:
    """Extract page title — tries <title>, then og:title, then first h1."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        tag = soup.find("title")
        if tag:
            return tag.get_text(strip=True)
        og = soup.find("meta", attrs={"property": "og:title"})
        if og and og.get("content", "").strip():
            return og["content"].strip()
        twitter = soup.find("meta", attrs={"name": "twitter:title"})
        if twitter and twitter.get("content", "").strip():
            return twitter["content"].strip()
        h1 = soup.find("h1")
        if h1:
            return h1.get_text(strip=True)
        return None
    except Exception:
        return None


def extract_text_bs4(html: str) -> str | None:
    """Fallback text extraction via BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
            tag.decompose()
        return soup.get_text(separator="\n", strip=True)
    except Exception as exc:
        logger.debug("BS4 text extraction failed: %s", exc)
        return None


def html_to_markdown(html: str) -> str | None:
    """Convert HTML to Markdown using markdownify, with boilerplate pre-stripped."""
    try:
        import markdownify

        source = html
        try:
            from bs4 import BeautifulSoup

            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "nav", "footer", "header", "aside", "form"]):
                tag.decompose()
            source = str(soup)
        except Exception:
            pass
        return markdownify.markdownify(source, heading_style="ATX", strip=["script", "style"])
    except Exception as exc:
        logger.debug("markdownify failed: %s", exc)
        return None
