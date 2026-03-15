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
    """Response from a run or chat request.

    When the Agents SDK Runner is active, ``tools_called`` and
    ``turns_used`` provide visibility into multi-step reasoning.
    """

    run_id: str
    status: StatusType
    result: str
    context: ContextType
    agent: str = "assistant"
    conversation_id: str | None = None
    tools_called: list[str] | None = None
    turns_used: int | None = None


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


class ConnectionStatusItem(BaseModel):
    """Health status of a single connection (Notion, Trello, Tavily, etc.)."""

    name: str
    healthy: bool
    message: str = ""
    latency_ms: float | None = None


class ConnectionsHealthResponse(BaseModel):
    """Result of health checks for all registered connections."""

    connections: list[ConnectionStatusItem]
    all_healthy: bool


class ToolStatusItem(BaseModel):
    """Health status of a single tool module."""

    name: str
    healthy: bool


class ToolsHealthResponse(BaseModel):
    """Result of health checks for all registered tool modules."""

    tools: list[ToolStatusItem]
    all_healthy: bool


class HealthAllResponse(BaseModel):
    """Combined health check for connections and tools (covers tools and imports)."""

    connections: list[ConnectionStatusItem]
    tools: list[ToolStatusItem]
    all_healthy: bool


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


# --- Import models ---


class ImportRequest(BaseModel):
    """Request body for the ``/import`` endpoint."""

    source: str = Field(min_length=1, description="Import source name (e.g. 'notion')")
    config: dict = Field(default_factory=dict, description="Source-specific config")
    dry_run: bool = Field(default=False, description="Preview without writing files")


class ImportResponse(BaseModel):
    """Response from the ``/import`` endpoint."""

    status: str
    source: str
    items_found: int
    items_imported: int
    items_skipped: int
    items_failed: int
    errors: list[str] = Field(default_factory=list)
    created_paths: list[str] = Field(default_factory=list)
    updated_paths: list[str] = Field(default_factory=list)


# --- Search models ---


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

