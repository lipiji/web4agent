"""Example: fetch a single URL with auto-degradation strategy."""

import asyncio
import json

from webweb import agent_read_url


async def main() -> None:
    url = "https://en.wikipedia.org/wiki/Web_scraping"
    print(f"Fetching: {url}\n")

    result = await agent_read_url(url, strategy="auto")

    print(json.dumps(result, indent=2, ensure_ascii=False))

    if result["success"]:
        content = result["content"] or ""
        print(f"\n--- Preview (first 500 chars) ---\n{content[:500]}")
    else:
        print(f"\nFailed: {result['error']}")


if __name__ == "__main__":
    asyncio.run(main())
