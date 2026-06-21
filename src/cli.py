"""Simple CLI for web4agent."""

from __future__ import annotations

import argparse
import asyncio
import json
from typing import Any

from . import agent_read_url, agent_read_urls, agent_search, discover_links
from .doctor import format_report, run_doctor


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

    search_parser = subparsers.add_parser("search", help="Search via SearXNG and extract full content")
    search_parser.add_argument("query", nargs="+", help="Search query")
    search_parser.add_argument(
        "--max-results",
        type=int,
        default=10,
        help="Number of search hits to extract (default: 10)",
    )
    search_parser.add_argument(
        "--instance",
        help="Custom SearXNG base URL (uses public pool by default)",
    )
    search_parser.add_argument(
        "--extract-strategy",
        choices=["auto", "fast", "browser"],
        default="auto",
        help="Strategy for extracting each result page (default: auto)",
    )
    search_parser.add_argument(
        "--concurrency",
        type=int,
        default=5,
        help="Concurrent extractions (default: 5)",
    )

    doctor_parser = subparsers.add_parser(
        "doctor", help="Diagnose optional dependencies, connectivity, and circuit-breaker state"
    )
    doctor_parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw diagnostic report as JSON instead of a human-readable summary",
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


async def _run_doctor(args: argparse.Namespace) -> int:
    report = await run_doctor()
    if args.json:
        _print_json(report)
    else:
        print(format_report(report))
    return 0


async def _run_links(args: argparse.Namespace) -> int:
    links = await discover_links(
        args.url,
        same_domain=args.same_domain,
        max_links=args.max_links,
    )
    _print_json({"url": args.url, "count": len(links), "links": links})
    return 0


async def _run_search(args: argparse.Namespace) -> int:
    query = " ".join(args.query)
    result = await agent_search(
        query,
        max_results=args.max_results,
        extract_strategy=args.extract_strategy,
        extract_concurrency=args.concurrency,
        instance=args.instance,
    )
    _print_json(result)
    return 0 if result.get("extracted", 0) > 0 else 1


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command == "read":
        raise SystemExit(asyncio.run(_run_read(args)))
    if args.command == "many":
        raise SystemExit(asyncio.run(_run_many(args)))
    if args.command == "links":
        raise SystemExit(asyncio.run(_run_links(args)))
    if args.command == "search":
        raise SystemExit(asyncio.run(_run_search(args)))
    if args.command == "doctor":
        raise SystemExit(asyncio.run(_run_doctor(args)))

    parser.error(f"Unsupported command: {args.command}")


if __name__ == "__main__":
    main()
