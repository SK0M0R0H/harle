"""Minimal request orchestrator for the Harle prototype."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from harle.api.models import RunRequest, RunResponse
from harle.config import PROVIDER_OPENAI, Settings
from harle.llm.providers import EchoProvider, LLMProvider, OpenAIProvider


@dataclass
class OrchestratorService:
    """Thin orchestrator that routes user requests to an LLM provider."""

    llm_provider: LLMProvider

    def run(self, *, request: RunRequest) -> RunResponse:
        """Process a run request by delegating directly to the LLM provider."""
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        result_text = self.llm_provider.generate(
            prompt=request.message,
            context=request.context,
            conversation_id=request.conversation_id,
        )

        return RunResponse(
            run_id=run_id,
            status="completed",
            result=result_text,
            context=request.context,
            conversation_id=request.conversation_id,
        )


def build_orchestrator(*, settings: Settings) -> OrchestratorService:
    """Build a runtime orchestrator with provider fallback."""
    provider_name = settings.llm_provider.lower()

    if provider_name == PROVIDER_OPENAI and settings.openai_api_key:
        provider: LLMProvider = OpenAIProvider(
            model=settings.llm_model,
            api_key=settings.openai_api_key,
        )
        return OrchestratorService(llm_provider=provider)

    provider = EchoProvider()
    return OrchestratorService(llm_provider=provider)

