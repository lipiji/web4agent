"""Example: fetch multiple URLs concurrently."""

import asyncio
import json

from webweb import agent_read_urls


URLS = [
    "https://en.wikipedia.org/wiki/Python_(programming_language)",
    "https://en.wikipedia.org/wiki/Asyncio",
    "https://en.wikipedia.org/wiki/Web_scraping",
    "https://httpx.readthedocs.io/en/latest/",
    "https://docs.pydantic.dev/latest/",
]


async def main() -> None:
    print(f"Fetching {len(URLS)} URLs with concurrency=5, strategy=fast\n")

    summary = await agent_read_urls(URLS, concurrency=5, strategy="fast")

    print(f"Total: {summary['total']}  Succeeded: {summary['succeeded']}  Failed: {summary['failed']}\n")

    for item in summary["results"]:
        status = "OK" if item["success"] else "FAIL"
        title = (item["title"] or "")[:60]
        print(f"[{status}] {item['url']}")
        if title:
            print(f"       Title: {title}")
        if not item["success"]:
            print(f"       Error: {item['error']}")
        content = item.get("content") or ""
        if content:
            print(f"       Preview: {content[:120].strip()!r}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
