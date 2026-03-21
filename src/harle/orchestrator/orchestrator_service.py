"""Orchestrator service dataclass — composes execution, chat, and finalize mixins."""

from __future__ import annotations

from dataclasses import dataclass, field

from harle.context.assembler import ContextAssembler
from harle.db.connection import Database
from harle.llm.providers import LLMProvider
from harle.tools.registry import ToolRegistry

from harle.orchestrator.chat import ChatMixin
from harle.orchestrator.execution import ExecutionMixin
from harle.orchestrator.finalize import FinalizeMixin


@dataclass
class OrchestratorService(ExecutionMixin, ChatMixin, FinalizeMixin):
    """Orchestrator that assembles context and routes requests to an LLM.

    Attributes:
        llm_provider: The LLM generation backend (fallback path).
        context_assembler: Optional assembler for dataset-aware
            context packing.
        db: Optional database connection for conversation and runs.
        dataset_path: Optional vault root path for writing run logs.
        run_log_store_context: Whether to store assembled context in
            logs.
        tool_registry: Optional tool registry providing agent tools.
        model: LLM model name for the Agents SDK Agent.
        max_iterations: Maximum turns for the agentic loop.
        use_agent_runner: When ``True``, use the Agents SDK Runner
            instead of the direct LLM provider.
        planning_enabled: When ``True`` (default), complex requests may
            use Level 3 plan-then-execute (see ``runner_execution``).
        planning_model: Optional model for the planning agent; ``None``
            uses the same model as execution.
        planning_max_turns: Max turns for the planning agent tool loop.
        planned_max_turns: Max execution turns when a plan exists;
            ``None`` uses ``max_iterations``.
    """

    llm_provider: LLMProvider
    context_assembler: ContextAssembler | None = field(default=None)
    db: Database | None = field(default=None)
    dataset_path: str | None = field(default=None)
    run_log_store_context: bool = field(default=False)
    tool_registry: ToolRegistry | None = field(default=None)
    model: str = field(default="gpt-4o-mini")
    max_iterations: int = field(default=10)
    run_timeout_seconds: int | None = field(default=60)
    use_agent_runner: bool = field(default=False)
    planning_enabled: bool = field(default=True)
    planning_model: str | None = field(default=None)
    planning_max_turns: int = field(default=5)
    planned_max_turns: int | None = field(default=None)
    reflection_enabled: bool = field(default=True)
    reflection_model: str | None = field(default=None)
    reflection_min_tool_calls: int = field(default=3)
    reflection_trigger_keywords: str = field(
        default="research,report,analysis,compare,evaluate,review,summarize",
    )
    reflection_trigger_roles: str = field(default="researcher")
    reflection_improvement_max_turns: int | None = field(default=None)
    #: Per-role tool module allowlist (from JSON / defaults). ``None`` uses
    #: built-in defaults only (no file resolution).
    role_tool_modules: dict[str, list[str]] | None = field(default=None)
