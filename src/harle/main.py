"""Harle orchestrator service entrypoint."""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from harle.api.routes import build_router
from harle.config import load_settings
from harle.debug.levels import TraceLevel
from harle.debug.queue import init_trace_queue
from harle.debug.setup import configure_tracing
from harle.orchestrator.service import build_orchestrator

logger = logging.getLogger(__name__)


def _resolve_trace_level(name: str, default: str) -> TraceLevel:
    """Resolve trace level by name; fall back to default if invalid."""
    try:
        return TraceLevel[name.upper()]
    except KeyError:
        logger.warning("Invalid trace level %r; using %s", name, default)
        return TraceLevel[default]


def create_app() -> FastAPI:
    """Create FastAPI app with orchestrator and optional data layer.

    If ``DATABASE_URL`` and ``HARLE_DATASET_PATH`` are configured, the
    data layer (database connection, search engine, dataset reader) is
    initialised.  The search engine and dataset reader are then wired
    into a :class:`~harle.context.assembler.ContextAssembler` so the
    orchestrator can pack dataset context into every LLM request.

    Tool modules are registered when their dependencies are available:
    vault tools require a dataset, web search requires ``TAVILY_API_KEY``.
    """
    settings = load_settings()

    sse_queue = None
    if settings.HARLE_TRACING_SSE_ENABLED:
        sse_queue = init_trace_queue()
    debug_level = _resolve_trace_level(settings.HARLE_TRACING_DEBUG_LEVEL, "STEP")

    configure_tracing(
        vault_path=settings.HARLE_DATASET_PATH,
        vault_enabled=settings.HARLE_TRACING_VAULT_ENABLED,
        db_url=settings.DATABASE_URL,
        db_enabled=settings.HARLE_TRACING_DB_ENABLED,
        min_storage_level=settings.HARLE_TRACING_MIN_STORAGE_LEVEL,
        debug_mode=settings.HARLE_TRACING_SSE_ENABLED,
        sse_queue=sse_queue,
        debug_level=debug_level,
    )

    db = None
    search_engine = None
    dataset_reader = None
    context_assembler = None

    if settings.DATABASE_URL:
        from harle.db.connection import Database

        db = Database(settings.DATABASE_URL)
        logger.info("Database connection configured.")

        if settings.HARLE_DATASET_PATH:
            from harle.bootstrap import ensure_initialized
            from harle.dataset.reader import DatasetReader
            from harle.search.engine import SearchEngine

            init_result = ensure_initialized(db, settings.HARLE_DATASET_PATH)
            if init_result["already_initialized"]:
                logger.info("Startup init check: already initialized; skipped seeding/indexing.")
            else:
                logger.info(
                    "Startup init check completed (seeded=%s, indexed=%s).",
                    init_result["files_seeded"],
                    init_result["files_indexed"],
                )

            search_engine = SearchEngine(
                dataset_path=settings.HARLE_DATASET_PATH,
                db=db,
            )
            dataset_reader = DatasetReader(settings.HARLE_DATASET_PATH)
            logger.info(
                "Search engine configured (dataset: %s).",
                settings.HARLE_DATASET_PATH,
            )
    elif settings.HARLE_DATASET_PATH:
        from harle.dataset.reader import DatasetReader

        dataset_reader = DatasetReader(settings.HARLE_DATASET_PATH)
        logger.info(
            "Dataset reader configured without DB (dataset: %s).",
            settings.HARLE_DATASET_PATH,
        )
    else:
        logger.info("DATABASE_URL not set — data layer endpoints disabled.")

    if search_engine is not None or dataset_reader is not None:
        from harle.context.assembler import ContextAssembler

        context_assembler = ContextAssembler(
            search_engine=search_engine,
            dataset_reader=dataset_reader,
        )
        logger.info("Context assembler configured.")

    # ── Tool modules ─────────────────────────────────────────────────
    from harle.tools import build_tool_registry

    tool_registry = build_tool_registry(
        search_engine=search_engine,
        dataset_reader=dataset_reader,
    )

    orchestrator = build_orchestrator(
        settings=settings,
        context_assembler=context_assembler,
        db=db,
        tool_registry=tool_registry,
    )

    app = FastAPI(title="Harle", version="0.3.0")
    app.include_router(
        build_router(
            orchestrator=orchestrator,
            db=db,
            search_engine=search_engine,
            settings=settings,
        )
    )
    return app


def run() -> None:
    """Run the orchestrator HTTP service."""
    settings = load_settings()
    uvicorn.run(
        "harle.main:create_app",
        host=settings.HARLE_HOST,
        port=settings.HARLE_PORT,
        factory=True,
    )
