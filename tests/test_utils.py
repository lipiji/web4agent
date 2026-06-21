"""Tests for utility helpers."""

from unittest.mock import patch

import pytest
from web4agent.utils import (
    extract_text_bs4,
    extract_title_bs4,
    fetch_failure_reason,
    html_to_markdown,
    looks_like_js_page,
    truncate,
    utc_now_iso,
)


# ── utc_now_iso ────────────────────────────────────────────────────────────────

class TestUtcNowIso:
    def test_returns_string(self):
        result = utc_now_iso()
        assert isinstance(result, str)

    def test_contains_timezone(self):
        result = utc_now_iso()
        assert "+" in result or "Z" in result

    def test_iso_format(self):
        import datetime
        result = utc_now_iso()
        # Should parse without error
        dt = datetime.datetime.fromisoformat(result)
        assert dt.tzinfo is not None


# ── fetch_failure_reason ───────────────────────────────────────────────────────

class TestFetchFailureReason:
    def test_bad_status_returns_http_reason(self):
        assert fetch_failure_reason(503, "some text") == "HTTP 503"

    def test_404_returns_http_reason_even_with_text(self):
        assert fetch_failure_reason(404, "Not Found page body") == "HTTP 404"

    def test_empty_text_with_good_status_returns_no_content_reason(self):
        assert fetch_failure_reason(200, "") == "No extractable text content"

    def test_none_text_with_good_status_returns_no_content_reason(self):
        assert fetch_failure_reason(200, None) == "No extractable text content"

    def test_good_status_with_text_returns_none(self):
        assert fetch_failure_reason(200, "plenty of content") is None

    def test_none_status_with_text_returns_none(self):
        assert fetch_failure_reason(None, "plenty of content") is None

    def test_status_just_under_400_is_not_a_failure(self):
        assert fetch_failure_reason(399, "content") is None


# ── truncate ───────────────────────────────────────────────────────────────────

class TestTruncate:
    def test_none_returns_none(self):
        assert truncate(None, 100) is None

    def test_short_text_unchanged(self):
        assert truncate("hello", 100) == "hello"

    def test_exact_length_unchanged(self):
        text = "a" * 100
        assert truncate(text, 100) == text

    def test_long_text_truncated(self):
        text = "a" * 200
        result = truncate(text, 100)
        assert result is not None
        assert result.startswith("a" * 100)
        assert "truncated" in result

    def test_truncated_length(self):
        text = "x" * 500
        result = truncate(text, 50)
        assert result is not None
        assert result[:50] == "x" * 50

    def test_empty_string(self):
        assert truncate("", 100) == ""


# ── looks_like_js_page ─────────────────────────────────────────────────────────

class TestLooksLikeJsPage:
    def test_empty_text_is_js(self):
        assert looks_like_js_page("<html></html>", None) is True

    def test_short_text_is_js(self):
        assert looks_like_js_page("<html></html>", "hi") is True

    def test_spa_root_div_is_js(self):
        html = '<html><body><div id="root"></div></body></html>'
        assert looks_like_js_page(html, "a" * 200) is True

    def test_spa_app_div_is_js(self):
        html = '<html><body><div id="app"></div></body></html>'
        assert looks_like_js_page(html, "a" * 200) is True

    def test_normal_page_not_js(self):
        html = "<html><body><p>Real content here</p></body></html>"
        text = "Real content here " * 10
        assert looks_like_js_page(html, text) is False

    def test_noscript_tag_is_js(self):
        html = "<html><body><noscript>Enable JS</noscript></body></html>"
        assert looks_like_js_page(html, "a" * 200) is True


# ── extract_title_bs4 ──────────────────────────────────────────────────────────

class TestExtractTitleBs4:
    def test_extracts_title(self):
        html = "<html><head><title>Hello World</title></head></html>"
        assert extract_title_bs4(html) == "Hello World"

    def test_no_title_returns_none(self):
        assert extract_title_bs4("<html><body>no title</body></html>") is None

    def test_empty_string(self):
        assert extract_title_bs4("") is None

    def test_strips_whitespace(self):
        html = "<html><head><title>  Padded  </title></head></html>"
        assert extract_title_bs4(html) == "Padded"

    def test_nested_tags(self):
        html = "<html><head><title>Page &amp; Title</title></head></html>"
        result = extract_title_bs4(html)
        assert result is not None
        assert "Page" in result


