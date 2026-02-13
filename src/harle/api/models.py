"""API models for the minimal orchestrator service."""

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


class HealthResponse(BaseModel):
    """Simple health response."""

    status: str = "ok"

