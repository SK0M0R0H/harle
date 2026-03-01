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


def build_import_registry(config: dict | None = None) -> ImportRegistry:
    """Build an ImportRegistry with the dummy source registered.

    No other sources are registered. Call register_source() to add
    more, or extend this function when new sources exist.

    Args:
        config: Optional global config (e.g. from config.yaml).
            Not used by the dummy source; real sources will receive
            it in initialize() when wired at app startup.

    Returns:
        A populated ImportRegistry ready for run_import().
    """
    registry = ImportRegistry()
    from harle.vault_imports.dummy import DummyImportSource

    registry.register_source(DummyImportSource())
    return registry
