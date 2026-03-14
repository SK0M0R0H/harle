"""Vault imports (Import Module Layer) — sources, registry, pipeline, and vault writer.

External knowledge enters Harle through import sources. Each source
implements :class:`BaseImportSource`, produces :class:`ImportItem`
objects, and the shared pipeline and :class:`VaultWriter` produce
vault Markdown files.

Example::

    from harle.vault_imports import ImportRegistry, build_import_registry

    registry = build_import_registry()
    result = await registry.run_import(
        "dummy",
        {"context": "personal"},
        vault_path="/path/to/vault",
    )
"""

from harle.vault_imports.base import (
    AccessInfo,
    BaseImportSource,
    ContentType,
    ImportItem,
    ImportResult,
)
from harle.vault_imports.pipeline import ConvertedItem, run_pipeline
from harle.vault_imports.registry import ImportRegistry, ImportSourceNotFound
from harle.vault_imports.writer import VaultWriter, WriteResult

__all__ = [
    "AccessInfo",
    "BaseImportSource",
    "ContentType",
    "ConvertedItem",
    "ImportItem",
    "ImportResult",
    "ImportRegistry",
    "ImportSourceNotFound",
    "VaultWriter",
    "WriteResult",
    "run_pipeline",
    "build_import_registry",
]


def build_import_registry(
    config: dict | None = None,
    connections: object | None = None,
) -> ImportRegistry:
    """Build an ImportRegistry with available sources registered.

    Registers the dummy source unconditionally, and the Notion source
    when a ``"notion"`` connection is present in *connections*.

    Args:
        config: Optional config for vault_imports (e.g. from the
            ``vault_imports`` section of config.yaml). If ``None``,
            loaded from :func:`harle.config.get_vault_imports_config`.
        connections: Optional ``ConnectionRegistry``.  Sources that
            support API mode use it to obtain shared HTTP clients.

    Returns:
        A populated ImportRegistry ready for run_import().
    """
    import asyncio

    if config is None:
        from harle.config import get_vault_imports_config

        config = get_vault_imports_config()

    registry = ImportRegistry()
    from harle.vault_imports.dummy import DummyImportSource

    registry.register_source(DummyImportSource())

    _register_notion_source(registry, connections, config)

    return registry


def _register_notion_source(
    registry: ImportRegistry,
    connections: object | None,
    config: dict | None = None,
) -> bool:
    """Register the Notion import source if a Notion connection exists."""
    if connections is None:
        return False

    from harle.connections.registry import ConnectionRegistry

    if not isinstance(connections, ConnectionRegistry):
        return False
    if not connections.has("notion"):
        return False

    import asyncio

    from harle.vault_imports.notion import NotionImportSource

    notion_config = (config or {}).get("notion", {})
    source = NotionImportSource()
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(source.initialize(notion_config, connections=connections))
    else:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(1) as pool:
            pool.submit(
                asyncio.run,
                source.initialize(notion_config, connections=connections),
            ).result()

    registry.register_source(source)
    return True
