"""Notion tool module for read-only Notion data access."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from harle.tools.base import BaseToolModule
from harle.tools.notion.client import NotionClient, clear_client, set_client
from harle.tools.notion.tools import (
    notion_get_database,
    notion_query_database,
    notion_read_page,
    notion_search,
)

if TYPE_CHECKING:
    from harle.connections.registry import ConnectionRegistry

logger = logging.getLogger(__name__)


class NotionModule(BaseToolModule):
    """Read-only Notion module backed by a Notion connection."""

    @property
    def name(self) -> str:
        return "notion"

    @property
    def description(self) -> str:
        return "Read-only Notion tools for searching pages and querying databases"

    async def initialize(
        self,
        config: dict,
        connections: "ConnectionRegistry | None" = None,
    ) -> None:
        if connections is None:
            raise RuntimeError(
                "NotionModule requires a ConnectionRegistry with Notion configured."
            )

        connection_name = str(config.get("connection", "notion"))
        connection = connections.get(connection_name)
        http_client = connection.get_client()

        self._connection = connection
        self._client = NotionClient(http_client=http_client)
        await self._client.open()
        set_client(self._client)

        logger.info("NotionModule initialised (connection=%s).", connection_name)

    async def shutdown(self) -> None:
        clear_client()
        if hasattr(self, "_client"):
            await self._client.close()
        logger.info("NotionModule shut down.")

    def get_tools(self) -> list[Callable]:
        return [
            notion_search,
            notion_read_page,
            notion_get_database,
            notion_query_database,
        ]

    async def health_check(self) -> bool:
        if not hasattr(self, "_connection"):
            return False
        status = await self._connection.health_check()
        return status.healthy
