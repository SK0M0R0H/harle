"""Vault Writer — write converted import items to the vault.

Shared write logic for the Import Module Layer: creates directories,
writes Markdown files, and applies the chosen strategy for existing files.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

from harle.vault_imports.pipeline import ConvertedItem

logger = logging.getLogger(__name__)


@dataclass
class WriteResult:
    """Result of writing converted items to the vault."""

    created: int = 0
    updated: int = 0
    skipped: int = 0
    failed: int = 0
    created_paths: list[str] = field(default_factory=list)
    updated_paths: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


class VaultWriter:
    """Writes converted Markdown items to the vault filesystem.

    Handles directory creation, path validation (within vault),
    and strategy-based handling of existing files.
    """

    def __init__(self, vault_path: Path | str) -> None:
        """Initialize with the vault root path.

        Args:
            vault_path: Absolute or resolved path to the vault root.
        """
        self._vault_root = Path(vault_path).resolve()

    def write_items(
        self,
        items: list[ConvertedItem],
        strategy: str = "skip_existing",
    ) -> WriteResult:
        """Write converted items to the vault.

        Args:
            items: Converted Markdown items ready for writing.
            strategy: How to handle existing files:
                - 'skip_existing': do not overwrite (default)
                - 'update_changed': overwrite if content differs
                - 'force': always overwrite

        Returns:
            WriteResult with counts and paths for created, updated, skipped.
        """
        result = WriteResult()
        for item in items:
            try:
                path = self._vault_root / item.relative_path
                if not self._path_inside_vault(path):
                    result.errors.append(
                        f"Path outside vault: {item.relative_path}"
                    )
                    result.failed += 1
                    continue
                path.parent.mkdir(parents=True, exist_ok=True)
                if path.exists():
                    existing = path.read_text(encoding="utf-8")
                    if strategy == "skip_existing":
                        result.skipped += 1
                        continue
                    if strategy == "update_changed" and existing == item.content:
                        result.skipped += 1
                        continue
                    path.write_text(item.content, encoding="utf-8")
                    result.updated += 1
                    result.updated_paths.append(item.relative_path)
                    logger.debug("Updated vault file: %s", item.relative_path)
                else:
                    path.write_text(item.content, encoding="utf-8")
                    result.created += 1
                    result.created_paths.append(item.relative_path)
                    logger.debug("Created vault file: %s", item.relative_path)
            except OSError as e:
                result.failed += 1
                result.errors.append(f"{item.relative_path}: {e}")
                logger.warning("Failed to write %s: %s", item.relative_path, e)
        return result

    def _path_inside_vault(self, path: Path) -> bool:
        """Return True if path is under the vault root."""
        try:
            path.resolve().relative_to(self._vault_root)
            return True
        except ValueError:
            return False
