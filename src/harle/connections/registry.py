"""Registry for configured external service connections."""

from __future__ import annotations

from harle.connections.base import BaseConnection, ConnectionStatus
from harle.connections.exceptions import ConnectionNotFound


class ConnectionRegistry:
    """Central catalog for available connections."""

    def __init__(self) -> None:
        self._connections: dict[str, BaseConnection] = {}

    async def register(self, connection: BaseConnection, config: dict) -> None:
        """Initialize and register a connection instance."""
        await connection.initialize(config)
        self._connections[connection.name] = connection

    def get(self, name: str) -> BaseConnection:
        """Fetch a connection by name or raise :class:`ConnectionNotFound`."""
        if name not in self._connections:
            available = ", ".join(self.list()) or "(none)"
            raise ConnectionNotFound(
                f"Connection '{name}' is not registered. Available: {available}"
            )
        return self._connections[name]

    def has(self, name: str) -> bool:
        return name in self._connections

    def list(self) -> list[str]:
        return list(self._connections.keys())

    async def health_check_all(self) -> dict[str, ConnectionStatus]:
        """Run health checks for all registered connections."""
        result: dict[str, ConnectionStatus] = {}
        for name, connection in self._connections.items():
            result[name] = await connection.health_check()
        return result

    async def shutdown_all(self) -> None:
        """Shutdown all registered connections."""
        for connection in self._connections.values():
            await connection.shutdown()

