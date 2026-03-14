"""Notion API client for the import source.

Wraps an ``httpx.AsyncClient`` (from a NotionConnection) to provide
high-level methods for discovering and extracting Notion content.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

from harle.vault_imports.notion.converter import property_value_to_string

logger = logging.getLogger(__name__)

DEFAULT_MAX_BLOCK_DEPTH = 3
DEFAULT_PAGE_SIZE = 100


class NotionClientError(RuntimeError):
    """Raised when a Notion API call fails."""


class NotionImportClient:
    """Import-focused Notion API client.

    Args:
        http_client: An authenticated ``httpx.AsyncClient`` with
            ``base_url`` set to ``https://api.notion.com/v1``.
        config: Optional dict (e.g. from ``vault_imports.notion`` in
            config.yaml). Supported keys: ``max_block_depth`` (int),
            ``page_size`` (int). Defaults: 3 and 100.
    """

    def __init__(
        self,
        http_client: httpx.AsyncClient,
        config: dict | None = None,
    ) -> None:
        self._http = http_client
        cfg = config or {}
        self._max_block_depth = int(cfg.get("max_block_depth", DEFAULT_MAX_BLOCK_DEPTH))
        self._page_size = int(cfg.get("page_size", DEFAULT_PAGE_SIZE))

    # ------------------------------------------------------------------
    # Page discovery
    # ------------------------------------------------------------------

    async def search_all_pages(self) -> list[dict[str, Any]]:
        """Return every page accessible to the integration."""
        return await self._search_all(object_type="page")

    async def search_all_databases(self) -> list[dict[str, Any]]:
        """Return every database accessible to the integration."""
        return await self._search_all(object_type="database")

    async def search(
        self,
        query: str,
        object_type: str | None = None,
        page_size: int = 20,
    ) -> list[dict[str, Any]]:
        """Run a single-page search (for tool/agent use).

        Args:
            query: Search text.
            object_type: Optional ``"page"`` or ``"database"`` filter.
            page_size: Max results to return (default 20).

        Returns:
            Raw result items from the Notion API.
        """
        payload: dict[str, Any] = {"query": query, "page_size": min(page_size, self._page_size)}
        if object_type:
            payload["filter"] = {"value": object_type, "property": "object"}
        data = await self._post_json("/search", json=payload)
        return data.get("results", [])

    async def _search_all(
        self,
        object_type: str,
        query: str = "",
    ) -> list[dict[str, Any]]:
        """Paginate through ``POST /search`` for *object_type*."""
        results: list[dict[str, Any]] = []
        payload: dict[str, Any] = {
            "filter": {"value": object_type, "property": "object"},
            "page_size": self._page_size,
        }
        if query:
            payload["query"] = query

        while True:
            data = await self._post_json("/search", json=payload)
            results.extend(data.get("results", []))
            if not data.get("has_more"):
                break
            payload["start_cursor"] = data["next_cursor"]

        return results

    async def get_page(self, page_id: str) -> dict[str, Any]:
        """Retrieve a page object (metadata + property IDs)."""
        return await self._get_json(f"/pages/{page_id}")

    # ------------------------------------------------------------------
    # Blocks (page body content)
    # ------------------------------------------------------------------

    async def get_blocks(
        self,
        block_id: str,
        depth: int = 0,
    ) -> list[dict[str, Any]]:
        """Recursively retrieve block children.

        Args:
            block_id: Page or block ID whose children to fetch.
            depth: Current recursion depth (capped at ``MAX_BLOCK_DEPTH``).

        Returns:
            Flat-ish list of blocks with nested ``children`` lists.
        """
        blocks: list[dict[str, Any]] = []
        params: dict[str, Any] = {"page_size": self._page_size}

        while True:
            data = await self._get_json(
                f"/blocks/{block_id}/children",
                params=params,
            )
            for block in data.get("results", []):
                if block.get("has_children") and depth < self._max_block_depth:
                    child_id = block["id"]
                    block["children"] = await self.get_blocks(child_id, depth + 1)
                blocks.append(block)

            if not data.get("has_more"):
                break
            params["start_cursor"] = data["next_cursor"]

        return blocks

    # ------------------------------------------------------------------
    # Database operations
    # ------------------------------------------------------------------

    async def get_database(self, database_id: str) -> dict[str, Any]:
        """Retrieve a database object (schema / properties definition)."""
        return await self._get_json(f"/databases/{database_id}")

    async def query_database(
        self,
        database_id: str,
        filter_obj: dict | None = None,
        sorts: list[dict] | None = None,
        page_size: int = DEFAULT_PAGE_SIZE,
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query a database and return all matching page objects.

        Args:
            database_id: The database to query.
            filter_obj: Optional Notion filter object.
            sorts: Optional list of sort objects.
            page_size: Results per API page.
            max_pages: If set, stop after this many result pages.

        Returns:
            List of page objects (property IDs only, no values).
        """
        results: list[dict[str, Any]] = []
        payload: dict[str, Any] = {"page_size": min(page_size, self._page_size)}
        if filter_obj:
            payload["filter"] = filter_obj
        if sorts:
            payload["sorts"] = sorts

        pages_fetched = 0
        while True:
            data = await self._post_json(
                f"/databases/{database_id}/query",
                json=payload,
            )
            results.extend(data.get("results", []))
            pages_fetched += 1

            if not data.get("has_more"):
                break
            if max_pages is not None and pages_fetched >= max_pages:
                break
            payload["start_cursor"] = data["next_cursor"]

        return results

    async def get_page_property(
        self,
        page_id: str,
        property_id: str,
    ) -> dict[str, Any]:
        """Retrieve a single property value for a page.

        Paginates automatically for list-type properties (rich_text,
        title, relation, people with >25 items).
        """
        data = await self._get_json(
            f"/pages/{page_id}/properties/{property_id}",
        )

        prop_type = data.get("type", "")
        if prop_type in ("property_item",):
            return data

        if data.get("object") == "list":
            all_results = list(data.get("results", []))
            while data.get("has_more"):
                data = await self._get_json(
                    f"/pages/{page_id}/properties/{property_id}",
                    params={"start_cursor": data["next_cursor"]},
                )
                all_results.extend(data.get("results", []))
            data["results"] = all_results
        return data

    async def get_database_rows_with_properties(
        self,
        database_id: str,
        schema: dict[str, dict],
        filter_obj: dict | None = None,
        max_rows: int | None = None,
    ) -> list[dict[str, Any]]:
        """Query a database and resolve all property values per row.

        Two-step process required by Notion API 2022-06-28:
        1. ``query_database`` to get page IDs
        2. ``get_page_property`` per property per page

        Args:
            database_id: Database to query.
            schema: Schema dict from ``get_database()["properties"]``.
            filter_obj: Optional Notion filter.
            max_rows: Cap on total rows returned.

        Returns:
            List of dicts mapping column name to resolved value string.
        """
        max_pages = None
        if max_rows is not None:
            max_pages = (max_rows // self._page_size) + 1

        pages = await self.query_database(
            database_id,
            filter_obj=filter_obj,
            max_pages=max_pages,
        )

        if max_rows is not None:
            pages = pages[:max_rows]

        rows: list[dict[str, Any]] = []
        for page in pages:
            page_id = page["id"]
            row: dict[str, Any] = {"_page_id": page_id, "_url": page.get("url", "")}

            for col_name, col_info in schema.items():
                prop_id = col_info.get("id", "")
                col_type = col_info.get("type", "rich_text")
                if not prop_id:
                    continue
                try:
                    prop_data = await self.get_page_property(page_id, prop_id)
                    row[col_name] = _extract_property_value(col_type, prop_data)
                except NotionClientError:
                    logger.warning(
                        "Failed to fetch property %r for page %s",
                        col_name,
                        page_id,
                    )
                    row[col_name] = None

            rows.append(row)

        return rows

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------

    async def _get_json(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """GET *path* and return the parsed JSON body."""
        try:
            resp = await self._http.get(path, params=params)
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            raise NotionClientError(
                f"Notion API error (status={status}): {exc}"
            ) from exc
        except Exception as exc:
            raise NotionClientError(f"Notion request failed: {exc}") from exc

    async def _post_json(
        self,
        path: str,
        json: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """POST *path* with a JSON body and return the parsed response."""
        try:
            resp = await self._http.post(path, json=json or {})
            resp.raise_for_status()
            return resp.json()
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code if exc.response is not None else "?"
            raise NotionClientError(
                f"Notion API error (status={status}): {exc}"
            ) from exc
        except Exception as exc:
            raise NotionClientError(f"Notion request failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _extract_property_value(
    col_type: str,
    prop_data: dict[str, Any],
) -> Any:
    """Pull the actual value out of a property-item API response.

    The shape differs between scalar properties (which return the
    value inline) and list properties (which return ``object: "list"``).
    """
    if prop_data.get("object") == "list":
        results = prop_data.get("results", [])
        if col_type in ("title", "rich_text"):
            return results
        if col_type in ("relation", "people"):
            return results
        return results

    actual_type = prop_data.get("type", col_type)
    return prop_data.get(actual_type)
