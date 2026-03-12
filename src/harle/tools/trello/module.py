"""Trello tool module for read-only Trello data access."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from harle.tools.base import BaseToolModule
from harle.tools.trello.client import TrelloClient, clear_client, set_client
from harle.tools.trello.tools import trello_list_boards, trello_list_cards

if TYPE_CHECKING:
    from harle.connections.registry import ConnectionRegistry

logger = logging.getLogger(__name__)


class TrelloModule(BaseToolModule):
    """Read-only Trello module backed by a Trello connection."""

    @property
    def name(self) -> str:
        return "trello"

    @property
    def description(self) -> str:
        return "Read-only Trello board and card tools"

    async def initialize(
        self,
        config: dict,
        connections: "ConnectionRegistry | None" = None,
    ) -> None:
        if connections is None:
            raise RuntimeError(
                "TrelloModule requires a ConnectionRegistry with Trello configured."
            )

        connection_name = str(config.get("connection", "trello"))
        connection = connections.get(connection_name)
        http_client = connection.get_client()

        self._connection = connection
        self._client = TrelloClient(http_client=http_client)
        await self._client.open()
        set_client(self._client)

        logger.info("TrelloModule initialised (connection=%s).", connection_name)

    async def shutdown(self) -> None:
        clear_client()
        if hasattr(self, "_client"):
            await self._client.close()
        logger.info("TrelloModule shut down.")

    def get_tools(self) -> list[Callable]:
        return [trello_list_boards, trello_list_cards]

    async def health_check(self) -> bool:
        if not hasattr(self, "_connection"):
            return False
        status = await self._connection.health_check()
        return status.healthy
