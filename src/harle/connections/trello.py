"""Trello connection implementation."""

from __future__ import annotations

import time

import httpx

from harle.connections.base import BaseConnection, ConnectionStatus
from harle.connections.exceptions import ConnectionConfigError


class TrelloConnection(BaseConnection):
    """Shared Trello API client/credentials for module consumers."""

    def __init__(self) -> None:
        self._client: httpx.AsyncClient | None = None

    @property
    def name(self) -> str:
        return "trello"

    @property
    def service_display_name(self) -> str:
        return "Trello"

    async def initialize(self, config: dict) -> None:
        api_key = (config.get("api_key") or "").strip()
        if not api_key:
            raise ConnectionConfigError("Trello connection requires 'api_key'.")

        api_token = (config.get("api_token") or "").strip()
        if not api_token:
            raise ConnectionConfigError("Trello connection requires 'api_token'.")

        timeout = float(config.get("timeout_seconds", 30))
        self._client = httpx.AsyncClient(
            base_url="https://api.trello.com/1",
            timeout=timeout,
            params={"key": api_key, "token": api_token},
        )

    async def shutdown(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    async def health_check(self) -> ConnectionStatus:
        if self._client is None:
            return ConnectionStatus(
                healthy=False,
                service_name=self.service_display_name,
                message="Connection is not initialized.",
            )

        start = time.perf_counter()
        try:
            response = await self._client.get("/members/me/boards", params={"limit": 1})
            response.raise_for_status()
        except Exception as exc:
            latency = (time.perf_counter() - start) * 1000
            return ConnectionStatus(
                healthy=False,
                service_name=self.service_display_name,
                message=str(exc),
                latency_ms=latency,
            )

        latency = (time.perf_counter() - start) * 1000
        return ConnectionStatus(
            healthy=True,
            service_name=self.service_display_name,
            message="Connection healthy.",
            latency_ms=latency,
        )

    def get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Trello connection has not been initialized.")
        return self._client
