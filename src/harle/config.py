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
from typing import Any, get_args, get_type_hints

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

    # Model tiers — must be non-empty (see :class:`~harle.orchestrator.model_tier.ModelTierConfig`)
    HARLE_MODEL_CLASSIFIER: str = "gpt-4o-mini"
    HARLE_MODEL_PLANNER: str = "gpt-4o"
    HARLE_MODEL_EXECUTOR: str = "gpt-4o-mini"
    HARLE_COMPLEX_EXECUTION_TIER: str = "executor"

    # External data paths — configured per user, never inside this repo
    HARLE_DATASET_PATH: str | None = None
    # Path to JSON mapping role → tool module names (see config/role_tool_modules.example.json).
    # When unset, ``<HARLE_DATASET_PATH>/role_tool_modules.json`` is used if present.
    HARLE_ROLE_TOOL_MODULES_PATH: str | None = None
    DATABASE_URL: str | None = None

    # Agentic loop
    HARLE_MAX_ITERATIONS: int = 10  # Max turns for the Agents SDK Runner (tool-calling loop)
    HARLE_RUN_TIMEOUT_SECONDS: int | None = 60  # End-to-end orchestrator timeout

    # Level 3 plan-then-execute (orchestrator)
    HARLE_PLANNING_ENABLED: bool = True
    HARLE_PLANNING_MAX_TURNS: int = 5  # Max turns for planning agent (tool loop)
    HARLE_PLANNED_MAX_TURNS: int | None = None  # Execution max_turns when a plan exists; None = HARLE_MAX_ITERATIONS

    # Level 4 reflection and self-critique (orchestrator)
    HARLE_REFLECTION_ENABLED: bool = True
    HARLE_REFLECTION_MIN_TOOL_CALLS: int = 3
    # Comma-separated keywords and roles (YAML can use a string or list; list coerced in load_settings)
    HARLE_REFLECTION_TRIGGER_KEYWORDS: str = (
        "research,report,analysis,compare,evaluate,review,summarize"
    )
    HARLE_REFLECTION_TRIGGER_ROLES: str = "researcher"
    HARLE_REFLECTION_IMPROVEMENT_MAX_TURNS: int | None = None  # None = HARLE_MAX_ITERATIONS
    HARLE_THINK_TOOL_ENABLED: bool = True

    # Run logging (vault logs/ directory)
    HARLE_RUN_LOG_STORE_CONTEXT: bool = False  # Store assembled context in logs (optional, for size/privacy)

    # Execution tracing (OpenTelemetry-based)
    HARLE_TRACING_VAULT_ENABLED: bool = True
    HARLE_TRACING_DB_ENABLED: bool = True
    HARLE_TRACING_MIN_STORAGE_LEVEL: str = "TRACE"
    # SSE streaming of trace events for ?debug=true on /chat
    HARLE_TRACING_SSE_ENABLED: bool = False
    HARLE_TRACING_DEBUG_LEVEL: str = "STEP"


def _coerce(value: Any, target_type: Any) -> Any:
    """Coerce *value* to *target_type* with basic ``T | None`` handling.

    Expects a **resolved** type (e.g. from :func:`typing.get_type_hints`), not a
    string annotation. Unwraps ``Optional[T]`` / ``T | None`` using
    :func:`typing.get_args` so PEP 604 unions (``types.UnionType``) and
    ``typing.Union`` both coerce env/YAML strings to ``int``, etc.
    """
    if value is None:
        return None

    args = get_args(target_type)
    if args and type(None) in args:
        non_none = [a for a in args if a is not type(None)]
        if len(non_none) == 1:
            target_type = non_none[0]

    if target_type is int:
        return int(value)
    if target_type is float:
        return float(value)
    if target_type is bool:
        if isinstance(value, str):
            return value.lower() in {"1", "true", "yes"}
        return bool(value)
    if target_type is str:
        if isinstance(value, list):
            return ",".join(str(x).strip() for x in value if str(x).strip())
        return value if isinstance(value, str) else str(value)
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

    # Resolve ``str | None``-style annotations (PEP 563) to real types for _coerce.
    type_hints = get_type_hints(Settings)

    resolved: dict[str, Any] = {}
    for f in fields(Settings):
        field_type = type_hints[f.name]
        # 1. Config file (primary)
        if f.name in file_values and file_values[f.name] is not None:
            resolved[f.name] = _coerce(file_values[f.name], field_type)
            continue

        # 2. Environment variable (fallback) — same key name, no mapping
        env_value = os.getenv(f.name)
        if env_value is not None:
            resolved[f.name] = _coerce(env_value, field_type)
            continue

        # 3. Built-in default (from the dataclass) — no action needed

    return Settings(**resolved)


