"""Web Search tool module for the Harle Tool Module Layer.

Provides web search and page extraction capabilities using
Tavily via the shared Connections Layer.

All tools in this module are read-only — they retrieve information
from the web but never modify external data.  This makes the module
safe to run in ``auto`` mode.

Configuration example (``config.yaml``)::

    tool_modules:
      web_search:
        enabled: true
        connection: tavily
        max_results: 5
        mode: auto
        skills: [research]
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from harle.tools.base import BaseToolModule
from harle.tools.web_search.client import WebSearchClient, clear_client, set_client

if TYPE_CHECKING:
    from harle.connections.registry import ConnectionRegistry
from harle.tools.web_search.tools import fetch_page, search_news, search_web

logger = logging.getLogger(__name__)


class WebSearchModule(BaseToolModule):
    """Web search and page extraction via Tavily connection."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Web search and page content extraction"

    async def initialize(
        self,
        config: dict,
        connections: "ConnectionRegistry | None" = None,
    ) -> None:
        """Create and open the search client from config.

        Expected config keys:

        - ``connection`` — connection registry key (default ``"tavily"``).
        - ``max_results`` — default result count (default ``5``).

        Args:
            config: Module-specific configuration from ``config.yaml``.
        """
        if connections is None:
            raise RuntimeError(
                "WebSearchModule requires a ConnectionRegistry with Tavily configured."
            )

        connection_name = str(config.get("connection", "tavily"))
        connection = connections.get(connection_name)
        http_client = connection.get_client()

        max_results = int(config.get("max_results", 5))

        self._connection = connection
        self._client = WebSearchClient(
            provider="tavily",
            max_results=max_results,
            http_client=http_client,
        )
        await self._client.open()
        set_client(self._client)

        logger.info(
            "WebSearchModule initialised (connection=%s, max_results=%d).",
            connection_name, max_results,
        )

    async def shutdown(self) -> None:
        """Close the HTTP client and clear the module-level reference."""
        clear_client()
        if hasattr(self, "_client"):
            await self._client.close()
        logger.info("WebSearchModule shut down.")

    def get_tools(self) -> list[Callable]:
        return [search_web, search_news, fetch_page]

    async def health_check(self) -> bool:
        """Verify the underlying Tavily connection is healthy."""
        if not hasattr(self, "_connection"):
            return False
        status = await self._connection.health_check()
        return status.healthy
