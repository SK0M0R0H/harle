"""Notion client wrapper for the tool module.

Provides higher-level methods that return tool-friendly data structures.
Reuses the converter from the import module for block-to-Markdown and
property-value rendering.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from harle.vault_imports.notion.client import NotionImportClient
from harle.vault_imports.notion.converter import (
    blocks_to_markdown,
    extract_database_title,
    extract_page_title,
    property_value_to_string,
    rich_text_to_plain,
)

logger = logging.getLogger(__name__)


class NotionToolClientError(RuntimeError):
    """Raised when a Notion tool-level operation fails."""


@dataclass
class NotionClient:
    """Tool-facing Notion client backed by a connection-managed HTTP client."""

    http_client: httpx.AsyncClient | None = None
    _api: NotionImportClient | None = field(default=None, init=False, repr=False)

    async def open(self) -> None:
        if self.http_client is None:
            raise RuntimeError("NotionClient requires a connection-managed HTTP client.")
        self._api = NotionImportClient(self.http_client)

    async def close(self) -> None:
        self._api = None

    # ------------------------------------------------------------------
    # Search
    # ------------------------------------------------------------------

    async def search(
        self,
        query: str,
        object_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Search Notion for pages and/or databases.

        Args:
            query: Search text.
            object_type: Optional ``"page"`` or ``"database"`` filter.

        Returns:
            List of result dicts with ``id``, ``title``, ``object``,
            ``url``.
        """
        self._ensure_open()
        assert self._api is not None

        items = await self._api.search(query, object_type=object_type, page_size=20)
        results: list[dict[str, Any]] = []
        for item in items:
            obj_type = item.get("object", "")
            title = _extract_title(item, obj_type)
            results.append({
                "id": item.get("id", ""),
                "title": title,
                "object": obj_type,
                "url": item.get("url", ""),
            })
        return results

    # ------------------------------------------------------------------
    # Read page
    # ------------------------------------------------------------------

    async def read_page(self, page_id: str) -> dict[str, Any]:
        """Fetch a page and render its content as Markdown.

        Returns:
            Dict with ``page_id``, ``title``, ``content_markdown``,
            ``url``.
        """
        self._ensure_open()
        assert self._api is not None

        page = await self._api.get_page(page_id)
        title = extract_page_title(page)
        blocks = await self._api.get_blocks(page_id)
        md = blocks_to_markdown(blocks)

        return {
            "page_id": page_id,
            "title": title,
            "content_markdown": md,
            "url": page.get("url", ""),
        }

    # ------------------------------------------------------------------
    # Database schema
    # ------------------------------------------------------------------

    async def get_database_schema(
        self,
        database_id: str,
    ) -> dict[str, Any]:
        """Retrieve a database's schema (column names and types).

        Returns:
            Dict with ``database_id``, ``title``, ``columns``.
        """
        self._ensure_open()
        assert self._api is not None

        db = await self._api.get_database(database_id)
        title = extract_database_title(db)

        columns = []
        for col_name, col_info in db.get("properties", {}).items():
            columns.append({
                "name": col_name,
                "type": col_info.get("type", "unknown"),
            })

        return {
            "database_id": database_id,
            "title": title,
            "columns": columns,
        }

    # ------------------------------------------------------------------
    # Query database
    # ------------------------------------------------------------------

    async def query_database(
        self,
        database_id: str,
        filter_obj: dict | None = None,
        sorts: list[dict] | None = None,
        max_rows: int = 50,
    ) -> dict[str, Any]:
        """Query a database with two-step property resolution.

        Args:
            database_id: The database to query.
            filter_obj: Optional Notion filter.
            sorts: Optional sort objects.
            max_rows: Max rows to return (default 50).

        Returns:
            Dict with ``database_id``, ``title``, ``columns``, ``rows``,
            ``total_rows``, ``truncated``.
        """
        self._ensure_open()
        assert self._api is not None

        db = await self._api.get_database(database_id)
        schema = db.get("properties", {})
        title = extract_database_title(db)

        rows_raw = await self._api.get_database_rows_with_properties(
            database_id,
            schema,
            filter_obj=filter_obj,
            max_rows=max_rows + 1,
        )

        truncated = len(rows_raw) > max_rows
        rows_raw = rows_raw[:max_rows]

        columns = [
            {"name": name, "type": info.get("type", "unknown")}
            for name, info in schema.items()
        ]

        rows = []
        for row in rows_raw:
            props: dict[str, str] = {}
            for col_name, col_info in schema.items():
                col_type = col_info.get("type", "rich_text")
                raw_val = row.get(col_name)
                props[col_name] = property_value_to_string(col_type, raw_val)
            rows.append({
                "page_id": row.get("_page_id", ""),
                "url": row.get("_url", ""),
                "properties": props,
            })

        return {
            "database_id": database_id,
            "title": title,
            "columns": columns,
            "rows": rows,
            "total_rows": len(rows),
            "truncated": truncated,
        }

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _ensure_open(self) -> None:
        if self._api is None:
            raise RuntimeError(
                "NotionClient is not open. Call `await client.open()` first."
            )


# ---------------------------------------------------------------------------
# Module-level active client (same pattern as Trello)
# ---------------------------------------------------------------------------

_active_client: NotionClient | None = None


def set_client(client: NotionClient) -> None:
    global _active_client
    _active_client = client


def get_client() -> NotionClient:
    if _active_client is None:
        raise RuntimeError(
            "Notion client is not initialised. "
            "Ensure NotionModule.initialize() has been called."
        )
    return _active_client


def clear_client() -> None:
    global _active_client
    _active_client = None


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _extract_title(item: dict[str, Any], obj_type: str) -> str:
    """Extract a title from a search result item."""
    if obj_type == "page":
        return extract_page_title(item)
    if obj_type == "database":
        title_arr = item.get("title", [])
        if isinstance(title_arr, list) and title_arr:
            return rich_text_to_plain(title_arr)
    return "Untitled"
