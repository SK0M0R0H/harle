"""Dataset reader — loads and parses Markdown files from the user vault.

Walks the dataset directory, reads ``.md`` files, and extracts
frontmatter metadata alongside body content.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from harle.dataset.frontmatter import parse_frontmatter

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DatasetFile:
    """Parsed representation of a single Markdown file in the dataset.

    Attributes:
        relative_path: Path relative to the dataset root.
        title: Title extracted from frontmatter (or ``None``).
        tags: List of tags from frontmatter.
        context: Context scope from frontmatter.
        content: Body text (after frontmatter).
        raw_content: Full file content including frontmatter.
        raw_frontmatter: Parsed frontmatter dict.
    """

    relative_path: str
    title: str | None
    tags: list[str] = field(default_factory=list)
    context: str | None = None
    content: str = ""
    raw_content: str = ""
    raw_frontmatter: dict[str, Any] = field(default_factory=dict)


class DatasetReader:
    """Reads and parses Markdown files from a dataset directory.

    Args:
        dataset_path: Absolute path to the vault root directory.
    """

    def __init__(self, dataset_path: str) -> None:
        self.dataset_path = Path(dataset_path)

    def list_files(self) -> list[Path]:
        """Return sorted list of all ``.md`` files, excluding hidden directories.

        Returns:
            List of absolute paths to Markdown files.
        """
        if not self.dataset_path.exists():
            logger.warning("Dataset path does not exist: %s", self.dataset_path)
            return []

        results: list[Path] = []
        for path in sorted(self.dataset_path.rglob("*.md")):
            parts = path.relative_to(self.dataset_path).parts
            if any(part.startswith(".") for part in parts):
                continue
            results.append(path)
        return results

    def read_file(self, relative_path: str) -> DatasetFile:
        """Read and parse a single Markdown file.

        Args:
            relative_path: Path relative to the dataset root.

        Returns:
            Parsed :class:`DatasetFile`.

        Raises:
            FileNotFoundError: If the file does not exist.
            UnicodeDecodeError: If the file cannot be read as UTF-8.
        """
        full_path = self.dataset_path / relative_path
        raw_content = full_path.read_text(encoding="utf-8")
        metadata, body = parse_frontmatter(raw_content)

        return DatasetFile(
            relative_path=relative_path,
            title=metadata.get("title"),
            tags=metadata.get("tags", []) or [],
            context=metadata.get("context"),
            content=body,
            raw_content=raw_content,
            raw_frontmatter=metadata,
        )

    def read_all(self) -> list[DatasetFile]:
        """Read and parse every Markdown file in the dataset.

        Files that fail to parse (encoding errors, etc.) are skipped
        with a warning.

        Returns:
            List of parsed :class:`DatasetFile` objects.
        """
        files: list[DatasetFile] = []
        for path in self.list_files():
            rel = str(path.relative_to(self.dataset_path))
            try:
                files.append(self.read_file(rel))
            except (UnicodeDecodeError, OSError) as exc:
                logger.warning("Skipping %s: %s", rel, exc)
        return files
