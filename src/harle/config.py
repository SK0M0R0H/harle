"""Runtime configuration for the Harle prototype."""

from __future__ import annotations

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables."""

    host: str = "127.0.0.1"
    port: int = 8000
    llm_provider: str = "openai"
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None


def load_settings() -> Settings:
    """Load settings from environment variables with sensible defaults."""
    port_text = os.getenv("HARLE_PORT", "8000")

    return Settings(
        host=os.getenv("HARLE_HOST", "127.0.0.1"),
        port=int(port_text),
        llm_provider=os.getenv("HARLE_LLM_PROVIDER", "openai"),
        llm_model=os.getenv("HARLE_LLM_MODEL", "gpt-4o-mini"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
    )

