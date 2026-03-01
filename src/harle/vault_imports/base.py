"""Base interface and data types for the Import Module Layer.

Every import source implements :class:`BaseImportSource`. Sources produce
:class:`ImportItem` objects; the conversion pipeline turns them into
vault-ready Markdown; the Vault Writer writes files.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass  # ConnectionRegistry can be imported when connections layer exists


class ContentType(Enum):
    """Type of content an import item carries."""

    MARKDOWN = "markdown"
    IMAGE = "image"
    STRUCTURED = "structured"
    REFERENCE = "reference"


@dataclass
class AccessInfo:
    """How to access the source data at runtime via a tool module.

    Stored in the vault file's frontmatter so agents know which
    tool to call and with what parameters.
    """

    tool_module: str
    params: dict
    default_filter: dict | None = None


@dataclass
class ImportItem:
    """Intermediate representation of a single importable unit.

    Produced by a source's extract step. Consumed by the conversion
    pipeline and Vault Writer to create or update vault files.

    Items with content_type=REFERENCE produce lightweight vault
    files containing metadata, a summary, and access instructions
    instead of the full source content.
    """

    source_id: str
    title: str
    content: str
    content_type: ContentType
    suggested_path: str
    tags: list[str] = field(default_factory=list)
    context: str = "personal"
    metadata: dict = field(default_factory=dict)
    images: list[Path] = field(default_factory=list)
    access_info: AccessInfo | None = None


@dataclass
class ImportResult:
    """Summary of an import run for a single source."""

    source_name: str
    items_found: int
    items_imported: int
    items_skipped: int
    items_failed: int
    errors: list[str] = field(default_factory=list)
    created_paths: list[str] = field(default_factory=list)
    updated_paths: list[str] = field(default_factory=list)


class BaseImportSource(ABC):
    """Contract every import source must follow.

    Subclasses provide name, description, supported_modes,
    validate_input, and extract. initialize() and default_config()
    are optional; preview() defaults to calling extract().
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique source identifier (e.g. 'notion', 'miro')."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description for CLI help and logging."""
        ...

    async def initialize(
        self,
        config: dict,
        connections: object | None = None,
    ) -> None:
        """Set up the source with config and optional connections.

        Sources that support API mode should look up their
        connection from the connections registry. Sources that
        only support file mode can ignore the connections parameter.

        Called once at registration time.
        """
        pass

    @abstractmethod
    def supported_modes(self) -> list[str]:
        """Return the import modes this source supports.

        Common modes: 'file' (from an export file/directory),
        'api' (from a live API connection).
        """
        ...

    @abstractmethod
    async def validate_input(self, config: dict) -> list[str]:
        """Check whether the provided config is valid for import.

        Returns a list of validation errors (empty = valid).
        """
        ...

    @abstractmethod
    async def extract(self, config: dict) -> list[ImportItem]:
        """Extract data from the source and return ImportItems.

        Reads from the external system (file, API, directory)
        and produces a list of ImportItems ready for the pipeline.
        """
        ...

    async def preview(self, config: dict) -> list[ImportItem]:
        """Return items without writing — for user review.

        Default implementation calls extract(). Sources may override
        to provide a lighter preview (e.g. titles only, no content).
        """
        return await self.extract(config)

    def default_config(self) -> dict:
        """Return default configuration values for this source.

        Merged with user-provided config (user values take precedence).
        """
        return {}
