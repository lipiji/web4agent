# web4agent

> Free, open-source, async-first web scraping toolkit for LLM agents.  
> No commercial APIs. No rate-limit bills. Self-hostable.

---

## Features

| Function | Description |
|---|---|
| `read_url` | Auto-degradation: fast → crawl4ai → browser → wayback → ddg |
| `read_fast` | curl_cffi TLS impersonation + realistic headers; httpx fallback |
| `read_browser` | Stealth headless Chromium (patchright); canvas noise; Playwright fallback |
| `read_crawl4ai` | Crawl4AI LLM-friendly Markdown output |
| `read_wayback` | Wayback Machine archive fallback — no API key needed |
| `read_ddg` | DuckDuckGo snippet fallback — no API key needed |
| `read_many` | Concurrent batch fetch with deduplication |
| `discover_links` | Extract, normalize, and deduplicate hrefs |
| `agent_read_url` | Single-URL fetch returning a slim LLM-ready dict |
| `agent_read_urls` | Batch fetch with summary stats for LLM context |
| `agent_search` / `search_searx` / `search_ddg` | Free web search (DDG primary, SearXNG fallback) + full-page extraction — Tavily-equivalent, no API key |
| `run_doctor` | Diagnose optional deps, upstream connectivity, circuit-breaker state |
| FastAPI server | Optional HTTP API (`/read`, `/read_many`, `/discover_links`) |

---

## Installation

**Minimal** (httpx + trafilatura, covers most use cases):

```bash
pip install web4agent
```

**With optional extras:**

```bash
# TLS impersonation + realistic headers (bypass most bot-detection without a browser)
pip install "web4agent[stealth]"

# Headless browser with stealth context (JS-heavy pages, Cloudflare-protected sites)
pip install "web4agent[browser]"
patchright install chromium

# Crawl4AI strategy (LLM-optimised Markdown)
pip install "web4agent[crawl4ai]"

# FastAPI server
pip install "web4agent[server]"

# Everything
pip install "web4agent[all]"
patchright install chromium
```

**From source (development):**

```bash
git clone https://github.com/lipiji/web4agent
cd web4agent
pip install -e ".[dev]"
```

---

## Quick Start

### CLI

```bash
# Fetch a single page
web4agent read https://en.wikipedia.org/wiki/Web_scraping

# Batch fetch
web4agent many https://example.com https://python.org --concurrency 5

# Extract links
web4agent links https://docs.python.org/3/ --same-domain --max-links 30

# Search the web and extract full content for each result (free, no API key)
web4agent search "rust async runtime comparison" --max-results 5

# Check optional deps, upstream connectivity, and circuit-breaker state
web4agent doctor
```

### Python

```python
import asyncio
from web4agent import read_url, read_many, discover_links

async def main():
    # Single URL — auto strategy (fast → crawl4ai → browser)
    result = await read_url("https://en.wikipedia.org/wiki/Web_scraping")
    print(result.title)
    print(result.text[:500])

    # Batch
    results = await read_many(
        ["https://example.com", "https://python.org"],
        concurrency=5,
        strategy="fast",
    )
    for r in results:
        print(r.url, "OK" if r.success else r.error)

    # Links
    links = await discover_links("https://docs.python.org/3/", same_domain=True)
    print(links[:5])

asyncio.run(main())
```

### Proxy rotation

```python
import asyncio
from web4agent import agent_read_urls

async def main():
    proxies = [
        "http://user:pass@proxy1:8080",
        "socks5://proxy2:1080",
    ]
    summary = await agent_read_urls(
        ["https://example.com", "https://python.org"],
        proxies=proxies,
        proxy_mode="round_robin",  # or "random"
    )
    print(summary)

asyncio.run(main())
```

Or manage rotation manually:

```python
from web4agent import ProxyRotator, read_url

rotator = ProxyRotator(["http://p1:8080", "http://p2:8080"])
proxy = rotator.next()
result = await read_url("https://example.com", proxy=proxy)
rotator.mark_success(proxy) if result.success else rotator.mark_failed(proxy)
print(rotator.stats())
```

---

### Agent interface (slim dicts for LLM context)

