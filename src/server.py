"""Optional FastAPI server exposing web retrieval as HTTP endpoints."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

try:
    from fastapi import FastAPI
    from pydantic import BaseModel as _BaseModel
except ImportError as _exc:
    raise ImportError(
        "FastAPI is not installed. "
        "Run: pip install 'web4agent[server]'"
    ) from _exc

from .batch import read_many
from .browser import close_browser
from .links import discover_links
from .router import read_url


# ── Request / Response schemas ─────────────────────────────────────────────────

class ReadRequest(_BaseModel):
    url: str
    strategy: str = "auto"


class ReadManyRequest(_BaseModel):
    urls: list[str]
    concurrency: int = 10
    strategy: str = "auto"


class DiscoverLinksRequest(_BaseModel):
    url: str
    same_domain: bool = True
    max_links: int = 100


# ── App ────────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def _lifespan(app: FastAPI):
    yield
    await close_browser()


app = FastAPI(
    title="Web Retrieval Toolkit",
    description="Free, open-source async web scraping API for LLM agents.",
    version="0.1.0",
    lifespan=_lifespan,
)


@app.get("/health")
async def health() -> dict[str, Any]:
    return {"status": "ok"}


@app.post("/read")
async def api_read(req: ReadRequest) -> dict[str, Any]:
    result = await read_url(req.url, strategy=req.strategy)
    return result.model_dump()


@app.post("/read_many")
async def api_read_many(req: ReadManyRequest) -> list[dict[str, Any]]:
    results = await read_many(req.urls, concurrency=req.concurrency, strategy=req.strategy)
    return [r.model_dump() for r in results]


@app.post("/discover_links")
async def api_discover_links(req: DiscoverLinksRequest) -> dict[str, Any]:
    links = await discover_links(req.url, same_domain=req.same_domain, max_links=req.max_links)
    return {"url": req.url, "links": links, "count": len(links)}
