# webweb

Free, open-source, async-first web scraping toolkit for LLM agents.  
No commercial APIs. No rate-limit bills. Self-hostable.

## Features

- **`read_fast`** — httpx + trafilatura + BeautifulSoup fallback  
- **`read_browser`** — Playwright JS rendering, reused browser instance  
- **`read_crawl4ai`** — Crawl4AI LLM-friendly Markdown  
- **`read_url`** — auto-degradation: fast → crawl4ai → browser  
- **`read_many`** — concurrent batch fetch with `asyncio.Semaphore`  
- **`discover_links`** — extract, normalize, deduplicate hrefs  
- **`agent_read_url` / `agent_read_urls`** — slim dicts for LLM context  
- Optional **FastAPI server** (`/read`, `/read_many`, `/discover_links`)

---

## Install (just one command)

```bash
pip install -e .
```

That's enough for most users.

If you need advanced features later:

- JS-rendered pages (Playwright):
  - `pip install -e ".[browser]"`
  - `playwright install chromium`
- Crawl4AI strategy:
  - `pip install -e ".[crawl4ai]"`
- FastAPI server:
  - `pip install -e ".[server]"`
- Everything:
  - `pip install -e ".[all]"`
  - `playwright install chromium`

---

## Quick Start (copy and run)

```bash
pip install -e .
webweb read https://en.wikipedia.org/wiki/Web_scraping
```

More commands:

```bash
webweb many https://example.com https://python.org --concurrency 5
webweb links https://docs.python.org/3/ --same-domain --max-links 30
```

> Prefer Python usage? See `examples/example.py`.

### Agent interface (slim output for LLM context)

```python
from webweb import agent_read_url, agent_read_urls

async def main():
    # Single
    r = await agent_read_url("https://example.com")
    print(r["title"], r["content"][:300])

    # Batch
    summary = await agent_read_urls(
        ["https://example.com", "https://python.org"],
        concurrency=5,
    )
    print(f"Fetched {summary['succeeded']}/{summary['total']}")
    for item in summary["results"]:
        print(item["url"], item["success"])

asyncio.run(main())
```

### Discover links

```python
from webweb import discover_links

async def main():
    links = await discover_links("https://docs.python.org/3/", same_domain=True, max_links=50)
    for link in links:
        print(link)

asyncio.run(main())
```

---

## Strategies

| Strategy   | Description                              | Best for                         |
|------------|------------------------------------------|----------------------------------|
| `fast`     | httpx + trafilatura                      | Static pages, high concurrency   |
| `crawl4ai` | Crawl4AI AsyncWebCrawler                 | Docs, structured content         |
| `browser`  | Playwright headless Chromium             | JS-heavy SPAs, lazy loading      |
| `auto`     | Degrades fast → crawl4ai → browser      | Unknown pages                    |

Auto-degradation triggers when:
- HTTP status ≥ 400
- Extracted text shorter than `MIN_TEXT_LENGTH` (default 300 chars)
- Page looks like a JS-only shell (empty `#root` / `#app` divs)

---

## Configuration

Copy `.env.example` to `.env` and adjust:

| Variable                   | Default | Description                          |
|----------------------------|---------|--------------------------------------|
| `WRT_TIMEOUT`              | `20`    | HTTP timeout (seconds)               |
| `WRT_FAST_CONCURRENCY`     | `50`    | Max concurrent fast requests         |
| `WRT_CRAWL4AI_CONCURRENCY` | `10`    | Max concurrent crawl4ai requests     |
| `WRT_BROWSER_CONCURRENCY`  | `3`     | Max concurrent Playwright pages      |
| `WRT_MIN_TEXT_LENGTH`      | `300`   | Minimum chars to accept as success   |
| `WRT_AGENT_MAX_CONTENT_CHARS` | `8000` | Truncation limit for agent output |

---

## FastAPI Server (optional)

```bash
uvicorn webweb.server:app --host 0.0.0.0 --port 8000
```

Endpoints:

| Method | Path              | Description              |
|--------|-------------------|--------------------------|
| GET    | `/health`         | Health check             |
| POST   | `/read`           | Fetch a single URL       |
| POST   | `/read_many`      | Batch fetch              |
| POST   | `/discover_links` | Extract links from a URL |

Request body for `/read`:

```json
{ "url": "https://example.com", "strategy": "auto" }
```

---

## Running Examples

```bash
python examples/example.py
```

---

## Running Tests

```bash
pip install -e ".[dev]"
pytest
```

---

## Compliance

- **Respect `robots.txt`** — this toolkit does not enforce `robots.txt` automatically.  
  Check it yourself or use a library like `robotparser` before scraping.  
- **Rate limiting** — use the `concurrency` parameter to avoid hammering servers.  
  Add `asyncio.sleep` delays between requests when scraping the same domain.  
- **Terms of Service** — always review a site's ToS before scraping.  
- This toolkit is intended for lawful, authorized use only.

---

## License

MIT
