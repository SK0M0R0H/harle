"""Tests for the Trello tool module."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from harle.connections import ConnectionRegistry, ConnectionStatus
from harle.tools.permissions import OperationMode
from harle.tools.registry import ToolRegistry
from harle.tools.trello.client import TrelloBoard, TrelloCard, clear_client, set_client
from harle.tools.trello.module import TrelloModule
from harle.tools.trello.tools import trello_list_boards, trello_list_cards


def _run(coro):
    return asyncio.get_event_loop().run_until_complete(coro)


class _StubConnection:
    def __init__(self, client: AsyncMock) -> None:
        self._client = client

    def get_client(self) -> AsyncMock:
        return self._client

    async def health_check(self) -> ConnectionStatus:
        return ConnectionStatus(
            healthy=True,
            service_name="Trello",
            message="ok",
        )


@pytest.fixture(autouse=True)
def _clean_module_client():
    clear_client()
    yield
    clear_client()


class TestTrelloModule:
    def test_initialize_requires_connections(self) -> None:
        module = TrelloModule()

        with pytest.raises(RuntimeError, match="ConnectionRegistry"):
            _run(module.initialize({}, connections=None))

    def test_initialize_success_and_health_shutdown(self) -> None:
        conn_registry = AsyncMock(spec=ConnectionRegistry)
        http_client = AsyncMock()
        conn_registry.get.return_value = _StubConnection(http_client)

        module = TrelloModule()
        _run(module.initialize({"connection": "trello"}, connections=conn_registry))

        assert _run(module.health_check()) is True
        _run(module.shutdown())

    def test_get_tools(self) -> None:
        module = TrelloModule()
        tool_names = [fn.__name__ for fn in module.get_tools()]
        assert tool_names == ["trello_list_boards", "trello_list_cards"]


class TestTrelloTools:
    def test_trello_list_boards_contract(self) -> None:
        fake_client = AsyncMock()
        fake_client.list_boards.return_value = [
            TrelloBoard(id="b1", name="Team", url="https://trello.com/b/1", closed=False),
        ]
        set_client(fake_client)

        payload = json.loads(_run(trello_list_boards()))
        assert "boards" in payload
        assert payload["boards"][0]["id"] == "b1"
        assert payload["boards"][0]["name"] == "Team"

    def test_trello_list_cards_contract(self) -> None:
        fake_client = AsyncMock()
        fake_client.list_cards.return_value = [
            TrelloCard(
                id="c1",
                name="Fix bug",
                url="https://trello.com/c/1",
                closed=False,
                id_list="l1",
                due=None,
            )
        ]
        set_client(fake_client)

        payload = json.loads(_run(trello_list_cards("board-1")))
        assert payload["board_id"] == "board-1"
        assert payload["cards"][0]["id"] == "c1"
        assert payload["cards"][0]["id_list"] == "l1"

    def test_trello_list_cards_requires_board_id(self) -> None:
        payload = json.loads(_run(trello_list_cards("  ")))
        assert payload["error"] is True


class TestTrelloRegistryExposure:
    def test_registry_registers_trello_tools_as_read(self) -> None:
        conn_registry = AsyncMock(spec=ConnectionRegistry)
        http_client = AsyncMock()
        conn_registry.get.return_value = _StubConnection(http_client)

        module = TrelloModule()
        _run(module.initialize({"connection": "trello"}, connections=conn_registry))

        registry = ToolRegistry()
        registry.register_module(module, mode=OperationMode.AUTO, skill_names=["read_sequence"])

        assert registry.get_module_for_tool("trello_list_boards") is module
        assert registry.get_module_for_tool("trello_list_cards") is module
        assert registry.check_tool_permission("trello_list_boards")["permission"] == "read"
        assert registry.check_tool_permission("trello_list_cards")["permission"] == "read"
