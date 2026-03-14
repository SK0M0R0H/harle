"""Tests for the Connections Layer core, Tavily, Trello, and Notion implementations."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from harle.connections import (
    BaseConnection,
    ConnectionConfigError,
    ConnectionRegistry,
    ConnectionStatus,
    NotionConnection,
    RateLimitConfig,
    RateLimiter,
    TavilyConnection,
    TrelloConnection,
)
from harle.connections.exceptions import ConnectionNotFound


class _DummyConnection(BaseConnection):
    def __init__(self) -> None:
        self.initialized = False
        self.shutdown_called = False

    @property
    def name(self) -> str:
        return "dummy"

    @property
    def service_display_name(self) -> str:
        return "Dummy"

    async def initialize(self, config: dict) -> None:
        self.initialized = True

    async def shutdown(self) -> None:
        self.shutdown_called = True

    async def health_check(self) -> ConnectionStatus:
        return ConnectionStatus(True, self.service_display_name, "ok")

    def get_client(self) -> httpx.AsyncClient:
        raise NotImplementedError


def _run(coro):
    return asyncio.run(coro)


class TestConnectionRegistry:
    def test_register_get_has_list(self) -> None:
        reg = ConnectionRegistry()
        conn = _DummyConnection()

        _run(reg.register(conn, {}))

        assert conn.initialized is True
        assert reg.has("dummy") is True
        assert reg.list() == ["dummy"]
        assert reg.get("dummy") is conn

    def test_get_missing_raises(self) -> None:
        reg = ConnectionRegistry()
        with pytest.raises(ConnectionNotFound, match=r"Available: \(none\)"):
            reg.get("missing")

    def test_health_check_all_and_shutdown_all(self) -> None:
        reg = ConnectionRegistry()
        conn = _DummyConnection()
        _run(reg.register(conn, {}))

        health = _run(reg.health_check_all())
        assert health["dummy"].healthy is True

        _run(reg.shutdown_all())
        assert conn.shutdown_called is True


class TestRateLimiter:
    def test_invalid_rate_raises(self) -> None:
        with pytest.raises(ValueError):
            RateLimiter(RateLimitConfig(tokens_per_second=0))

    def test_acquire_non_positive_is_noop(self) -> None:
        limiter = RateLimiter(RateLimitConfig(tokens_per_second=10))
        _run(limiter.acquire(0))


class TestTavilyConnection:
    def test_initialize_requires_api_key(self) -> None:
        conn = TavilyConnection()
        with pytest.raises(ConnectionConfigError):
            _run(conn.initialize({}))

    @patch("harle.connections.tavily.httpx.AsyncClient")
    def test_initialize_and_get_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        conn = TavilyConnection()
        _run(conn.initialize({"api_key": "k"}))

        assert conn.get_client() is mock_client
        mock_client_cls.assert_called_once()

    @patch("harle.connections.tavily.httpx.AsyncClient")
    def test_health_check_success(self, mock_client_cls: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        conn = TavilyConnection()
        _run(conn.initialize({"api_key": "k"}))
        status = _run(conn.health_check())

        assert status.healthy is True
        assert status.service_name == "Tavily"

    @patch("harle.connections.tavily.httpx.AsyncClient")
    def test_health_check_failure(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client.post.side_effect = RuntimeError("boom")
        mock_client_cls.return_value = mock_client

        conn = TavilyConnection()
        _run(conn.initialize({"api_key": "k"}))
        status = _run(conn.health_check())

        assert status.healthy is False
        assert "boom" in status.message

    @patch("harle.connections.tavily.httpx.AsyncClient")
    def test_shutdown_closes_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        conn = TavilyConnection()
        _run(conn.initialize({"api_key": "k"}))
        _run(conn.shutdown())

        mock_client.aclose.assert_awaited_once()


class TestTrelloConnection:
    def test_initialize_requires_api_key(self) -> None:
        conn = TrelloConnection()
        with pytest.raises(ConnectionConfigError):
            _run(conn.initialize({"api_token": "t"}))

    def test_initialize_requires_api_token(self) -> None:
        conn = TrelloConnection()
        with pytest.raises(ConnectionConfigError):
            _run(conn.initialize({"api_key": "k"}))

    @patch("harle.connections.trello.httpx.AsyncClient")
    def test_initialize_and_get_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        conn = TrelloConnection()
        _run(conn.initialize({"api_key": "k", "api_token": "t"}))

        assert conn.get_client() is mock_client
        mock_client_cls.assert_called_once()

    @patch("harle.connections.trello.httpx.AsyncClient")
    def test_health_check_success(self, mock_client_cls: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        conn = TrelloConnection()
        _run(conn.initialize({"api_key": "k", "api_token": "t"}))
        status = _run(conn.health_check())

        assert status.healthy is True
        assert status.service_name == "Trello"

    @patch("harle.connections.trello.httpx.AsyncClient")
    def test_health_check_failure(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = RuntimeError("boom")
        mock_client_cls.return_value = mock_client

        conn = TrelloConnection()
        _run(conn.initialize({"api_key": "k", "api_token": "t"}))
        status = _run(conn.health_check())

        assert status.healthy is False
        assert "boom" in status.message

    @patch("harle.connections.trello.httpx.AsyncClient")
    def test_shutdown_closes_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        conn = TrelloConnection()
        _run(conn.initialize({"api_key": "k", "api_token": "t"}))
        _run(conn.shutdown())

        mock_client.aclose.assert_awaited_once()


class TestNotionConnection:
    def test_initialize_requires_api_token(self) -> None:
        conn = NotionConnection()
        with pytest.raises(ConnectionConfigError):
            _run(conn.initialize({}))

    def test_initialize_requires_nonempty_token(self) -> None:
        conn = NotionConnection()
        with pytest.raises(ConnectionConfigError):
            _run(conn.initialize({"api_token": "  "}))

    @patch("harle.connections.notion.httpx.AsyncClient")
    def test_initialize_and_get_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        conn = NotionConnection()
        _run(conn.initialize({"api_token": "ntn_test"}))

        assert conn.get_client() is mock_client
        mock_client_cls.assert_called_once()

        call_kwargs = mock_client_cls.call_args[1]
        assert "api.notion.com" in call_kwargs["base_url"]
        assert "Bearer ntn_test" in call_kwargs["headers"]["Authorization"]
        assert "Notion-Version" in call_kwargs["headers"]

    @patch("harle.connections.notion.httpx.AsyncClient")
    def test_health_check_success(self, mock_client_cls: MagicMock) -> None:
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_cls.return_value = mock_client

        conn = NotionConnection()
        _run(conn.initialize({"api_token": "ntn_test"}))
        status = _run(conn.health_check())

        assert status.healthy is True
        assert status.service_name == "Notion"

    @patch("harle.connections.notion.httpx.AsyncClient")
    def test_health_check_failure(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client.get.side_effect = RuntimeError("boom")
        mock_client_cls.return_value = mock_client

        conn = NotionConnection()
        _run(conn.initialize({"api_token": "ntn_test"}))
        status = _run(conn.health_check())

        assert status.healthy is False
        assert "boom" in status.message

    @patch("harle.connections.notion.httpx.AsyncClient")
    def test_shutdown_closes_client(self, mock_client_cls: MagicMock) -> None:
        mock_client = AsyncMock()
        mock_client_cls.return_value = mock_client

        conn = NotionConnection()
        _run(conn.initialize({"api_token": "ntn_test"}))
        _run(conn.shutdown())

        mock_client.aclose.assert_awaited_once()

    def test_get_client_before_init_raises(self) -> None:
        conn = NotionConnection()
        with pytest.raises(RuntimeError, match="not been initialized"):
            conn.get_client()

    def test_name_and_display_name(self) -> None:
        conn = NotionConnection()
        assert conn.name == "notion"
        assert conn.service_display_name == "Notion"
