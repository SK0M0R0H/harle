"""Pydantic models for the Vault Capture interview API."""

from __future__ import annotations

from pydantic import BaseModel, Field


class InterviewStartRequest(BaseModel):
    """Request to start or resume an interview session."""

    scope: str = Field(
        default="all",
        description="Topic scope: all, work, personal, goals",
    )
    tiers: list[int] = Field(
        default_factory=lambda: [1, 2],
        description="Target tier numbers (1-4)",
    )
    resume: bool = Field(
        default=False,
        description="Resume a paused session instead of starting new",
    )


class InterviewRespondRequest(BaseModel):
    """Request to respond to an interview question or draft."""

    run_id: str = Field(description="Active capture run ID")
    response: str = Field(default="", description="User's text response")
    action: str = Field(
        default="answer",
        description="One of: answer, approve, edit, skip, pause, continue, stop",
    )


class InterviewProgressResponse(BaseModel):
    """Progress statistics within an interview."""

    completed: int = 0
    skipped: int = 0
    total: int = 0
    current_tier: int | None = None


class InterviewResponse(BaseModel):
    """Response from interview start or respond endpoints."""

    run_id: str
    action: str = Field(
        description="Next action: question, draft, summary, tier_break, complete, paused, error",
    )
    message: str
    topic_id: str | None = None
    topic_name: str | None = None
    draft_content: str | None = None
    capability_note: str | None = None
    progress: InterviewProgressResponse = Field(
        default_factory=InterviewProgressResponse,
    )
