"""Runtime configuration for the Harle prototype."""

from __future__ import annotations

import os
from dataclasses import dataclass


PROVIDER_OPENAI = "openai"

@dataclass(frozen=True)
class Settings:
    """Application settings loaded from environment variables.

    Data-related paths (dataset_path, database_url) always reference
    external resources.  They must be configured per-user / per-deployment.
    """

    host: str = "127.0.0.1"
    port: int = 8000
    llm_provider: str = PROVIDER_OPENAI
    llm_model: str = "gpt-4o-mini"
    openai_api_key: str | None = None

    # External data paths — configured per user, never inside this repo
    dataset_path: str | None = None
    database_url: str | None = None


def load_settings() -> Settings:
    """Load settings from environment variables with sensible defaults.

    All data-related settings (HARLE_DATASET_PATH, DATABASE_URL) must be
    supplied by the user to point at their own vault and database instance.
    """
    port_text = os.getenv("HARLE_PORT", "8000")

    return Settings(
        host=os.getenv("HARLE_HOST", "127.0.0.1"),
        port=int(port_text),
        llm_provider=os.getenv("HARLE_LLM_PROVIDER", PROVIDER_OPENAI),
        llm_model=os.getenv("HARLE_LLM_MODEL", "gpt-4o-mini"),
        openai_api_key=os.getenv("OPENAI_API_KEY"),
        dataset_path=os.getenv("HARLE_DATASET_PATH"),
        database_url=os.getenv("DATABASE_URL"),
    )

