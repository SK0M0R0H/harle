"""Tool registry factory — module discovery and registration.

Encapsulates the logic for deciding which tool modules to register
and initialising them with their dependencies.  The application
entrypoint calls :func:`build_tool_registry` and receives a
ready-to-use :class:`ToolRegistry` (or ``None`` when no modules
are available).

Adding a new tool module:
    1. Create the module package under ``harle/tools/<name>/``.
    2. Add a registration block in :func:`build_tool_registry`.
"""

from __future__ import annotations

import asyncio
import logging
import os
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Awaitable, TypeVar

from harle.connections import ConnectionRegistry, TavilyConnection, TrelloConnection
from harle.tools.permissions import OperationMode
from harle.tools.registry import ToolRegistry

if TYPE_CHECKING:
    from harle.dataset.reader import DatasetReader
    from harle.search.engine import SearchEngine

logger = logging.getLogger(__name__)

_T = TypeVar("_T")


def _run_coro_sync(coro: Awaitable[_T]) -> _T:
    """Run *coro* to completion, even when called inside a running event loop.

    When no loop is running (e.g. plain script), falls back to
    :func:`asyncio.run`.  When called from a sync frame inside a
    running loop (typical of uvicorn ``factory=True``), a dedicated
    thread with its own loop is used to avoid the "event loop is
    already running" error.
    """
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)

    with ThreadPoolExecutor(1) as pool:
        return pool.submit(asyncio.run, coro).result()


def build_tool_registry(
    *,
    search_engine: SearchEngine | None = None,
    dataset_reader: DatasetReader | None = None,
) -> ToolRegistry | None:
    """Create and populate a :class:`ToolRegistry` with available modules.

    Registers modules based on runtime availability of their
    dependencies:

    * **vault** — when a *search_engine* or *dataset_reader* is
      provided.  Exposes ``dataset_search`` and
      ``dataset_read_file``.
    * **web_search** — when the ``TAVILY_API_KEY`` environment
      variable is set.  Exposes ``search_web``, ``search_news``,
      and ``fetch_page``.
    * **trello** — when both ``TRELLO_API_KEY`` and
      ``TRELLO_API_TOKEN`` are set. Exposes ``trello_list_boards``
      and ``trello_list_cards``.

    Args:
        search_engine: Pre-configured search engine for dataset
            queries (enables vault ``dataset_search``).
        dataset_reader: Pre-configured dataset reader for file
            access (enables vault ``dataset_read_file``).

    Returns:
        A fully initialised :class:`ToolRegistry`, or ``None`` if
        no modules can be registered.
    """
    registry = ToolRegistry()
    has_modules = False

    connections = _build_connections()

    has_modules |= _register_vault(
        registry,
        search_engine=search_engine,
        dataset_reader=dataset_reader,
    )
    has_modules |= _register_web_search(registry, connections=connections)
    has_modules |= _register_trello(registry, connections=connections)

    if not has_modules:
        return None

    logger.info(
        "Tool registry ready: %d module(s), %d tool(s) — %s",
        len(registry.list_modules()),
        len(registry),
        registry.list_all_tools(),
    )
    return registry



def _build_connections() -> ConnectionRegistry | None:
    """Build the shared connection registry for enabled services."""
    tavily_key = os.getenv("TAVILY_API_KEY", "")
    trello_key = os.getenv("TRELLO_API_KEY", "")
    trello_token = os.getenv("TRELLO_API_TOKEN", "")

    if not tavily_key and not (trello_key and trello_token):
        return None

    registry = ConnectionRegistry()

    if tavily_key:
        _run_coro_sync(registry.register(TavilyConnection(), {"api_key": tavily_key}))
        logger.info("Connection registered: tavily")

    if trello_key and trello_token:
        _run_coro_sync(
            registry.register(
                TrelloConnection(),
                {"api_key": trello_key, "api_token": trello_token},
            )
        )
        logger.info("Connection registered: trello")

    return registry

# ── Per-module registration helpers ──────────────────────────────────


def _register_vault(
    registry: ToolRegistry,
    *,
    search_engine: SearchEngine | None,
    dataset_reader: DatasetReader | None,
) -> bool:
    """Register the vault module if a dataset backend is available."""
    if search_engine is None and dataset_reader is None:
        return False

    from harle.tools.vault.module import VaultModule

    module = VaultModule(
        search_engine=search_engine,
        dataset_reader=dataset_reader,
    )
    _run_coro_sync(module.initialize({}))
    registry.register_module(module, mode=OperationMode.AUTO)
    logger.info("Vault tool module registered.")
    return True


def _register_web_search(
    registry: ToolRegistry,
    *,
    connections: ConnectionRegistry | None,
) -> bool:
    """Register the web search module if ``TAVILY_API_KEY`` is set."""
    if connections is None or not connections.has("tavily"):
        return False

    from harle.tools.web_search.module import WebSearchModule

    module = WebSearchModule()
    _run_coro_sync(
        module.initialize({
            "provider": "tavily",
            "connection": "tavily",
        }, connections=connections)
    )
    registry.register_module(
        module,
        mode=OperationMode.AUTO,
        skill_names=["research"],
    )
    logger.info("Web Search tool module registered.")
    return True


def _register_trello(
    registry: ToolRegistry,
    *,
    connections: ConnectionRegistry | None,
) -> bool:
    """Register the Trello module if Trello credentials are configured."""
    if connections is None or not connections.has("trello"):
        return False

    from harle.tools.trello.module import TrelloModule

    module = TrelloModule()
    _run_coro_sync(
        module.initialize({
            "connection": "trello",
        }, connections=connections)
    )
    registry.register_module(
        module,
        mode=OperationMode.AUTO,
        skill_names=["read_sequence"],
    )
    logger.info("Trello tool module registered.")
    return True