```python
import asyncio
from web4agent import agent_read_url, agent_read_urls

async def main():
    # Single — returns {"url", "title", "content", "success", "strategy_used", "error"}
    r = await agent_read_url("https://example.com")
    print(r["title"])
    print(r["content"][:300])

    # Batch — returns {"results", "total", "succeeded", "failed"}
    summary = await agent_read_urls(
        ["https://example.com", "https://python.org"],
        concurrency=5,
    )
    print(f"Fetched {summary['succeeded']}/{summary['total']}")
    for item in summary["results"]:
        print(item["url"], item["success"])

asyncio.run(main())
```

### Search (free Tavily equivalent)

```python
import asyncio
from web4agent import agent_search

async def main():
    # Searches DuckDuckGo first, falls back to SearXNG, then extracts
    # full page content for every hit.
    result = await agent_search("rust async runtime comparison", max_results=5)
    print(f"{result['extracted']}/{result['hits']} pages extracted via {result['search_backend']}")
    for r in result["results"]:
        print(r["url"], r["title"])

asyncio.run(main())
```

> Full working examples: [`examples/example.py`](examples/example.py)

---

## Strategies

| Strategy | How it works | Best for |
|---|---|---|
| `fast` | httpx + trafilatura (+ BS4 fallback) | Static pages, high concurrency |
| `crawl4ai` | Crawl4AI `AsyncWebCrawler` | Docs, structured Markdown output |
| `browser` | Playwright headless Chromium | JS-heavy SPAs, lazy-loaded content |
| `wayback` | archive.org snapshot | Sites blocking direct access |
| `ddg` | DuckDuckGo cached snippet | Last-resort fallback, no API key |
| `auto` | Degrades: fast → crawl4ai → browser → wayback → ddg (extended fallbacks toggle via `WRT_EXTENDED_FALLBACKS`) | Unknown pages |

**Auto-degradation** triggers when:
- HTTP status ≥ 400
- Extracted text is shorter than `MIN_TEXT_LENGTH` (default 300 chars)
- Page looks like a JS-only shell (empty `#root` / `#app` div)

---

## Result shape

All read functions return a `WebReadResult`:

```python
class WebReadResult(BaseModel):
    url: str
    final_url: str | None       # after redirects
    title: str | None
    text: str | None            # plain text
    markdown: str | None        # Markdown version
    html: str | None            # raw HTML
    status_code: int | None
    success: bool
    strategy_used: str | None
    attempts: list[FetchAttempt]
    error: str | None
    fetched_at: str             # ISO-8601 UTC
    elapsed_ms: int | None
    metadata: dict              # e.g. screenshot_b64 for browser reads
```

---

## Configuration

Set via environment variables (or a `.env` file):

| Variable | Default | Description |
|---|---|---|
| `WRT_TIMEOUT` | `20` | HTTP timeout in seconds |
| `WRT_FAST_CONCURRENCY` | `50` | Max concurrent fast requests |
| `WRT_CRAWL4AI_CONCURRENCY` | `10` | Max concurrent crawl4ai requests |
| `WRT_BROWSER_CONCURRENCY` | `3` | Max simultaneous Playwright pages |
| `WRT_MIN_TEXT_LENGTH` | `300` | Min chars to consider a fetch successful |
| `WRT_AGENT_MAX_CONTENT_CHARS` | `8000` | Content truncation limit for agent output |
| `WRT_USER_AGENT` | Chrome 124 | User-Agent header string |
| `WRT_HEALTH_FAILURE_THRESHOLD` | `3` | Consecutive failures before a fallback tier is circuit-broken |
| `WRT_HEALTH_COOLDOWN_SECONDS` | `60` | Cooldown before a circuit-broken tier is retried |
| `WRT_EXTENDED_FALLBACKS` | `true` | Enable the `wayback` / `ddg` tiers in the `auto` chain |

---

## FastAPI Server

```bash
pip install "web4agent[server]"
uvicorn web4agent.server:app --host 0.0.0.0 --port 8000
```

| Method | Path | Body |
|---|---|---|
| `GET` | `/health` | — |
| `POST` | `/read` | `{"url": "...", "strategy": "auto"}` |
| `POST` | `/read_many` | `{"urls": [...], "concurrency": 10, "strategy": "auto"}` |
| `POST` | `/discover_links` | `{"url": "...", "same_domain": true, "max_links": 100}` |

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

---

## Compliance

- **`robots.txt`** — not enforced automatically; check it yourself before scraping.
- **Rate limiting** — use the `concurrency` parameter; add delays for the same domain.
- **Terms of Service** — always review a site's ToS before scraping.
- Intended for lawful, authorized use only.

---

## License

MIT
