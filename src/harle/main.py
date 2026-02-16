"""Harle orchestrator service entrypoint."""

from __future__ import annotations

import logging

from fastapi import FastAPI
import uvicorn

from harle.api.routes import build_router
from harle.config import load_settings
from harle.orchestrator.service import build_orchestrator

logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    """Create FastAPI app with orchestrator and optional data layer.

    If ``DATABASE_URL`` and ``HARLE_DATASET_PATH`` are configured, the
    data layer (database connection + search engine) is initialised and
    the ``/init`` and ``/search`` endpoints become available.
    """
    settings = load_settings()
    orchestrator = build_orchestrator(settings=settings)

    # Data layer is optional — only enabled when both DB and dataset
    # paths are configured.
    db = None
    search_engine = None

    if settings.DATABASE_URL:
        from harle.db.connection import Database

        db = Database(settings.DATABASE_URL)
        logger.info("Database connection configured.")

        if settings.HARLE_DATASET_PATH:
            from harle.search.engine import SearchEngine

            search_engine = SearchEngine(
                dataset_path=settings.HARLE_DATASET_PATH,
                db=db,
            )
            logger.info("Search engine configured (dataset: %s).", settings.HARLE_DATASET_PATH)
    else:
        logger.info("DATABASE_URL not set — data layer endpoints disabled.")

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

