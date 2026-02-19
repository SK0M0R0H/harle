"""HTTP routes for the orchestrator API."""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, Query

from harle.api.models import (
    HealthResponse,
    InitResponse,
    ReindexResponse,
    RunDetail,
    RunRequest,
    RunResponse,
    SearchResponse,
    SearchResultItem,
)
from harle.config import Settings
from harle.db.connection import Database
from harle.orchestrator.service import OrchestratorService
from harle.search.engine import SearchEngine

logger = logging.getLogger(__name__)


def build_router(
    *,
    orchestrator: OrchestratorService,
    db: Database | None = None,
    search_engine: SearchEngine | None = None,
    settings: Settings | None = None,
) -> APIRouter:
    """Create API routes bound to concrete service instances.

    Args:
        orchestrator: The LLM orchestrator service.
        db: Optional database instance (enables ``/init``).
        search_engine: Optional search engine (enables ``/search``).
        settings: Application settings (needed for ``/init``).
    """
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @router.post("/run", response_model=RunResponse)
    def run_task(request: RunRequest) -> RunResponse:
        return orchestrator.run(request=request)

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
        )

    @router.post("/chat", response_model=RunResponse)
    def chat(request: RunRequest) -> RunResponse:
        """Send a message in a multi-turn conversation.

        If ``conversation_id`` is ``null``, a new conversation is
        created.  Otherwise the existing conversation is continued
        and recent history is included in the LLM context.

        Requires a configured database connection.
        """
        if db is None:
            raise HTTPException(
                status_code=503,
                detail="Database is not configured. Chat requires DATABASE_URL.",
            )
        try:
            return orchestrator.chat(request=request)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/init", response_model=InitResponse)
    def init_system() -> InitResponse:
        """Create database tables, seed the dataset, and run initial indexing."""
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
    def reindex() -> ReindexResponse:
        """Re-index dataset files without seeding or recreating tables."""
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
        results = search_engine.search(query)

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
                )
                for r in results
            ],
            total=len(results),
        )

    return router

