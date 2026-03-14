"""Tests for the Notion tool module."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock

import pytest

from harle.connections import ConnectionRegistry, ConnectionStatus
from harle.tools.notion.client import NotionClient, clear_client, set_client
from harle.tools.notion.module import NotionModule
from harle.tools.notion.tools import (
    notion_get_database,
    notion_query_database,
    notion_read_page,
    notion_search,
)
from harle.tools.permissions import OperationMode
from harle.tools.registry import ToolRegistry


def _run(coro):
    return asyncio.run(coro)


class _StubConnection:
    def __init__(self, client: AsyncMock) -> None:
        self._client = client

    def get_client(self) -> AsyncMock:
        return self._client

    async def health_check(self) -> ConnectionStatus:
        return ConnectionStatus(
            healthy=True,
            service_name="Notion",
            message="ok",
        )


@pytest.fixture(autouse=True)
def _clean_module_client():
    clear_client()
    yield
    clear_client()


class TestNotionModule:
    def test_initialize_requires_connections(self) -> None:
        module = NotionModule()

        with pytest.raises(RuntimeError, match="ConnectionRegistry"):
            _run(module.initialize({}, connections=None))

    def test_initialize_success_and_health_shutdown(self) -> None:
        conn_registry = AsyncMock(spec=ConnectionRegistry)
        http_client = AsyncMock()
        conn_registry.get.return_value = _StubConnection(http_client)

        module = NotionModule()
        _run(module.initialize({"connection": "notion"}, connections=conn_registry))

        assert _run(module.health_check()) is True
        _run(module.shutdown())

    def test_get_tools(self) -> None:
        module = NotionModule()
        tool_names = [fn.__name__ for fn in module.get_tools()]
        assert "notion_search" in tool_names
        assert "notion_read_page" in tool_names
        assert "notion_get_database" in tool_names
        assert "notion_query_database" in tool_names
        assert len(tool_names) == 4

    def test_name_and_description(self) -> None:
        module = NotionModule()
        assert module.name == "notion"
        assert "Notion" in module.description


class TestNotionToolSearch:
    def test_search_empty_query_returns_error(self) -> None:
        payload = json.loads(_run(notion_search("  ")))
        assert payload["error"] is True
        assert "required" in payload["message"]

    def test_search_returns_results(self) -> None:
        fake_client = AsyncMock()
        fake_client.search.return_value = [
            {"id": "p1", "title": "My Page", "object": "page", "url": "https://notion.so/p1"},
        ]
        set_client(fake_client)

        payload = json.loads(_run(notion_search("My Page")))
        assert "results" in payload
        assert len(payload["results"]) == 1
        assert payload["results"][0]["id"] == "p1"
        assert payload["results"][0]["title"] == "My Page"


class TestNotionToolReadPage:
    def test_read_page_empty_id_returns_error(self) -> None:
        payload = json.loads(_run(notion_read_page("")))
        assert payload["error"] is True
        assert "required" in payload["message"]

    def test_read_page_returns_content(self) -> None:
        fake_client = AsyncMock()
        fake_client.read_page.return_value = {
            "page_id": "p1",
            "title": "Test",
            "content_markdown": "# Test\n\nHello",
            "url": "https://notion.so/p1",
        }
        set_client(fake_client)

        payload = json.loads(_run(notion_read_page("p1")))
        assert payload["page_id"] == "p1"
        assert payload["title"] == "Test"
        assert "Hello" in payload["content_markdown"]


class TestNotionToolGetDatabase:
    def test_get_database_empty_id_returns_error(self) -> None:
        payload = json.loads(_run(notion_get_database("")))
        assert payload["error"] is True

    def test_get_database_returns_schema(self) -> None:
        fake_client = AsyncMock()
        fake_client.get_database_schema.return_value = {
            "database_id": "db1",
            "title": "Tasks",
            "columns": [
                {"name": "Name", "type": "title"},
                {"name": "Status", "type": "select"},
            ],
        }
        set_client(fake_client)

        payload = json.loads(_run(notion_get_database("db1")))
        assert payload["database_id"] == "db1"
        assert payload["title"] == "Tasks"
        assert len(payload["columns"]) == 2
        assert payload["columns"][0]["name"] == "Name"


class TestNotionToolQueryDatabase:
    def test_query_empty_id_returns_error(self) -> None:
        payload = json.loads(_run(notion_query_database("")))
        assert payload["error"] is True

    def test_query_invalid_filter_returns_error(self) -> None:
        payload = json.loads(_run(notion_query_database("db1", filter_json="not json")))
        assert payload["error"] is True
        assert "Invalid filter_json" in payload["message"]

    def test_query_returns_rows(self) -> None:
        fake_client = AsyncMock()
        fake_client.query_database.return_value = {
            "database_id": "db1",
            "title": "Tasks",
            "columns": [{"name": "Name", "type": "title"}],
            "rows": [
                {"page_id": "r1", "url": "", "properties": {"Name": "Task 1"}},
                {"page_id": "r2", "url": "", "properties": {"Name": "Task 2"}},
            ],
            "total_rows": 2,
            "truncated": False,
        }
        set_client(fake_client)

        payload = json.loads(_run(notion_query_database("db1")))
        assert payload["database_id"] == "db1"
        assert payload["total_rows"] == 2
        assert payload["truncated"] is False
        assert len(payload["rows"]) == 2


class TestNotionRegistryExposure:
    def test_registry_registers_notion_tools_as_read(self) -> None:
        conn_registry = AsyncMock(spec=ConnectionRegistry)
        http_client = AsyncMock()
        conn_registry.get.return_value = _StubConnection(http_client)

        module = NotionModule()
        _run(module.initialize({"connection": "notion"}, connections=conn_registry))

        registry = ToolRegistry()
        registry.register_module(module, mode=OperationMode.AUTO, skill_names=["usage"])

        for tool_name in ["notion_search", "notion_read_page", "notion_get_database", "notion_query_database"]:
            assert registry.get_module_for_tool(tool_name) is module
            assert registry.check_tool_permission(tool_name)["permission"] == "read"
