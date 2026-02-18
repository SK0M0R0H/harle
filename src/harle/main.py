"""Harle orchestrator service entrypoint."""

from __future__ import annotations

import logging

import uvicorn
from fastapi import FastAPI

from harle.api.routes import build_router
from harle.config import load_settings
from harle.orchestrator.service import build_orchestrator

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create FastAPI app with orchestrator and optional data layer.

    If ``DATABASE_URL`` and ``HARLE_DATASET_PATH`` are configured, the
    data layer (database connection, search engine, dataset reader) is
    initialised.  The search engine and dataset reader are then wired
    into a :class:`~harle.context.assembler.ContextAssembler` so the
    orchestrator can pack dataset context into every LLM request.
    """
    settings = load_settings()

    # Data layer is optional — only enabled when both DB and dataset
    # paths are configured.
    db = None
    search_engine = None
    dataset_reader = None
    context_assembler = None

    if settings.DATABASE_URL:
        from harle.db.connection import Database

        db = Database(settings.DATABASE_URL)
        logger.info("Database connection configured.")

        if settings.HARLE_DATASET_PATH:
            from harle.dataset.reader import DatasetReader
            from harle.search.engine import SearchEngine

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
        # Dataset reader can work without the database (P0 loading).
        from harle.dataset.reader import DatasetReader

        dataset_reader = DatasetReader(settings.HARLE_DATASET_PATH)
        logger.info(
            "Dataset reader configured without DB (dataset: %s).",
            settings.HARLE_DATASET_PATH,
        )
    else:
        logger.info("DATABASE_URL not set — data layer endpoints disabled.")

    # Context assembler — available when at least a dataset reader or
    # search engine is configured.
    if search_engine is not None or dataset_reader is not None:
        from harle.context.assembler import ContextAssembler

        context_assembler = ContextAssembler(
            search_engine=search_engine,
            dataset_reader=dataset_reader,
        )
        logger.info("Context assembler configured.")

    orchestrator = build_orchestrator(
        settings=settings,
        context_assembler=context_assembler,
        db=db,
    )

    app = FastAPI(title="Harle", version="0.2.0")
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