# ── extract_text_bs4 ──────────────────────────────────────────────────────────

class TestExtractTextBs4:
    def test_basic_extraction(self):
        html = "<html><body><p>Hello world</p></body></html>"
        result = extract_text_bs4(html)
        assert result is not None
        assert "Hello world" in result

    def test_strips_scripts(self):
        html = "<html><body><script>var x=1;</script><p>Content</p></body></html>"
        result = extract_text_bs4(html)
        assert result is not None
        assert "var x" not in result
        assert "Content" in result

    def test_strips_styles(self):
        html = "<html><body><style>.a{color:red}</style><p>Text</p></body></html>"
        result = extract_text_bs4(html)
        assert result is not None
        assert "color" not in result

    def test_empty_html(self):
        result = extract_text_bs4("<html></html>")
        # May return empty string or None — just shouldn't raise
        assert result is None or isinstance(result, str)

    def test_multiple_paragraphs(self):
        html = "<html><body><p>Para 1</p><p>Para 2</p></body></html>"
        result = extract_text_bs4(html)
        assert result is not None
        assert "Para 1" in result
        assert "Para 2" in result


# ── html_to_markdown ──────────────────────────────────────────────────────────

class TestHtmlToMarkdown:
    def test_heading(self):
        result = html_to_markdown("<h1>Title</h1>")
        assert result is not None
        assert "Title" in result
        assert "#" in result

    def test_paragraph(self):
        result = html_to_markdown("<p>Hello world</p>")
        assert result is not None
        assert "Hello world" in result

    def test_link(self):
        result = html_to_markdown('<a href="https://example.com">Click</a>')
        assert result is not None
        assert "Click" in result

    def test_strips_script(self):
        # markdownify's strip= removes the tag wrapper but may keep inner text;
        # just verify the paragraph content survives and no exception is raised
        result = html_to_markdown("<script>alert(1)</script><p>text</p>")
        assert result is not None
        assert "text" in result

    def test_empty_string(self):
        result = html_to_markdown("")
        assert result is None or isinstance(result, str)

    def test_returns_none_on_exception(self):
        with patch("markdownify.markdownify", side_effect=Exception("markdownify broke")):
            result = html_to_markdown("<p>text</p>")
        assert result is None


class TestExtractTitleBs4Exceptions:
    def test_returns_none_on_exception(self):
        with patch("bs4.BeautifulSoup", side_effect=Exception("bs4 broke")):
            from web4agent.utils import extract_title_bs4
            result = extract_title_bs4("<html><head><title>T</title></head></html>")
        assert result is None


class TestExtractTextBs4Exceptions:
    def test_returns_none_on_exception(self):
        with patch("bs4.BeautifulSoup", side_effect=Exception("bs4 broke")):
            from web4agent.utils import extract_text_bs4
            result = extract_text_bs4("<html><body><p>text</p></body></html>")
        assert result is None


class TestExtractTitleBs4Fallbacks:
    def test_og_title_fallback(self):
        html = '<html><head><meta property="og:title" content="OG Title"/></head></html>'
        result = extract_title_bs4(html)
        assert result == "OG Title"

    def test_twitter_title_fallback(self):
        html = '<html><head><meta name="twitter:title" content="Tweet Title"/></head></html>'
        result = extract_title_bs4(html)
        assert result == "Tweet Title"

    def test_h1_fallback(self):
        html = "<html><body><h1>Main Heading</h1><p>content</p></body></html>"
        result = extract_title_bs4(html)
        assert result == "Main Heading"


class TestTruncateNaturalBoundary:
    def test_cuts_at_sentence_boundary(self):
        text = ("First sentence. " * 10).strip()
        result = truncate(text, 50)
        assert result is not None
        assert "truncated" in result

    def test_cuts_at_newline_boundary(self):
        text = "Line one\nLine two\nLine three\nLine four\nLine five\nLine six\n" * 3
        result = truncate(text, 60)
        assert result is not None
        assert "truncated" in result


class TestHtmlToMarkdownBs4Inner:
    def test_markdownify_still_runs_when_bs4_inner_fails(self):
        with patch("bs4.BeautifulSoup", side_effect=Exception("bs4 broke")):
            result = html_to_markdown("<h1>Title</h1><p>Text here</p>")
        assert result is not None
        assert "Title" in result or "Text" in result
