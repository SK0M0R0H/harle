"""Vault tool module for the Harle Tool Module Layer.

Provides read-only access to the user's Markdown knowledge base
(dataset).  The module exposes two tools:

* ``dataset_search`` — keyword search over indexed files.
* ``dataset_read_file`` — read the full content of a specific file.

Both tools are read-only and safe to run in ``auto`` mode.

Configuration example (``config.yaml``)::

    tool_modules:
      vault:
        enabled: true
        mode: auto
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Callable

from harle.tools.base import BaseToolModule
from harle.tools.vault.tools import (
    clear_vault_accessors,
    dataset_read_file,
    dataset_search,
    set_dataset_reader,
    set_search_engine,
)

if TYPE_CHECKING:
    from harle.dataset.reader import DatasetReader
    from harle.search.engine import SearchEngine

logger = logging.getLogger(__name__)


class VaultModule(BaseToolModule):
    """Read-only access to the user's Markdown knowledge base.

    Args:
        search_engine: Pre-configured search engine for dataset
            queries.  May be ``None`` (dataset_search will return
            an error).
        dataset_reader: Pre-configured dataset reader for file
            access.  May be ``None`` (dataset_read_file will return
            an error).
    """

    def __init__(
        self,
        search_engine: SearchEngine | None = None,
        dataset_reader: DatasetReader | None = None,
    ) -> None:
        self._search_engine = search_engine
        self._dataset_reader = dataset_reader

    @property
    def name(self) -> str:
        return "vault"

    @property
    def description(self) -> str:
        return "Search and read files from the user's dataset"

    async def initialize(self, config: dict) -> None:
        """Expose search engine and dataset reader to tool functions.

        Args:
            config: Module-specific configuration (currently unused).
        """
        set_search_engine(self._search_engine)
        set_dataset_reader(self._dataset_reader)

        has_search = self._search_engine is not None
        has_reader = self._dataset_reader is not None
        logger.info(
            "VaultModule initialised (search=%s, reader=%s).",
            has_search, has_reader,
        )

    async def shutdown(self) -> None:
        """Clear module-level references."""
        clear_vault_accessors()
        logger.info("VaultModule shut down.")

    def get_tools(self) -> list[Callable]:
        return [dataset_search, dataset_read_file]

    async def health_check(self) -> bool:
        """Check that at least one backend is available."""
        return (
            self._search_engine is not None
            or self._dataset_reader is not None
        )
