"""Orchestrator per-request types and shared constants."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from harle.orchestrator.agents import HandoffRecord
from harle.orchestrator.reflection import ReflectionRunRecord

DEFAULT_AGENT_ROLE: str = "assistant"
RESULT_SUMMARY_MAX_CHARS: int = 2000


def files_used_from_package(
    p0_files: list[str],
    search_results: list,
) -> list[str]:
    """Build combined list of dataset file paths used in context (P0 + P1)."""
    paths = list(p0_files)
    for r in search_results:
        path = getattr(r, "file_path", None)
        if path and path not in paths:
            paths.append(path)
    return paths


@dataclass(frozen=True)
class AgentResult:
    """Internal result from either the Runner or the legacy provider."""

    text: str
    tools_called: list[str] = field(default_factory=list)
    turns_used: int = 0
    plan_text: str | None = None
    plan_revisions: list[str] | None = None
    planning_tool_context: str | None = None
    routing_method: str | None = None
    reflection_triggered: bool | None = None
    reflection_improved: bool | None = None
    reflection_record: ReflectionRunRecord | None = None
    handoffs: list[HandoffRecord] | None = None
    final_agent: str | None = None
    models_used: dict[str, str] | None = None


@dataclass
class RunState:
    """Mutable per-request state used for completion and failure logging."""

    run_id: str
    started_at: datetime
    message: str
    context: str
    conversation_id: str | None
    system_prompt: str | None = None
    files_used: list[str] | None = None
    tools_called: list[str] | None = None
    result_text: str | None = None
    turns_used: int | None = None
    plan_text: str | None = None
    plan_revisions: list[str] | None = None
    planning_tool_context: str | None = None
    routing_method: str | None = None
    reflection_triggered: bool | None = None
    reflection_improved: bool | None = None
    reflection_record: ReflectionRunRecord | None = None
    handoffs: list[HandoffRecord] | None = None
    final_agent: str | None = None
    starting_role: str | None = None
    models_used: dict[str, str] | None = None
    timeout_deadline_monotonic: float | None = None


class RunTimeoutError(TimeoutError):
    """Raised when an orchestrator request exceeds the configured timeout."""
