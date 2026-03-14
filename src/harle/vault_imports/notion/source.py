"""Notion import source — extract pages and databases via the Notion API."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

from harle.vault_imports.base import (
    BaseImportSource,
    ContentType,
    ImportItem,
)
from harle.vault_imports.notion.client import NotionClientError, NotionImportClient
from harle.vault_imports.notion.converter import (
    blocks_to_markdown,
    database_to_markdown_table,
    extract_database_title,
    extract_page_title,
    page_properties_to_metadata,
    property_value_to_string,
)

if TYPE_CHECKING:
    from harle.connections.registry import ConnectionRegistry

logger = logging.getLogger(__name__)


def _slugify(text: str, max_length: int = 80) -> str:
    """Turn *text* into a filesystem-friendly slug."""
    slug = text.lower().strip()
    slug = re.sub(r"[^\w\s-]", "", slug)
    slug = re.sub(r"[\s_]+", "_", slug)
    slug = slug.strip("_-")
    return slug[:max_length] or "untitled"


class NotionImportSource(BaseImportSource):
    """Import pages and databases from Notion via the API.

    Supports two modes:

    * ``api`` — full materialization: fetch all accessible pages and
      databases, convert to Markdown, write to the vault.
    * ``reference`` — (stub) copy metadata only and access full
      content online via the Notion tool. Not yet implemented.
    """

    def __init__(self) -> None:
        self._client: NotionImportClient | None = None

    @property
    def name(self) -> str:
        return "notion"

    @property
    def description(self) -> str:
        return "Import pages and databases from Notion"

    async def initialize(
        self,
        config: dict,
        connections: object | None = None,
    ) -> None:
        if connections is None:
            return
        registry: ConnectionRegistry = connections  # type: ignore[assignment]
        if not registry.has("notion"):
            return
        connection = registry.get("notion")
        self._client = NotionImportClient(connection.get_client(), config=config)

    def supported_modes(self) -> list[str]:
        return ["api", "reference"]

    async def validate_input(self, config: dict) -> list[str]:
        errors: list[str] = []
        mode = config.get("mode", "api")
        if mode not in self.supported_modes():
            errors.append(
                f"Unsupported mode '{mode}'. Supported: {self.supported_modes()}"
            )
        if mode == "reference":
            errors.append(
                "Reference mode is planned but not yet implemented. Use 'api' mode."
            )
        if mode == "api" and self._client is None:
            errors.append(
                "Notion connection is not configured. "
                "Set NOTION_API_TOKEN and ensure the connection is registered."
            )
        return errors

    async def extract(self, config: dict) -> list[ImportItem]:
        mode = config.get("mode", "api")
        if mode == "reference":
            raise NotImplementedError(
                "Reference mode is planned but not yet implemented."
            )
        return await self._extract_api(config)

    def default_config(self) -> dict:
        return {
            "mode": "api",
            "context": "personal",
            "target_dir": "knowledge/",
            "database_import_mode": "pages",
            "max_block_depth": 3,
            "page_size": 100,
        }

    # ------------------------------------------------------------------
    # API-mode extraction
    # ------------------------------------------------------------------

    async def _extract_api(self, config: dict) -> list[ImportItem]:
        """Full materialization: pages (Phase A) then databases (Phase B)."""
        assert self._client is not None

        context = config.get("context", "personal")
        page_ids_filter: list[str] | None = config.get("page_ids")
        database_ids_filter: list[str] | None = config.get("database_ids")
        db_import_mode = config.get("database_import_mode", "pages")

        items: list[ImportItem] = []

        items.extend(
            await self._extract_pages(context, page_ids_filter, database_ids_filter)
        )
        items.extend(
            await self._extract_databases(context, database_ids_filter, db_import_mode)
        )

        logger.info("Notion import extracted %d items.", len(items))
        return items

    # ------------------------------------------------------------------
    # Phase A: standalone pages
    # ------------------------------------------------------------------

    async def _extract_pages(
        self,
        context: str,
        page_ids_filter: list[str] | None,
        database_ids_filter: list[str] | None,
    ) -> list[ImportItem]:
        """Discover and convert standalone pages (not database rows)."""
        assert self._client is not None
        pages = await self._client.search_all_pages()

        items: list[ImportItem] = []
        for page in pages:
            page_id = page.get("id", "")
            parent = page.get("parent", {})
            parent_type = parent.get("type", "")

            if parent_type == "database_id":
                continue

            if page_ids_filter is not None and page_id not in page_ids_filter:
                continue

            try:
                title = extract_page_title(page)
                blocks = await self._client.get_blocks(page_id)
                body_md = blocks_to_markdown(blocks)

                items.append(
                    ImportItem(
                        source_id=f"notion-page-{page_id}",
                        title=title,
                        content=body_md,
                        content_type=ContentType.MARKDOWN,
                        suggested_path=f"notion/pages/{_slugify(title)}.md",
                        tags=["notion", "imported"],
                        context=context,
                        metadata={
                            "notion_id": page_id,
                            "notion_url": page.get("url", ""),
                            "created_time": page.get("created_time", ""),
                            "last_edited_time": page.get("last_edited_time", ""),
                            "parent_type": parent_type,
                        },
                    )
                )
            except NotionClientError:
                logger.warning("Failed to extract page %s, skipping.", page_id)

        return items

    # ------------------------------------------------------------------
    # Phase B: databases
    # ------------------------------------------------------------------

    async def _extract_databases(
        self,
        context: str,
        database_ids_filter: list[str] | None,
        db_import_mode: str,
    ) -> list[ImportItem]:
        """Discover databases and convert rows to ImportItems."""
        assert self._client is not None
        databases = await self._client.search_all_databases()

        items: list[ImportItem] = []
        for db in databases:
            db_id = db.get("id", "")
            if database_ids_filter is not None and db_id not in database_ids_filter:
                continue

            try:
                db_detail = await self._client.get_database(db_id)
                schema: dict[str, dict] = db_detail.get("properties", {})
                db_title = extract_database_title(db_detail)

                rows = await self._client.get_database_rows_with_properties(
                    db_id, schema
                )

                if db_import_mode == "table":
                    items.extend(
                        self._database_as_table(db_id, db_title, schema, rows, context)
                    )
                else:
                    items.extend(
                        await self._database_as_pages(
                            db_id, db_title, schema, rows, context
                        )
                    )
            except NotionClientError:
                logger.warning("Failed to extract database %s, skipping.", db_id)

        return items

    def _database_as_table(
        self,
        db_id: str,
        db_title: str,
        schema: dict[str, dict],
        rows: list[dict[str, Any]],
        context: str,
    ) -> list[ImportItem]:
        """One ImportItem per database — rendered as a Markdown table."""
        table_md = database_to_markdown_table(schema, rows)
        return [
            ImportItem(
                source_id=f"notion-db-{db_id}",
                title=db_title,
                content=table_md,
                content_type=ContentType.MARKDOWN,
                suggested_path=f"notion/databases/{_slugify(db_title)}.md",
                tags=["notion", "imported", "database"],
                context=context,
                metadata={
                    "notion_id": db_id,
                    "notion_type": "database",
                    "row_count": len(rows),
                },
            )
        ]

    async def _database_as_pages(
        self,
        db_id: str,
        db_title: str,
        schema: dict[str, dict],
        rows: list[dict[str, Any]],
        context: str,
    ) -> list[ImportItem]:
        """One ImportItem per database row — properties in frontmatter."""
        assert self._client is not None
        items: list[ImportItem] = []
        db_slug = _slugify(db_title)

        for row in rows:
            page_id = row.get("_page_id", "")
            meta = page_properties_to_metadata(row, schema)
            row_title = _row_title(row, schema)

            body_md = ""
            try:
                blocks = await self._client.get_blocks(page_id)
                body_md = blocks_to_markdown(blocks)
            except NotionClientError:
                logger.debug(
                    "No block content for database row %s.", page_id
                )

            items.append(
                ImportItem(
                    source_id=f"notion-dbrow-{page_id}",
                    title=row_title,
                    content=body_md,
                    content_type=ContentType.MARKDOWN,
                    suggested_path=(
                        f"notion/databases/{db_slug}/{_slugify(row_title)}.md"
                    ),
                    tags=["notion", "imported", "database-row"],
                    context=context,
                    metadata={
                        "notion_id": page_id,
                        "notion_url": row.get("_url", ""),
                        "notion_database": db_title,
                        "notion_database_id": db_id,
                        **meta,
                    },
                )
            )

        return items


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _row_title(row: dict[str, Any], schema: dict[str, dict]) -> str:
    """Extract the title column value from an enriched row."""
    for col_name, col_info in schema.items():
        if col_info.get("type") == "title":
            val = row.get(col_name)
            rendered = property_value_to_string("title", val)
            if rendered:
                return rendered
    return "Untitled"
