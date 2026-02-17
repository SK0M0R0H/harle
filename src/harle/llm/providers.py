"""LLM provider layer for the first Harle prototype."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI


class LLMProvider(Protocol):
    """Provider interface for text generation.

    All providers must implement :meth:`generate`.  The optional
    *system_prompt* parameter allows the orchestrator to pass a
    context-assembled prompt instead of relying on a hardcoded default.
    """

    def generate(
        self,
        *,
        prompt: str,
        context: str,
        conversation_id: str | None,
        system_prompt: str | None = None,
    ) -> str:
        """Generate a text response for a request.

        Args:
            prompt: The user's message.
            context: Active context scope (``"work"`` / ``"personal"``).
            conversation_id: Conversation identifier for multi-turn
                sessions, or ``None`` for one-shot requests.
            system_prompt: Pre-assembled system prompt from the
                Context Assembler.  When provided the provider should
                use it instead of its built-in default.
        """


@dataclass(frozen=True)
class OpenAIProvider:
    """OpenAI-backed provider implementation."""

    model: str
    api_key: str

    def generate(
        self,
        *,
        prompt: str,
        context: str,
        conversation_id: str | None,
        system_prompt: str | None = None,
    ) -> str:
        """Generate a response using the OpenAI Responses API.

        When *system_prompt* is provided (from the Context Assembler)
        it replaces the built-in default system text.

        Args:
            prompt: The user's message.
            context: Active context scope.
            conversation_id: Conversation identifier (unused for now).
            system_prompt: Pre-assembled system prompt, or ``None``
                to use the default.
        """
        client = OpenAI(api_key=self.api_key)
        if system_prompt is None:
            system_prompt = (
                "You are Harle, a concise assistant. "
                f"Current context: {context}. "
                "Answer directly and keep structure clear."
            )
        response = client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": prompt},
            ],
        )
        return response.output_text.strip()


class EchoProvider:
    """Local fallback provider when no external LLM credentials are available."""

    def generate(
        self,
        *,
        prompt: str,
        context: str,
        conversation_id: str | None,
        system_prompt: str | None = None,
    ) -> str:
        """Return a deterministic placeholder response.

        Args:
            prompt: The user's message.
            context: Active context scope.
            conversation_id: Conversation identifier (unused).
            system_prompt: Ignored by the echo provider.
        """
        prefix = "[echo provider] OPENAI_API_KEY environment variable not set."
        return f"{prefix}\ncontext={context}\nmessage={prompt}"

