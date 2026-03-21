"""Factory for :class:`~harle.orchestrator.orchestrator_service.OrchestratorService`."""

from __future__ import annotations

import os

from harle.config import PROVIDER_OPENAI, Settings
from harle.context.assembler import ContextAssembler
from harle.db.connection import Database
from harle.llm.providers import EchoProvider, LLMProvider, OpenAIProvider
from harle.orchestrator.orchestrator_service import OrchestratorService
from harle.tools.registry import ToolRegistry


def build_orchestrator(
    *,
    settings: Settings,
    context_assembler: ContextAssembler | None = None,
    db: Database | None = None,
    tool_registry: ToolRegistry | None = None,
) -> OrchestratorService:
    """Build a runtime orchestrator with provider fallback.

    When an OpenAI API key is available the orchestrator uses the
    Agents SDK Runner for multi-step reasoning.  Otherwise it falls
    back to the echo provider for local development.

    Args:
        settings: Application settings (LLM provider, model, etc.).
        context_assembler: Optional context assembler.
        db: Optional database connection.
        tool_registry: Optional tool registry with registered modules.

    Returns:
        A fully configured :class:`OrchestratorService`.
    """
    provider_name = settings.HARLE_LLM_PROVIDER.lower()
    openai_api_key = os.getenv("OPENAI_API_KEY")

    if provider_name == PROVIDER_OPENAI and openai_api_key:
        provider: LLMProvider = OpenAIProvider(
            model=settings.HARLE_LLM_MODEL,
            api_key=openai_api_key,
        )
        return OrchestratorService(
            llm_provider=provider,
            context_assembler=context_assembler,
            db=db,
            dataset_path=settings.HARLE_DATASET_PATH,
            run_log_store_context=settings.HARLE_RUN_LOG_STORE_CONTEXT,
            tool_registry=tool_registry,
            model=settings.HARLE_LLM_MODEL,
            max_iterations=settings.HARLE_MAX_ITERATIONS,
            run_timeout_seconds=settings.HARLE_RUN_TIMEOUT_SECONDS,
            use_agent_runner=True,
            planning_enabled=settings.HARLE_PLANNING_ENABLED,
            planning_model=settings.HARLE_PLANNING_MODEL,
            planning_max_turns=settings.HARLE_PLANNING_MAX_TURNS,
            planned_max_turns=settings.HARLE_PLANNED_MAX_TURNS,
            reflection_enabled=settings.HARLE_REFLECTION_ENABLED,
            reflection_model=settings.HARLE_REFLECTION_MODEL,
            reflection_min_tool_calls=settings.HARLE_REFLECTION_MIN_TOOL_CALLS,
            reflection_trigger_keywords=settings.HARLE_REFLECTION_TRIGGER_KEYWORDS,
            reflection_trigger_roles=settings.HARLE_REFLECTION_TRIGGER_ROLES,
            reflection_improvement_max_turns=settings.HARLE_REFLECTION_IMPROVEMENT_MAX_TURNS,
        )

    provider = EchoProvider()
    return OrchestratorService(
        llm_provider=provider,
        context_assembler=context_assembler,
        db=db,
        dataset_path=settings.HARLE_DATASET_PATH,
        run_log_store_context=settings.HARLE_RUN_LOG_STORE_CONTEXT,
        tool_registry=tool_registry,
        model=settings.HARLE_LLM_MODEL,
        max_iterations=settings.HARLE_MAX_ITERATIONS,
        run_timeout_seconds=settings.HARLE_RUN_TIMEOUT_SECONDS,
        use_agent_runner=False,
        planning_enabled=settings.HARLE_PLANNING_ENABLED,
        planning_model=settings.HARLE_PLANNING_MODEL,
        planning_max_turns=settings.HARLE_PLANNING_MAX_TURNS,
        planned_max_turns=settings.HARLE_PLANNED_MAX_TURNS,
        reflection_enabled=settings.HARLE_REFLECTION_ENABLED,
        reflection_model=settings.HARLE_REFLECTION_MODEL,
        reflection_min_tool_calls=settings.HARLE_REFLECTION_MIN_TOOL_CALLS,
        reflection_trigger_keywords=settings.HARLE_REFLECTION_TRIGGER_KEYWORDS,
        reflection_trigger_roles=settings.HARLE_REFLECTION_TRIGGER_ROLES,
        reflection_improvement_max_turns=settings.HARLE_REFLECTION_IMPROVEMENT_MAX_TURNS,
    )
