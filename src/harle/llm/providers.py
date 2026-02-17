"""LLM provider layer for the first Harle prototype."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openai import OpenAI


class LLMProvider(Protocol):
    """Provider interface for text generation."""

    def generate(self, *, prompt: str, context: str, conversation_id: str | None) -> str:
        """Generate a text response for a request."""


@dataclass(frozen=True)
class OpenAIProvider:
    """OpenAI-backed provider implementation."""

    model: str
    api_key: str

    def generate(self, *, prompt: str, context: str, conversation_id: str | None) -> str:
        """Generate a response using the OpenAI Responses API."""
        client = OpenAI(api_key=self.api_key)
        system_text = (
            "You are Harle, a concise assistant. "
            f"Current context: {context}. "
            "Answer directly and keep structure clear."
        )
        response = client.responses.create(
            model=self.model,
            input=[
                {"role": "system", "content": system_text},
                {"role": "user", "content": prompt},
            ],
        )
        return response.output_text.strip()


class EchoProvider:
    """Local fallback provider when no external LLM credentials are available."""

    def generate(self, *, prompt: str, context: str, conversation_id: str | None) -> str:
        """Return a deterministic placeholder response."""
        prefix = "[echo provider] OPENAI_API_KEY environment variable not set."
        return f"{prefix}\ncontext={context}\nmessage={prompt}"

