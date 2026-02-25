"""Base interface for all Harle tool modules.

Every tool module — whether it connects to an external API, runs local
scripts, or manages vault files — implements :class:`BaseToolModule`.

The module class groups related tool functions, manages their lifecycle
(initialisation, shutdown, health checks), and declares module identity.
Tool function metadata (name, description, parameter schema) lives on the
functions themselves and is introspected by the registry — the module does
not duplicate it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Callable

if TYPE_CHECKING:
    from harle.tools.constraints import ConstraintConfig


class BaseToolModule(ABC):
    """Contract every tool module must follow.

    Subclasses provide a unique *name*, a human-readable *description*,
    lifecycle hooks (``initialize`` / ``shutdown`` / ``health_check``), and
    a list of tool functions via ``get_tools``.

    Modules that interact with the local system (scripts, vault) should
    override ``default_constraints`` to provide a safety floor.  The
    registry merges these defaults with user config so that deployments
    are secure out of the box but remain customisable.

    Skills (Markdown files with domain knowledge) live in a ``skills/``
    subdirectory by convention; the registry knows where to look.  Which
    skill files are loaded is controlled by configuration, not by this
    class.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique module identifier (e.g. ``'trello'``, ``'web_search'``)."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable module description for logging and debugging."""
        ...

    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Set up clients, validate credentials, prepare state.

        Args:
            config: Module-specific configuration from ``config.yaml``.
        """
        ...

    @abstractmethod
    async def shutdown(self) -> None:
        """Clean up resources (close HTTP clients, flush buffers)."""
        ...

    @abstractmethod
    def get_tools(self) -> list[Callable]:
        """Return the tool functions this module provides.

        Each function must have type hints and a docstring.  The registry
        introspects these to build JSON schemas for the LLM.

        Returns:
            A list of callable tool functions.
        """
        ...

    def default_constraints(self) -> ConstraintConfig | None:
        """Return the module's recommended default constraints.

        Override this to provide a safety floor for modules that interact
        with the local system (filesystem, subprocesses, network).  The
        registry merges these defaults with user-provided config:
        user config fields **replace** defaults field-by-field; fields
        the user does not set keep the module's defaults.

        Returns ``None`` by default (no default constraints).  API-only
        modules (Trello, web search) typically don't need defaults
        because their damage surface is bounded by the external API.

        Returns:
            A :class:`ConstraintConfig` with recommended defaults, or
            ``None`` if the module has no default constraints.
        """
        return None

    async def health_check(self) -> bool:
        """Verify the module is operational (e.g. credentials valid).

        Returns ``True`` by default.  Override to add real checks.

        Returns:
            ``True`` if the module is healthy, ``False`` otherwise.
        """
        return True
