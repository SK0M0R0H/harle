"""Request orchestrator for Harle.

Coordinates context assembly and LLM generation.  When a
:class:`ContextAssembler` is available the orchestrator searches the
user's dataset and packs relevant context before calling the LLM
provider.  Without a context assembler it falls back to direct LLM
calls (prototype behaviour).
"""

from __future__ import annotations

import logging
import os
import uuid
from dataclasses import dataclass, field

from harle.api.models import RunRequest, RunResponse
from harle.config import PROVIDER_OPENAI, Settings
from harle.context.assembler import ContextAssembler
from harle.llm.providers import EchoProvider, LLMProvider, OpenAIProvider

logger = logging.getLogger(__name__)


@dataclass
class OrchestratorService:
    """Orchestrator that assembles context and routes requests to an LLM.

    When *context_assembler* is provided the :meth:`run` method will:
    1. Assemble a context package (prompts, policies, search results).
    2. Pass the assembled system prompt to the LLM provider.

    Without a context assembler the provider receives only the raw
    user message (backward-compatible prototype mode).

    Attributes:
        llm_provider: The LLM generation backend.
        context_assembler: Optional assembler for dataset-aware
            context packing.
    """

    llm_provider: LLMProvider
    context_assembler: ContextAssembler | None = field(default=None)

    def run(self, *, request: RunRequest) -> RunResponse:
        """Process a run request end-to-end.

        Steps:
            1. If a context assembler is available, build a
               :class:`ContextPackage` with prompts, policies, and
               dataset search results.
            2. Call the LLM provider with the assembled system prompt
               (or fall back to the provider's default).
            3. Return the response.

        Args:
            request: Incoming run request from the API.

        Returns:
            A :class:`RunResponse` with the generated result.
        """
        run_id = f"run_{uuid.uuid4().hex[:12]}"

        # Context assembly (when data layer is configured).
        system_prompt: str | None = None
        if self.context_assembler is not None:
            package = self.context_assembler.assemble(
                message=request.message,
                context=request.context,
            )
            system_prompt = package.system_prompt
            logger.info(
                "Context assembled: %d tokens, %d search results, "
                "%d P0 files, %d budget remaining",
                package.total_tokens,
                len(package.search_results),
                len(package.p0_files),
                package.budget_remaining,
            )

        result_text = self.llm_provider.generate(
            prompt=request.message,
            context=request.context,
            conversation_id=request.conversation_id,
            system_prompt=system_prompt,
        )

        return RunResponse(
            run_id=run_id,
            status="completed",
            result=result_text,
            context=request.context,
            conversation_id=request.conversation_id,
        )


def build_orchestrator(
    *,
    settings: Settings,
    context_assembler: ContextAssembler | None = None,
) -> OrchestratorService:
    """Build a runtime orchestrator with provider fallback.

    Args:
        settings: Application settings (LLM provider, model, etc.).
        context_assembler: Optional context assembler.  When provided
            the orchestrator searches the dataset and packs context
            before each LLM call.

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
        )

    provider = EchoProvider()
    return OrchestratorService(
        llm_provider=provider,
        context_assembler=context_assembler,
    )

