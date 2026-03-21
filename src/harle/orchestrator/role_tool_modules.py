"""Per-role tool module allowlists (vault, web_search, …).

Defaults are built-in. Users can override via:

1. ``HARLE_ROLE_TOOL_MODULES_PATH`` — path to a JSON file (see
   ``config/role_tool_modules.example.json``).
2. ``<HARLE_DATASET_PATH>/role_tool_modules.json`` when (1) is unset or missing.

Each JSON object maps role name → list of module names registered in
:class:`~harle.tools.registry.ToolRegistry`. Keys from the file are **merged**
over :data:`DEFAULT_ROLE_TOOL_MODULES` so partial overrides keep other roles.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Shipped defaults (also used when no config file exists or parse fails).
DEFAULT_ROLE_TOOL_MODULES: dict[str, list[str]] = {
    "assistant": ["vault", "web_search", "think"],
    "researcher": ["vault", "web_search", "think"],
    "secretary": ["vault", "trello", "notion", "think"],
    "specialist": ["vault", "think"],
    "writer": ["vault", "think"],
}

# Backwards-compatible alias for code/tests that import ROLE_TOOL_MODULES.
ROLE_TOOL_MODULES = DEFAULT_ROLE_TOOL_MODULES


def _coerce_modules(value: Any) -> list[str] | None:
    if not isinstance(value, list):
        return None
    out: list[str] = []
    for item in value:
        if isinstance(item, str) and item.strip():
            out.append(item.strip())
    return out


def load_role_tool_modules_json(path: Path) -> dict[str, list[str]]:
    """Load mapping from a JSON file. Raises on invalid structure."""
    text = path.read_text(encoding="utf-8")
    data = json.loads(text)
    if not isinstance(data, dict):
        raise ValueError("role_tool_modules JSON must be a top-level object")
    result: dict[str, list[str]] = {}
    for key, val in data.items():
        if not isinstance(key, str) or not key.strip():
            continue
        if key.strip().startswith("_"):
            continue
        modules = _coerce_modules(val)
        if modules is not None:
            result[key.strip().lower()] = modules
    return result


def merge_with_defaults(loaded: dict[str, list[str]]) -> dict[str, list[str]]:
    """Apply *loaded* on top of :data:`DEFAULT_ROLE_TOOL_MODULES`."""
    merged = dict(DEFAULT_ROLE_TOOL_MODULES)
    for role, modules in loaded.items():
        merged[role] = list(modules)
    return merged


def resolve_role_tool_modules(
    *,
    explicit_path: str | None,
    dataset_path: str | None,
) -> dict[str, list[str]]:
    """Resolve the effective role → module mapping.

    Tries, in order:

    #. File at *explicit_path* if set and it exists.
    #. ``<dataset_path>/role_tool_modules.json`` if *dataset_path* is set.
    #. :data:`DEFAULT_ROLE_TOOL_MODULES`.
    """
    candidates: list[Path] = []
    if explicit_path:
        candidates.append(Path(explicit_path).expanduser())
    if dataset_path:
        candidates.append(Path(dataset_path).expanduser() / "role_tool_modules.json")

    for path in candidates:
        if not path.is_file():
            continue
        try:
            loaded = load_role_tool_modules_json(path)
            merged = merge_with_defaults(loaded)
            logger.info(
                "Loaded role_tool_modules from %s (%d role overrides)",
                path,
                len(loaded),
            )
            return merged
        except OSError as exc:
            logger.warning("Could not read role_tool_modules file %s: %s", path, exc)
        except (json.JSONDecodeError, ValueError) as exc:
            logger.warning(
                "Invalid role_tool_modules JSON %s: %s; using defaults.",
                path,
                exc,
            )

    return dict(DEFAULT_ROLE_TOOL_MODULES)
