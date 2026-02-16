"""Harle orchestrator service entrypoint."""

from __future__ import annotations

from fastapi import FastAPI
import uvicorn

from harle.api.routes import build_router
from harle.config import load_settings
from harle.orchestrator.service import build_orchestrator


def create_app() -> FastAPI:
    """Create FastAPI app with a minimal orchestrator pipeline."""
    settings = load_settings()
    orchestrator = build_orchestrator(settings=settings)

    app = FastAPI(title="Harle Prototype", version="0.1.0")
    app.include_router(build_router(orchestrator=orchestrator))
    return app


def run() -> None:
    """Run the orchestrator HTTP service."""
    settings = load_settings()
    uvicorn.run("harle.main:create_app", host=settings.HARLE_HOST, port=settings.HARLE_PORT, factory=True)