def get_role_tool_modules() -> dict[str, list[str]]:
    """Return per-role tool module allowlists (defaults + optional JSON).

    Resolution: :envvar:`HARLE_ROLE_TOOL_MODULES_PATH` file, then
    ``<HARLE_DATASET_PATH>/role_tool_modules.json``, then built-in defaults.
    """
    load_environment()
    settings = load_settings()
    from harle.orchestrator.role_tool_modules import resolve_role_tool_modules

    return resolve_role_tool_modules(
        explicit_path=settings.HARLE_ROLE_TOOL_MODULES_PATH,
        dataset_path=settings.HARLE_DATASET_PATH,
    )


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
    bm25_weight: float = 0.35
    tag_match_weight: float = 0.20
    recency_weight: float = 0.15
    source_priority_weight: float = 0.15
    memory_confidence_weight: float = 0.10
    prior_run_weight: float = 0.05
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
    defaults = SearchConfig()

    def _str(key: str, fallback: str) -> str:
        env_key = "HARLE_SEARCH_ENGINE" if key == "engine" else "HARLE_WHOOSH_INDEX_PATH"
        env_val = os.getenv(env_key)
        if env_val is not None:
            return env_val.strip()
        val = raw.get(key)
        return str(val).strip() if val is not None else fallback

    def _int(key: str, fallback: int) -> int:
        val = raw.get(key)
        if val is None:
            return fallback
        try:
            return int(val)
        except (TypeError, ValueError):
            return fallback

    def _float(key: str, fallback: float) -> float:
        val = raw.get(key)
        if val is None:
            return fallback
        try:
            return float(val)
        except (TypeError, ValueError):
            return fallback

    engine = _str("engine", defaults.engine)
    whoosh_index_path = _str("whoosh_index_path", defaults.whoosh_index_path)
    if not whoosh_index_path:
        whoosh_index_path = _default_whoosh_index_path()

    expansion = raw.get("expansion")
    if not isinstance(expansion, dict):
        expansion = {}

    def _expansion_bool(key: str, fallback: bool) -> bool:
        val = expansion.get(key)
        if val is None:
            return fallback
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in {"1", "true", "yes"}
        return fallback

    return SearchConfig(
        engine=engine,
        max_results=_int("max_results", defaults.max_results),
        min_score=_float("min_score", defaults.min_score),
        whoosh_index_path=whoosh_index_path,
        title_boost=_float("title_boost", defaults.title_boost),
        tag_boost=_float("tag_boost", defaults.tag_boost),
        bm25_weight=_float("bm25_weight", defaults.bm25_weight),
        tag_match_weight=_float("tag_match_weight", defaults.tag_match_weight),
        recency_weight=_float("recency_weight", defaults.recency_weight),
        source_priority_weight=_float("source_priority_weight", defaults.source_priority_weight),
        memory_confidence_weight=_float("memory_confidence_weight", defaults.memory_confidence_weight),
        prior_run_weight=_float("prior_run_weight", defaults.prior_run_weight),
        memory_min_confidence=_float("memory_min_confidence", defaults.memory_min_confidence),
        max_memories=_int("max_memories", defaults.max_memories),
        max_prior_runs=_int("max_prior_runs", defaults.max_prior_runs),
        add_role_terms=_expansion_bool("add_role_terms", defaults.add_role_terms),
        match_tag_vocabulary=_expansion_bool("match_tag_vocabulary", defaults.match_tag_vocabulary),
        use_stemming=_expansion_bool("use_stemming", defaults.use_stemming),
    )


# ---------------------------------------------------------------------------
# Chunking config (Best Practices §5)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ChunkingConfig:
    """Vault chunking for Whoosh indexing and retrieval."""

    enabled: bool = True
    knowledge_token_threshold: int = 2000
    contextual_enrichment: bool = True
    paragraph_max_tokens: int = 600
    max_chunks_per_file_in_results: int = 3


def get_chunking_config() -> ChunkingConfig:
    """Load ``chunking`` section from config.yaml (defaults if absent)."""
    load_environment()
    data = _load_yaml(_resolve_config_path())
    raw = data.get("chunking")
    if not isinstance(raw, dict):
        raw = {}

    def _bool(key: str, default: bool) -> bool:
        val = raw.get(key)
        if val is None:
            return default
        if isinstance(val, bool):
            return val
        if isinstance(val, str):
            return val.lower() in {"1", "true", "yes"}
        return default

    def _int(key: str, default: int) -> int:
        val = raw.get(key)
        if val is None:
            return default
        try:
            return int(val)
        except (TypeError, ValueError):
            return default

    return ChunkingConfig(
        enabled=_bool("enabled", True),
        knowledge_token_threshold=_int("knowledge_token_threshold", 2000),
        contextual_enrichment=_bool("contextual_enrichment", True),
        paragraph_max_tokens=_int("paragraph_max_tokens", 600),
        max_chunks_per_file_in_results=_int("max_chunks_per_file_in_results", 3),
    )
