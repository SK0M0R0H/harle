"""Runtime configuration for the Harle prototype.

Resolution order (highest priority wins):
    1. Config file  (``config.yaml`` by default, override with ``HARLE_CONFIG_PATH``)
    2. Environment variables  (fallback when a key is absent from the file)
       - Process environment values win over ``.env`` values
       - ``.env`` is loaded at startup when present
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
from dotenv import find_dotenv, load_dotenv

logger = logging.getLogger(__name__)

PROVIDER_OPENAI = "openai"

DEFAULT_CONFIG_FILENAME = "config.yaml"
DEFAULT_DOTENV_FILENAME = ".env"

_DOTENV_LOADED = False


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
    HARLE_RUN_TIMEOUT_SECONDS: int | None = 60  # End-to-end orchestrator timeout

    # Run logging (vault logs/ directory)
    HARLE_RUN_LOG_STORE_CONTEXT: bool = False  # Store assembled context in logs (optional, for size/privacy)

    # Execution tracing (OpenTelemetry-based)
    HARLE_TRACING_VAULT_ENABLED: bool = True
    HARLE_TRACING_DB_ENABLED: bool = True
    HARLE_TRACING_MIN_STORAGE_LEVEL: str = "TRACE"
    # SSE streaming of trace events for ?debug=true on /run and /chat
    HARLE_TRACING_SSE_ENABLED: bool = False
    HARLE_TRACING_DEBUG_LEVEL: str = "STEP"


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


def _resolve_dotenv_path() -> Path | None:
    """Return the dotenv path if one should be loaded.

    Resolution order:
        1. ``HARLE_DOTENV_PATH`` when set
        2. The nearest ``.env`` discovered from the current working directory
    """
    dotenv_override = os.getenv("HARLE_DOTENV_PATH")
    if dotenv_override:
        return Path(dotenv_override)

    discovered = find_dotenv(filename=DEFAULT_DOTENV_FILENAME, usecwd=True)
    if discovered:
        return Path(discovered)
    return None


def load_environment(*, force: bool = False) -> None:
    """Load environment values from dotenv once without overriding process env.

    ``force=True`` can be used by tests to reload after changing cwd or env.
    """
    global _DOTENV_LOADED
    if _DOTENV_LOADED and not force:
        return

    dotenv_path = _resolve_dotenv_path()
    if dotenv_path is None:
        _DOTENV_LOADED = True
        return

    load_dotenv(dotenv_path=dotenv_path, override=False)
    logger.info("Loaded environment variables from %s", dotenv_path)
    _DOTENV_LOADED = True


def load_settings() -> Settings:
    """Build :class:`Settings` by merging config file, env vars, and defaults.

    Priority (highest to lowest):
        1. Values from the YAML config file
        2. Environment variables
        3. Dataclass defaults
    """
    load_environment()

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


def get_vault_imports_config() -> dict[str, Any]:
    """Return the ``vault_imports`` section from the config file.

    Used by :func:`harle.vault_imports.build_import_registry` to pass
    source-specific options (e.g. ``notion.max_block_depth``,
    ``notion.page_size``). Returns an empty dict if the section is
    missing or the config file is not loaded.
    """
    data = _load_yaml(_resolve_config_path())
    vault_imports = data.get("vault_imports")
    if isinstance(vault_imports, dict):
        return vault_imports
    return {}


# ---------------------------------------------------------------------------
# Search config (Phase 2+)
# ---------------------------------------------------------------------------

def _default_whoosh_index_path() -> str:
    """Default Whoosh index path following XDG Base Directory spec."""
    home = os.environ.get("HOME", os.path.expanduser("~"))
    return f"{home}/.local/share/harle/whoosh_index"


@dataclass(frozen=True)
class SearchConfig:
    """Search algorithm configuration (Phase 2 Whoosh + ranking).

    Read from the ``search`` key in config.yaml with env overrides
    for ``HARLE_SEARCH_ENGINE`` and ``HARLE_WHOOSH_INDEX_PATH``.
    """

    engine: str = "whoosh"
    max_results: int = 10
    min_score: float = 0.1
    whoosh_index_path: str = ""
    title_boost: float = 2.0
    tag_boost: float = 1.5
    bm25_weight: float = 0.40
    tag_match_weight: float = 0.20
    recency_weight: float = 0.15
    source_priority_weight: float = 0.15
    prior_run_weight: float = 0.10
    memory_min_confidence: float = 0.3
    max_memories: int = 10
    max_prior_runs: int = 5
    add_role_terms: bool = True
    match_tag_vocabulary: bool = True
    use_stemming: bool = True

    def __post_init__(self) -> None:
        if not self.whoosh_index_path:
            object.__setattr__(self, "whoosh_index_path", _default_whoosh_index_path())


def _get_search_config_raw() -> dict[str, Any]:
    """Return the ``search`` section from the config file (no env overrides)."""
    data = _load_yaml(_resolve_config_path())
    search = data.get("search")
    if isinstance(search, dict):
        return search
    return {}


def get_search_config() -> SearchConfig:
    """Return search configuration from config file and env overrides.

    Priority: env vars (HARLE_SEARCH_ENGINE, HARLE_WHOOSH_INDEX_PATH)
    override the ``search`` section in config.yaml. Missing keys use
    :class:`SearchConfig` defaults.
    """
    load_environment()
    raw = _get_search_config_raw()

    def _str(key: str, default: str) -> str:
        env_key = "HARLE_SEARCH_ENGINE" if key == "engine" else "HARLE_WHOOSH_INDEX_PATH"
        env_val = os.getenv(env_key)
        if env_val is not None:
            return env_val.strip()
        val = raw.get(key)
        return str(val).strip() if val is not None else default

    def _int(key: str, default: int) -> int:
        val = raw.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    def _float(key: str, default: float) -> float:
        val = raw.get(key)
        if val is None:
            return default
        try:
            return float(val)
        except (TypeError, ValueError):
            return default

    def _bool(key: str, default: bool) -> bool:
        val = raw.get(key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in {"1", "true", "yes"}
        return default

    engine = _str("engine", "whoosh")
    whoosh_index_path = _str("whoosh_index_path", _default_whoosh_index_path())
    if not whoosh_index_path:
        whoosh_index_path = _default_whoosh_index_path()

    expansion = raw.get("expansion")
    if not isinstance(expansion, dict):
        expansion = {}

    def _expansion_bool(key: str, default: bool) -> bool:
        val = expansion.get(key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in {"1", "true", "yes"}
        return default

    return SearchConfig(
        engine=engine,
        max_results=_int("max_results", 10),
        min_score=_float("min_score", 0.1),
        whoosh_index_path=whoosh_index_path,
        title_boost=_float("title_boost", 2.0),
        tag_boost=_float("tag_boost", 1.5),
        bm25_weight=_float("bm25_weight", 0.40),
        tag_match_weight=_float("tag_match_weight", 0.20),
        recency_weight=_float("recency_weight", 0.15),
        source_priority_weight=_float("source_priority_weight", 0.15),
        prior_run_weight=_float("prior_run_weight", 0.10),
        memory_min_confidence=_float("memory_min_confidence", 0.3),
        max_memories=_int("max_memories", 10),
        max_prior_runs=_int("max_prior_runs", 5),
        add_role_terms=_expansion_bool("add_role_terms", True),
        match_tag_vocabulary=_expansion_bool("match_tag_vocabulary", True),
        use_stemming=_expansion_bool("use_stemming", True),
    )
