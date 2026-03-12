"""Core contracts for the Connections Layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import httpx


@dataclass(frozen=True)
class ConnectionStatus:
    """Result of a connection health check."""

    healthy: bool
    service_name: str
    message: str = ""
    latency_ms: float | None = None


class BaseConnection(ABC):
    """Contract that every external service connection must implement."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique connection identifier (e.g. ``tavily``)."""

    @property
    @abstractmethod
    def service_display_name(self) -> str:
        """Human-readable service name for logging and CLI output."""

    @abstractmethod
    async def initialize(self, config: dict) -> None:
        """Set up the authenticated client using the provided config."""

    @abstractmethod
    async def shutdown(self) -> None:
        """Close clients and release resources."""

    @abstractmethod
    async def health_check(self) -> ConnectionStatus:
        """Verify the service is reachable and credentials are valid."""

    @abstractmethod
    def get_client(self) -> httpx.AsyncClient:
        """Return the authenticated HTTP client for this service."""

