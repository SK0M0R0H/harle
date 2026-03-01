"""Import Registry — discover, register, and run import sources.

Central catalog of import sources. run_import() runs the full pipeline:
validate → extract → convert → write (unless dry_run).
"""

from __future__ import annotations

import logging
from pathlib import Path

from harle.vault_imports.base import BaseImportSource, ImportResult
from harle.vault_imports.pipeline import run_pipeline
from harle.vault_imports.writer import VaultWriter, WriteResult

logger = logging.getLogger(__name__)


class ImportSourceNotFound(Exception):
    """Raised when a requested import source is not registered."""


class ImportRegistry:
    """Central catalog of import sources and pipeline runner."""

    def __init__(self) -> None:
        self._sources: dict[str, BaseImportSource] = {}

    def register_source(self, source: BaseImportSource) -> None:
        """Register a source and index it by name."""
        self._sources[source.name] = source

    def get_source(self, name: str) -> BaseImportSource:
        """Return a registered source by name."""
        if name not in self._sources:
            raise ImportSourceNotFound(
                f"Import source '{name}' is not registered. "
                f"Available: {', '.join(self.list_sources())}"
            )
        return self._sources[name]

    def list_sources(self) -> list[str]:
        """Return names of all registered sources."""
        return list(self._sources.keys())

    async def run_import(
        self,
        source_name: str,
        config: dict,
        vault_path: Path | str,
        dry_run: bool = False,
    ) -> ImportResult:
        """Execute the full import pipeline for a source.

        Steps:
        1. Look up the source
        2. Merge default config with user config
        3. Validate input
        4. Extract items (or preview if dry_run)
        5. Run conversion pipeline
        6. If not dry_run: write to vault via VaultWriter
        7. Return ImportResult summary
        """
        source = self.get_source(source_name)
        merged = {**source.default_config(), **config}
        errors = await source.validate_input(merged)
        if errors:
            return ImportResult(
                source_name=source_name,
                items_found=0,
                items_imported=0,
                items_skipped=0,
                items_failed=0,
                errors=errors,
            )
        if dry_run:
            items = await source.preview(merged)
        else:
            items = await source.extract(merged)
        items_found = len(items)
        target_dir = merged.get("target_dir", "knowledge/")
        converted = run_pipeline(items, source_name, target_dir=target_dir)
        if dry_run:
            return ImportResult(
                source_name=source_name,
                items_found=items_found,
                items_imported=0,
                items_skipped=0,
                items_failed=0,
                created_paths=[c.relative_path for c in converted],
            )
        writer = VaultWriter(vault_path)
        strategy = merged.get("strategy", "skip_existing")
        write_result = writer.write_items(converted, strategy=strategy)
        return _import_result_from_write(
            source_name=source_name,
            items_found=items_found,
            write_result=write_result,
        )


def _import_result_from_write(
    source_name: str,
    items_found: int,
    write_result: WriteResult,
) -> ImportResult:
    """Build ImportResult from pipeline counts and WriteResult."""
    return ImportResult(
        source_name=source_name,
        items_found=items_found,
        items_imported=write_result.created + write_result.updated,
        items_skipped=write_result.skipped,
        items_failed=write_result.failed,
        errors=write_result.errors,
        created_paths=write_result.created_paths,
        updated_paths=write_result.updated_paths,
    )
