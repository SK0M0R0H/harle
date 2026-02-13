"""HTTP routes for the prototype orchestrator API."""

from __future__ import annotations

from fastapi import APIRouter

from harle.api.models import HealthResponse, RunRequest, RunResponse
from harle.orchestrator.service import OrchestratorService


def build_router(*, orchestrator: OrchestratorService) -> APIRouter:
    """Create API routes bound to a concrete orchestrator service instance."""
    router = APIRouter()

    @router.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        return HealthResponse()

    @router.post("/run", response_model=RunResponse)
    def run_task(request: RunRequest) -> RunResponse:
        return orchestrator.run(request=request)

    return router

