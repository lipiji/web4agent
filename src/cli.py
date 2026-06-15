"""Simple CLI for web4agent."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from . import agent_read_url, agent_read_urls, discover_links


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="web4agent",
        description="Easy web reader for LLM-friendly output.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    read_parser = subparsers.add_parser("read", help="Fetch one URL")
    read_parser.add_argument("url", help="Target URL")
    read_parser.add_argument(
        "--strategy",
        choices=["auto", "fast", "crawl4ai", "browser", "wayback", "ddg"],
        default="auto",
        help="Fetch strategy (default: auto)",
    )
    read_parser.add_argument(
        "--max-content-chars",
        type=int,
        default=1200,
        help="Preview length in terminal output (default: 1200)",
    )

    many_parser = subparsers.add_parser("many", help="Fetch multiple URLs")
    many_parser.add_argument("urls", nargs="+", help="Target URLs")
    many_parser.add_argument(
        "--strategy",
        choices=["auto", "fast", "crawl4ai", "browser", "wayback", "ddg"],
        default="auto",
        help="Fetch strategy (default: auto)",
    )
    many_parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Concurrent requests (default: 5)",
    )
    many_parser.add_argument(
        "--max-content-chars",
        type=int,
        default=300,
        help="Preview length per URL (default: 300)",
    )

    links_parser = subparsers.add_parser("links", help="Extract links from one URL")
    links_parser.add_argument("url", help="Target URL")
    links_parser.add_argument(
        "--same-domain",
        action="store_true",
        help="Only keep links on the same domain",
    )
    links_parser.add_argument(
        "--max-links",
        type=int,
        default=50,
        help="Maximum links to return (default: 50)",
    )

    return parser


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False))


async def _run_read(args: argparse.Namespace) -> int:
    result = await agent_read_url(args.url, strategy=args.strategy)
    content = result.get("content") or ""
    if args.max_content_chars >= 0:
        result["content"] = content[: args.max_content_chars]
    _print_json(result)
    return 0 if result.get("success") else 1


async def _run_many(args: argparse.Namespace) -> int:
    summary = await agent_read_urls(
        args.urls,
        strategy=args.strategy,
        concurrency=args.concurrency,
    )

    max_chars = max(0, args.max_content_chars)
    for item in summary.get("results", []):
        content = item.get("content") or ""
        item["content"] = content[:max_chars]

    _print_json(summary)
    return 0 if summary.get("failed", 0) == 0 else 1


async def _run_links(args: argparse.Namespace) -> int:
    links = await discover_links(
        args.url,
        same_domain=args.same_domain,
        max_links=args.max_links,
    )
    _print_json({"url": args.url, "count": len(links), "links": links})
    return 0


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "read":
        raise SystemExit(asyncio.run(_run_read(args)))
    if args.command == "many":
        raise SystemExit(asyncio.run(_run_many(args)))
    if args.command == "links":
        raise SystemExit(asyncio.run(_run_links(args)))

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
