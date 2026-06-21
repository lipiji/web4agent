"""Diagnostics: optional dependency availability, upstream connectivity, and
the auto-degradation chain's circuit breaker state."""

from __future__ import annotations

import asyncio
import importlib.util

from .health import default_tracker

# Diagnostics should return quickly; this is independent of WRT_TIMEOUT,
# which governs full page fetches and would make `doctor` block for ~20s
# per unreachable target.
_CONNECTIVITY_TIMEOUT = 5.0

# Maps a human-readable label to the importable module it depends on.
_OPTIONAL_DEPS: dict[str, str] = {
    "fast (TLS impersonation)": "curl_cffi",
    "browser (stealth)": "patchright",
    "browser (fallback)": "playwright",
    "crawl4ai": "crawl4ai",
}

# Upstream services the extended fallback tiers depend on.
_CONNECTIVITY_TARGETS: dict[str, str] = {
    "wayback": "https://archive.org",
    "ddg": "https://duckduckgo.com",
}


def _check_dependencies() -> list[dict]:
    return [
        {"name": label, "module": module, "installed": importlib.util.find_spec(module) is not None}
        for label, module in _OPTIONAL_DEPS.items()
    ]


async def _check_one(client, name: str, url: str) -> dict:
    try:
        resp = await client.head(url)
        return {"target": name, "url": url, "reachable": resp.status_code < 500}
    except Exception as exc:
        return {
            "target": name,
            "url": url,
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}",
        }


async def _check_connectivity(timeout: float = _CONNECTIVITY_TIMEOUT) -> list[dict]:
    import httpx

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        return await asyncio.gather(
            *(_check_one(client, name, url) for name, url in _CONNECTIVITY_TARGETS.items())
        )


async def run_doctor(timeout: float = _CONNECTIVITY_TIMEOUT) -> dict:
    """Run all diagnostic checks and return a structured report."""
    return {
        "dependencies": _check_dependencies(),
        "connectivity": await _check_connectivity(timeout=timeout),
        "circuit_breakers": default_tracker.status(),
    }


def format_report(report: dict) -> str:
    """Render a doctor report as human-readable text for the CLI."""
    lines = ["Dependencies:"]
    for dep in report["dependencies"]:
        mark = "OK" if dep["installed"] else "MISSING"
        lines.append(f"  [{mark}] {dep['name']} ({dep['module']})")

    lines.append("Connectivity:")
    for target in report["connectivity"]:
        mark = "OK" if target["reachable"] else "UNREACHABLE"
        suffix = f" - {target['error']}" if target.get("error") else ""
        lines.append(f"  [{mark}] {target['target']} ({target['url']}){suffix}")

    breakers = report["circuit_breakers"]
    lines.append("Circuit breakers:")
    if not breakers:
        lines.append("  (no strategy has failed yet - nothing tripped)")
    for b in breakers:
        mark = "OPEN" if not b["available"] else "CLOSED"
        cooldown = f", retry in {b['cooldown_remaining_s']}s" if not b["available"] else ""
        lines.append(f"  [{mark}] {b['strategy']} (failures={b['failures']}{cooldown})")

    return "\n".join(lines)
