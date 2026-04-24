"""Pydantic data models for web retrieval results."""

from __future__ import annotations

from pydantic import BaseModel, Field


class FetchAttempt(BaseModel):
    """Records a single fetch strategy attempt."""

    strategy: str
    success: bool
    status_code: int | None = None
    error: str | None = None
    elapsed_ms: int | None = None


class WebReadResult(BaseModel):
    """Unified result returned by all read functions."""

    url: str
    final_url: str | None = None
    title: str | None = None
    text: str | None = None
    markdown: str | None = None
    html: str | None = None
    status_code: int | None = None
    success: bool = False
    strategy_used: str | None = None
    attempts: list[FetchAttempt] = Field(default_factory=list)
    error: str | None = None
    fetched_at: str = ""
    elapsed_ms: int | None = None
    metadata: dict = Field(default_factory=dict)
