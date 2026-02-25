"""Web Search tool module for the Harle Tool Module Layer.

Provides web search and page extraction capabilities using an
external search API (Tavily by default, with support for Bing and
SearXNG).

All tools in this module are read-only — they retrieve information
from the web but never modify external data.  This makes the module
safe to run in ``auto`` mode.

Configuration example (``config.yaml``)::

    tool_modules:
      web_search:
        enabled: true
        provider: tavily
        api_key: ${TAVILY_API_KEY}
        max_results: 5
        timeout_seconds: 30
        mode: auto
        skills: [research]
"""

from __future__ import annotations

import logging
from typing import Callable

from harle.tools.base import BaseToolModule
from harle.tools.web_search.client import WebSearchClient, clear_client, set_client
from harle.tools.web_search.tools import fetch_page, search_news, search_web

logger = logging.getLogger(__name__)


class WebSearchModule(BaseToolModule):
    """Web search and page extraction via Tavily / Bing / SearXNG."""

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return "Web search and page content extraction"

    async def initialize(self, config: dict) -> None:
        """Create and open the search client from config.

        Expected config keys:

        - ``provider`` — ``"tavily"`` (default), ``"bing"``, or
          ``"searxng"``.
        - ``api_key`` — provider API key.
        - ``max_results`` — default result count (default ``5``).
        - ``timeout_seconds`` — HTTP timeout (default ``30``).

        Args:
            config: Module-specific configuration from ``config.yaml``.
        """
        provider = config.get("provider", "tavily")
        api_key = config.get("api_key", "")
        max_results = config.get("max_results", 5)
        timeout = config.get("timeout_seconds", 30)

        self._client = WebSearchClient(
            provider=provider,
            api_key=api_key,
            max_results=max_results,
            timeout=float(timeout),
        )
        await self._client.open()
        set_client(self._client)

        logger.info(
            "WebSearchModule initialised (provider=%s, max_results=%d).",
            provider, max_results,
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
        """Verify the search provider accepts our credentials."""
        if not hasattr(self, "_client"):
            return False
        return await self._client.verify_credentials()
