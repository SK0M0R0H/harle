"""API models for the orchestrator service."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


ContextType = Literal["work", "personal"]
StatusType = Literal["completed", "failed"]


class RunRequest(BaseModel):
    """Incoming request from CLI to orchestrator."""

    message: str = Field(min_length=1)
    context: ContextType = "personal"
    conversation_id: str | None = None


class RunResponse(BaseModel):
    """Single-response result for the first prototype."""

    run_id: str
    status: StatusType
    result: str
    context: ContextType
    conversation_id: str | None = None


class RunDetail(BaseModel):
    """Run metadata returned by GET /run/{run_id}."""

    run_id: str
    timestamp: str  # ISO format
    user_request: str
    context_scope: str
    agent: str
    status: str
    routing_method: str | None = None
    files_used: list[str] | None = None
    tools_called: list[str] | None = None
    result_summary: str | None = None
    result_path: str | None = None
    context_path: str | None = None
    conversation_id: str | None = None
    duration_ms: int | None = None


class HealthResponse(BaseModel):
    """Simple health response."""

    status: str = "ok"


class ErrorResponse(BaseModel):
    """Structured error returned by the API."""

    detail: str


# --- Data layer models ---


class InitResponse(BaseModel):
    """Response from the ``/init`` endpoint."""

    status: str
    tables_created: bool
    files_seeded: int
    files_indexed: int
    total_files: int
    dataset_path: str


class ReindexResponse(BaseModel):
    """Response from the ``/reindex`` endpoint."""

    status: str
    files_indexed: int
    total_files: int
    dataset_path: str


class SearchResultItem(BaseModel):
    """A single search result."""

    file_path: str
    title: str
    score: float
    context: str | None = None
    tags: list[str] = Field(default_factory=list)
    snippet: str | None = None


class SearchResponse(BaseModel):
    """Response from the ``/search`` endpoint."""

    query: str
    context: str | None = None
    results: list[SearchResultItem] = Field(default_factory=list)
    total: int = 0

