"""Runtime configuration for the Harle prototype.

Resolution order (highest priority wins):
    1. Config file  (``config.yaml`` by default, override with ``HARLE_CONFIG_PATH``)
    2. Environment variables  (fallback when a key is absent from the file)
    3. Built-in defaults defined on the :class:`Settings` dataclass

Field names are identical to environment variable names, so the same
SCREAMING_CASE keys are used in the YAML config file, env vars, and
the dataclass — one canonical name everywhere, zero mapping code.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, fields
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

PROVIDER_OPENAI = "openai"

DEFAULT_CONFIG_FILENAME = "config.yaml"


@dataclass(frozen=True)
class Settings:
    """Application settings.

    Each field name is the canonical key used in:
        - the YAML config file
        - the corresponding environment variable
        - Python code (``settings.HARLE_HOST``, etc.)

    Data-related paths always reference external resources and must be
    configured per-user / per-deployment.
    """

    HARLE_HOST: str = "127.0.0.1"
    HARLE_PORT: int = 8000
    HARLE_LLM_PROVIDER: str = PROVIDER_OPENAI
    HARLE_LLM_MODEL: str = "gpt-4o-mini"

    # External data paths — configured per user, never inside this repo
    HARLE_DATASET_PATH: str | None = None
    DATABASE_URL: str | None = None

    # Agentic loop
    HARLE_MAX_ITERATIONS: int = 10  # Max turns for the Agents SDK Runner (tool-calling loop)

    # Run logging (vault logs/ directory)
    HARLE_RUN_LOG_STORE_CONTEXT: bool = False  # Store assembled context in logs (optional, for size/privacy)

    # Execution tracing (OpenTelemetry-based)
    HARLE_TRACING_VAULT_ENABLED: bool = True
    HARLE_TRACING_DB_ENABLED: bool = True
    HARLE_TRACING_MIN_STORAGE_LEVEL: str = "TRACE"


def _coerce(value: Any, target_type: type) -> Any:
    """Coerce *value* to *target_type* with basic ``str | None`` handling."""
    if value is None:
        return None

    origin = getattr(target_type, "__origin__", None)
    # Handle ``str | None`` (unions that include None)
    if origin is not None:
        args = [a for a in target_type.__args__ if a is not type(None)]
        if args:
            target_type = args[0]
        else:
            return value

    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is bool:
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes"}
        return bool(value)
    return value


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML config file and return its contents as a dict.

    Returns an empty dict when the file does not exist or cannot be parsed.
    """
    if not path.is_file():
        return {}

    try:
        with path.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh)
    except yaml.YAMLError:
        logger.warning("Failed to parse config file %s; ignoring it.", path)
        return {}

    if not isinstance(data, dict):
        logger.warning("Config file %s does not contain a mapping; ignoring it.", path)
        return {}

    logger.info("Loaded configuration from %s", path)
    return data


def _resolve_config_path() -> Path:
    """Return the path to the config file.

    Uses ``HARLE_CONFIG_PATH`` env var if set, otherwise falls back
    to ``config.yaml`` in the current working directory.
    """
    env_path = os.getenv("HARLE_CONFIG_PATH")
    if env_path:
        return Path(env_path)
    return Path(DEFAULT_CONFIG_FILENAME)


def load_settings() -> Settings:
    """Build :class:`Settings` by merging config file, env vars, and defaults.

    Priority (highest to lowest):
        1. Values from the YAML config file
        2. Environment variables
        3. Dataclass defaults
    """
    file_values = _load_yaml(_resolve_config_path())

    resolved: dict[str, Any] = {}
    for f in fields(Settings):
        # 1. Config file (primary)
        if f.name in file_values and file_values[f.name] is not None:
            resolved[f.name] = _coerce(file_values[f.name], f.type)
            continue

        # 2. Environment variable (fallback) — same key name, no mapping
        env_value = os.getenv(f.name)
        if env_value is not None:
            resolved[f.name] = _coerce(env_value, f.type)
            continue

        # 3. Built-in default (from the dataclass) — no action needed

    return Settings(**resolved)
