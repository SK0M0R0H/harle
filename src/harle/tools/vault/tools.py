"""Tool functions for the Vault module.

Provides dataset search and file reading capabilities, allowing the
agent to discover and read files from the user's knowledge base during
multi-step reasoning.

All functions return JSON strings.  Permission attributes are set as
function-level attributes after each definition.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from harle.dataset.reader import DatasetReader
    from harle.search.engine import SearchEngine

# ---------------------------------------------------------------------------
# Module-level accessors (set by VaultModule.initialize)
# ---------------------------------------------------------------------------

_active_search_engine: SearchEngine | None = None
_active_dataset_reader: DatasetReader | None = None


def set_search_engine(engine: SearchEngine | None) -> None:
    """Set the module-level search engine (called by VaultModule)."""
    global _active_search_engine
    _active_search_engine = engine


def get_search_engine() -> SearchEngine | None:
    """Return the active search engine, or ``None`` if not configured."""
    return _active_search_engine


def set_dataset_reader(reader: DatasetReader | None) -> None:
    """Set the module-level dataset reader (called by VaultModule)."""
    global _active_dataset_reader
    _active_dataset_reader = reader


def get_dataset_reader() -> DatasetReader | None:
    """Return the active dataset reader, or ``None`` if not configured."""
    return _active_dataset_reader


def clear_vault_accessors() -> None:
    """Remove module-level references (called on shutdown)."""
    global _active_search_engine, _active_dataset_reader
    _active_search_engine = None
    _active_dataset_reader = None


# ---------------------------------------------------------------------------
# Tool functions
# ---------------------------------------------------------------------------


async def dataset_search(
    query: str,
    max_results: int = 5,
) -> str:
    """Search the user's dataset (knowledge base) for relevant files.

    Use this tool when you need to find information in the user's
    knowledge base — notes, documents, project files, and other
    Markdown files stored in the vault.  Results include file paths
    you can then read with dataset_read_file.

    Args:
        query: The search query.  Use specific keywords for better
            results.
        max_results: Maximum number of results to return (1–10).
            Defaults to 5.

    Returns:
        JSON string with ``query`` and a ``results`` list.  Each
        result has ``file_path``, ``title``, ``score``, ``tags``,
        and ``snippet``.
    """
    engine = get_search_engine()
    if engine is None:
        return json.dumps({
            "query": query,
            "results": [],
            "error": "Dataset search is not configured.",
        }, ensure_ascii=False)

    from harle.search.types import SearchQuery

    max_results = max(1, min(max_results, 10))
    sq = SearchQuery(query=query, max_results=max_results)
    results = engine.search(sq).file_results

    payload: dict = {"query": query, "results": []}
    for r in results:
        entry: dict = {
            "file_path": r.file_path,
            "title": r.title,
            "score": round(r.score, 4),
        }
        if r.tags:
            entry["tags"] = r.tags
        if r.snippet:
            entry["snippet"] = r.snippet
        payload["results"].append(entry)
    payload["total"] = len(results)
    return json.dumps(payload, ensure_ascii=False)


dataset_search.permission = "read"  # type: ignore[attr-defined]
dataset_search.requires_approval = False  # type: ignore[attr-defined]


async def dataset_read_file(file_path: str) -> str:
    """Read the full content of a specific file from the user's dataset.

    Use this tool when you know the exact file path and want to read
    its complete content — for example, after finding a relevant file
    via dataset_search.

    Args:
        file_path: The vault-relative path of the file to read
            (e.g. ``"knowledge/work/architecture.md"``).

    Returns:
        JSON string with ``file_path``, ``title``, ``tags``,
        ``context``, and ``content``.  If the file does not exist,
        returns an error description in the ``content`` field.
    """
    reader = get_dataset_reader()
    if reader is None:
        return json.dumps({
            "file_path": file_path,
            "content": "Dataset reader is not configured.",
            "error": True,
        }, ensure_ascii=False)

    try:
        df = reader.read_file(file_path)
        payload: dict = {
            "file_path": file_path,
            "title": df.title or file_path,
            "content": df.content,
        }
        if df.tags:
            payload["tags"] = df.tags
        if df.context:
            payload["context"] = df.context
        return json.dumps(payload, ensure_ascii=False)
    except FileNotFoundError:
        return json.dumps({
            "file_path": file_path,
            "content": f"File not found: {file_path}",
            "error": True,
        }, ensure_ascii=False)
    except Exception as exc:
        return json.dumps({
            "file_path": file_path,
            "content": f"Failed to read file: {exc}",
            "error": True,
        }, ensure_ascii=False)


dataset_read_file.permission = "read"  # type: ignore[attr-defined]
dataset_read_file.requires_approval = False  # type: ignore[attr-defined]
