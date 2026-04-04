"""HTTP routes for the orchestrator API."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Generator

from fastapi import APIRouter, HTTPException, Query, Request
from sse_starlette.sse import EventSourceResponse
from starlette.concurrency import run_in_threadpool

from harle.api.models import (
    ConnectionStatusItem,
    ConnectionsHealthResponse,
    HealthAllResponse,
    HealthResponse,
    ImportRequest,
    ImportResponse,
    InitResponse,
    ProcessingStatusResponse,
    ReindexResponse,
    RunDetail,
    RunRequest,
    RunResponse,
    SearchResponse,
    SearchResultItem,
    ToolStatusItem,
    ToolsHealthResponse,
)
from harle.api.processing_registry import (
    MAX_REQUEST_ID_BYTES,
    DuplicateActiveProcessingError,
    ProcessingRegistry,
)
from harle.api.streaming import drain_debug_events, result_event
from harle.config import Settings
from harle.db.connection import Database
from harle.orchestrator.service import OrchestratorService, RunTimeoutError
from harle.search.engine import SearchEngine

logger = logging.getLogger(__name__)

HARLE_CLIENT_HEADER = "X-Harle-Client"


def _harle_client_from_request(http_request: Request) -> str:
    label = (http_request.headers.get(HARLE_CLIENT_HEADER) or "").strip()
    return label or "unknown"


def _raise_if_processing_id_too_large(request_id: str) -> None:
    if len(request_id.encode("utf-8")) > MAX_REQUEST_ID_BYTES:
        raise HTTPException(
            status_code=400,
            detail=f"request_id exceeds maximum length ({MAX_REQUEST_ID_BYTES} bytes).",
        )


def build_router(
    *,
    orchestrator: OrchestratorService,
    processing_registry: ProcessingRegistry,
    db: Database | None = None,
    search_engine: SearchEngine | None = None,
    settings: Settings | None = None,
    import_registry: object | None = None,
    connections: object | None = None,
    tool_registry: object | None = None,
) -> APIRouter:
    """Create API routes bound to concrete service instances.

    Args:
        orchestrator: The LLM orchestrator service.
        processing_registry: In-flight ``/chat`` tracking for ``GET /processing/{request_id}``.
        db: Optional database instance (enables ``/init``).
        search_engine: Optional search engine (enables ``/search``).
        settings: Application settings (needed for ``/init``).
        import_registry: Optional ``ImportRegistry`` (enables ``/import``).
        connections: Optional ``ConnectionRegistry`` (enables ``/health/connections``).
        tool_registry: Optional ``ToolRegistry`` (enables ``/health/tools``).
    """
    router = APIRouter()

    def _run_async(coro):
        import asyncio
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(1) as pool:
            return pool.submit(asyncio.run, coro).result()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @router.get("/health/connections", response_model=ConnectionsHealthResponse)
    def health_connections() -> ConnectionsHealthResponse:
        """Run health checks for all registered connections (Notion, Trello, Tavily, etc.)."""
        if connections is None:
            return ConnectionsHealthResponse(connections=[], all_healthy=True)
        from harle.connections.registry import ConnectionRegistry
        reg: ConnectionRegistry = connections  # type: ignore[assignment]
        statuses = _run_async(reg.health_check_all())
        items = [
            ConnectionStatusItem(
                name=name,
                healthy=s.healthy,
                message=s.message or "",
                latency_ms=s.latency_ms,
            )
            for name, s in statuses.items()
        ]
        return ConnectionsHealthResponse(
            connections=items,
            all_healthy=all(s.healthy for s in statuses.values()),
        )

    @router.get("/health/tools", response_model=ToolsHealthResponse)
    def health_tools() -> ToolsHealthResponse:
        """Run health checks for all registered tool modules."""
        if tool_registry is None:
            return ToolsHealthResponse(tools=[], all_healthy=True)
        from harle.tools.registry import ToolRegistry
        reg: ToolRegistry = tool_registry  # type: ignore[assignment]
        results = _run_async(reg.health_check_all())
        items = [ToolStatusItem(name=name, healthy=ok) for name, ok in results.items()]
        return ToolsHealthResponse(
            tools=items,
            all_healthy=all(results.values()) if results else True,
        )

    @router.get("/health/all", response_model=HealthAllResponse)
    def health_all() -> HealthAllResponse:
        """Run health checks for all connections and tool modules (covers tools and imports)."""
        conn_items: list[ConnectionStatusItem] = []
        if connections is not None:
            from harle.connections.registry import ConnectionRegistry
            reg: ConnectionRegistry = connections  # type: ignore[assignment]
            statuses = _run_async(reg.health_check_all())
            conn_items = [
                ConnectionStatusItem(
                    name=name,
                    healthy=s.healthy,
                    message=s.message or "",
                    latency_ms=s.latency_ms,
                )
                for name, s in statuses.items()
            ]
        tool_items: list[ToolStatusItem] = []
        if tool_registry is not None:
            from harle.tools.registry import ToolRegistry
            reg: ToolRegistry = tool_registry  # type: ignore[assignment]
            results = _run_async(reg.health_check_all())
            tool_items = [ToolStatusItem(name=name, healthy=ok) for name, ok in results.items()]
        conn_healthy = all(c.healthy for c in conn_items) if conn_items else True
        tool_healthy = all(t.healthy for t in tool_items) if tool_items else True
        return HealthAllResponse(
            connections=conn_items,
            tools=tool_items,
            all_healthy=conn_healthy and tool_healthy,
        )

    @router.get("/processing/{request_id}", response_model=ProcessingStatusResponse)
    def get_processing_status(request_id: str) -> ProcessingStatusResponse:
        """Return whether the given request ID is still being processed by /chat."""
        _raise_if_processing_id_too_large(request_id)
        entry = processing_registry.get_status(request_id)
        if entry is None:
            return ProcessingStatusResponse(
                request_id=request_id,
                status="not_found",
                started_at=None,
            )
        return ProcessingStatusResponse(
            request_id=request_id,
            status=entry.status,
            started_at=entry.started_at.isoformat(),
        )

    @router.get("/run/{run_id}", response_model=RunDetail)
    def get_run(run_id: str) -> RunDetail:
        """Return metadata for a single run by run_id."""
        if db is None:
            raise HTTPException(
                status_code=503,
                detail="Database is not configured. Set DATABASE_URL in config.",
            )
        from harle.db.runs import get_run as _get_run
        with db.session() as session:
            run = _get_run(session, run_id)
            if run is None:
                raise HTTPException(status_code=404, detail=f"Run {run_id!r} not found.")
            return RunDetail(
                run_id=run.run_id,
                timestamp=run.timestamp.isoformat(),
                user_request=run.user_request,
                context_scope=run.context_scope,
                agent=run.agent,
                status=run.status,
                routing_method=run.routing_method,
                files_used=run.files_used,
                tools_called=run.tools_called,
                result_summary=run.result_summary,
                result_path=run.result_path,
                context_path=run.context_path,
                conversation_id=run.conversation_id,
                duration_ms=run.duration_ms,
                reflection_triggered=run.reflection_triggered,
                reflection_improved=run.reflection_improved,
                handoffs=run.handoffs,
                models_used=run.models_used,
            )

    @router.post("/chat", response_model=RunResponse)
    async def chat(
        http_request: Request,
        request: RunRequest,
        debug: bool = Query(default=False, description="Enable SSE debug event stream"),
    ) -> RunResponse | EventSourceResponse:
        """Submit a task or send a message in a conversation.

        If ``conversation_id`` is ``null``, a new conversation is
        created (one-shot tasks use a single exchange in that
        conversation).  Otherwise the existing conversation is
        continued and recent history is included in the LLM context.

        Requires a configured database connection.
        """
        if db is None:
            raise HTTPException(
                status_code=503,
                detail="Database is not configured. Chat requires DATABASE_URL.",
            )
        if await http_request.is_disconnected():
            run_id = orchestrator.record_aborted_request(request=request)
            logger.warning(
                "Client disconnected before /chat execution (run_id=%s conversation_id=%s)",
                run_id,
                request.conversation_id,
            )
            raise HTTPException(
                status_code=499,
                detail=(
                    "Client disconnected before chat execution started. "
                    f"Recorded aborted run {run_id}."
                ),
            )

        logger.info(
            "Received /chat request",
            extra={
                "path": str(http_request.url.path),
                "context_scope": request.context,
                "conversation_id": request.conversation_id,
                "harle_client": _harle_client_from_request(http_request),
            },
        )
        client_request_id = (http_request.headers.get("X-Request-ID") or "").strip()
        if client_request_id:
            try:
                processing_registry.register(client_request_id)
            except DuplicateActiveProcessingError as exc:
                raise HTTPException(
                    status_code=409,
                    detail=(
                        "A chat request with this X-Request-ID is already in progress."
                    ),
                ) from exc
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            response = await run_in_threadpool(orchestrator.chat, request=request)
        except RunTimeoutError as exc:
            raise HTTPException(
                status_code=504,
                detail="Chat request exceeded the server-side timeout before completion.",
            ) from exc
        except asyncio.CancelledError:
            # Mid-flight disconnects are not reliably recoverable while the
            # synchronous orchestrator continues in the threadpool.
            logger.warning(
                "Client disconnected during /chat request handling (conversation_id=%s)",
                request.conversation_id,
            )
            raise
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        finally:
            if client_request_id:
                processing_registry.deregister(client_request_id)
        if debug:
            return _sse_response(response)
        return response

    @router.post("/init", response_model=InitResponse)
    def init_system(http_request: Request) -> InitResponse:
        """Create database tables, seed the dataset, and run initial indexing."""
        logger.info(
            "POST /init",
            extra={"harle_client": _harle_client_from_request(http_request)},
        )
        if db is None or settings is None:
            raise HTTPException(
                status_code=503,
                detail="Database is not configured. Set DATABASE_URL in config.",
            )
        if not settings.HARLE_DATASET_PATH:
            raise HTTPException(
                status_code=503,
                detail="Dataset path is not configured. Set HARLE_DATASET_PATH in config.",
            )

        from harle.bootstrap import init_system as _init_system

        result = _init_system(db, settings.HARLE_DATASET_PATH)
        return InitResponse(
            status="initialized",
            tables_created=result["tables_created"],  # type: ignore[arg-type]
            files_seeded=result["files_seeded"],  # type: ignore[arg-type]
            files_indexed=result["files_indexed"],  # type: ignore[arg-type]
            total_files=result["total_files"],  # type: ignore[arg-type]
            dataset_path=result["dataset_path"],  # type: ignore[arg-type]
        )

    @router.post("/reindex", response_model=ReindexResponse)
    def reindex(http_request: Request) -> ReindexResponse:
        """Re-index dataset files without seeding or recreating tables."""
        logger.info(
            "POST /reindex",
            extra={"harle_client": _harle_client_from_request(http_request)},
        )
        if db is None or settings is None:
            raise HTTPException(
                status_code=503,
                detail="Database is not configured. Set DATABASE_URL in config.",
            )
        if not settings.HARLE_DATASET_PATH:
            raise HTTPException(
                status_code=503,
                detail="Dataset path is not configured. Set HARLE_DATASET_PATH in config.",
            )

        from harle.bootstrap import reindex_dataset

        result = reindex_dataset(db, settings.HARLE_DATASET_PATH)
        return ReindexResponse(
            status="reindexed",
            files_indexed=result["files_indexed"],  # type: ignore[arg-type]
            total_files=result["total_files"],  # type: ignore[arg-type]
            dataset_path=result["dataset_path"],  # type: ignore[arg-type]
        )

    @router.get("/search", response_model=SearchResponse)
    def search_dataset(
        q: str = Query(min_length=1, description="Search query"),
        context: str | None = Query(default=None, description="Context scope filter"),
        max_results: int = Query(default=10, ge=1, le=50, description="Max results"),
    ) -> SearchResponse:
        """Search the indexed dataset for relevant files."""
        if search_engine is None:
            raise HTTPException(
                status_code=503,
                detail="Search is not configured. Run /init first and check config.",
            )

        from harle.search.types import SearchQuery

        query = SearchQuery(query=q, context=context, max_results=max_results)
        search_response = search_engine.search(query)
        # Support both SearchResponse (Phase 2) and plain list (backward compat)
        results = getattr(search_response, "file_results", search_response)

        return SearchResponse(
            query=q,
            context=context,
            results=[
                SearchResultItem(
                    file_path=r.file_path,
                    title=r.title,
                    score=r.score,
                    context=r.context,
                    tags=r.tags,
                    snippet=r.snippet,
                    chunk_index=getattr(r, "chunk_index", None),
                    heading_path=getattr(r, "heading_path", None),
                )
                for r in results
            ],
            total=len(results),
        )

    @router.post("/import", response_model=ImportResponse)
    def run_import(http_request: Request, request: ImportRequest) -> ImportResponse:
        """Run an import from an external source into the vault."""
        logger.info(
            "POST /import",
            extra={
                "harle_client": _harle_client_from_request(http_request),
                "source": request.source,
            },
        )
        if import_registry is None:
            raise HTTPException(
                status_code=503,
                detail="Import registry is not configured.",
            )
        if settings is None or not settings.HARLE_DATASET_PATH:
            raise HTTPException(
                status_code=503,
                detail="Dataset path is not configured. Set HARLE_DATASET_PATH.",
            )

        from harle.vault_imports.registry import ImportRegistry, ImportSourceNotFound

        registry: ImportRegistry = import_registry  # type: ignore[assignment]

        import asyncio

        try:
            try:
                loop = asyncio.get_running_loop()
            except RuntimeError:
                result = asyncio.run(
                    registry.run_import(
                        request.source,
                        request.config,
                        vault_path=settings.HARLE_DATASET_PATH,
                        dry_run=request.dry_run,
                    )
                )
            else:
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(1) as pool:
                    result = pool.submit(
                        asyncio.run,
                        registry.run_import(
                            request.source,
                            request.config,
                            vault_path=settings.HARLE_DATASET_PATH,
                            dry_run=request.dry_run,
                        ),
                    ).result()
        except ImportSourceNotFound as e:
            raise HTTPException(status_code=404, detail=str(e)) from e
        except Exception as e:
            logger.exception("Import failed: %s", e)
            raise HTTPException(status_code=500, detail=str(e)) from e

        status = "dry_run" if request.dry_run else "completed"
        if result.errors:
            status = "completed_with_errors" if result.items_imported else "failed"

        return ImportResponse(
            status=status,
            source=result.source_name,
            items_found=result.items_found,
            items_imported=result.items_imported,
            items_skipped=result.items_skipped,
            items_failed=result.items_failed,
            errors=result.errors,
            created_paths=result.created_paths,
            updated_paths=result.updated_paths,
        )

    def _sse_response(response: RunResponse) -> EventSourceResponse:
        """Wrap a completed run as an SSE stream with any pending trace events."""
        from harle.debug.queue import get_trace_queue

        def _generate() -> Generator[dict[str, str], None, None]:
            queue = get_trace_queue()
            if queue is not None:
                yield from drain_debug_events(queue)
            yield result_event(response)

        return EventSourceResponse(_generate())

    return router
