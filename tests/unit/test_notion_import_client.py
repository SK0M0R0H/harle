"""Unit tests for NotionImportClient (vault_imports/notion/client.py)."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from harle.vault_imports.notion.client import NotionClientError, NotionImportClient


def _run(coro):
    return asyncio.run(coro)


def _make_response(json_body: dict) -> MagicMock:
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = json_body
    return resp


class TestNotionImportClientConfig:
    """Tests for configurable max_block_depth and page_size."""

    def test_client_uses_config_page_size_and_max_block_depth(self) -> None:
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response({"results": [], "has_more": False})
        mock_http.post.return_value = _make_response({"results": [], "has_more": False})

        client = NotionImportClient(
            mock_http,
            config={"page_size": 50, "max_block_depth": 2},
        )
        assert client._page_size == 50
        assert client._max_block_depth == 2

    def test_client_defaults_when_config_empty(self) -> None:
        mock_http = AsyncMock()
        client = NotionImportClient(mock_http, config={})
        assert client._page_size == 100
        assert client._max_block_depth == 3

    def test_client_defaults_when_config_none(self) -> None:
        mock_http = AsyncMock()
        client = NotionImportClient(mock_http)
        assert client._page_size == 100
        assert client._max_block_depth == 3


class TestNotionImportClientSearch:
    """Tests for search_all_pages and search_all_databases."""

    def test_search_all_pages_single_page(self) -> None:
        mock_http = AsyncMock()
        mock_http.post.return_value = _make_response({
            "results": [{"id": "p1", "object": "page", "url": "https://notion.so/p1"}],
            "has_more": False,
        })

        client = NotionImportClient(mock_http)
        results = _run(client.search_all_pages())

        assert len(results) == 1
        assert results[0]["id"] == "p1"
        mock_http.post.assert_called_once()
        call_json = mock_http.post.call_args[1]["json"]
        assert call_json["filter"] == {"value": "page", "property": "object"}

    def test_search_all_pages_paginates(self) -> None:
        mock_http = AsyncMock()
        mock_http.post.side_effect = [
            _make_response({
                "results": [{"id": "p1", "object": "page"}],
                "has_more": True,
                "next_cursor": "cursor1",
            }),
            _make_response({
                "results": [{"id": "p2", "object": "page"}],
                "has_more": False,
            }),
        ]

        client = NotionImportClient(mock_http)
        results = _run(client.search_all_pages())

        assert len(results) == 2
        assert results[0]["id"] == "p1"
        assert results[1]["id"] == "p2"
        assert mock_http.post.call_count == 2
        second_call_json = mock_http.post.call_args_list[1][1]["json"]
        assert second_call_json["start_cursor"] == "cursor1"

    def test_search_all_databases_returns_databases(self) -> None:
        mock_http = AsyncMock()
        mock_http.post.return_value = _make_response({
            "results": [{"id": "db1", "object": "database", "title": []}],
            "has_more": False,
        })

        client = NotionImportClient(mock_http)
        results = _run(client.search_all_databases())

        assert len(results) == 1
        assert results[0]["object"] == "database"
        call_json = mock_http.post.call_args[1]["json"]
        assert call_json["filter"] == {"value": "database", "property": "object"}

    def test_search_returns_first_page_only(self) -> None:
        mock_http = AsyncMock()
        mock_http.post.return_value = _make_response({
            "results": [
                {"id": "p1", "object": "page", "url": "https://notion.so/p1"},
                {"id": "p2", "object": "page", "url": "https://notion.so/p2"},
            ],
            "has_more": True,
        })

        client = NotionImportClient(mock_http)
        results = _run(client.search("tasks", object_type="page", page_size=20))

        assert len(results) == 2
        call_json = mock_http.post.call_args[1]["json"]
        assert call_json["query"] == "tasks"
        assert call_json["filter"] == {"value": "page", "property": "object"}
        assert call_json["page_size"] == 20
        assert mock_http.post.call_count == 1


class TestNotionImportClientPages:
    """Tests for get_page and get_blocks."""

    def test_get_page_returns_page_object(self) -> None:
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response({
            "id": "p1",
            "url": "https://notion.so/p1",
            "properties": {"title": {"id": "t1", "type": "title"}},
        })

        client = NotionImportClient(mock_http)
        page = _run(client.get_page("p1"))

        assert page["id"] == "p1"
        mock_http.get.assert_called_once()
        assert "/pages/p1" in mock_http.get.call_args[0][0]

    def test_get_blocks_returns_blocks(self) -> None:
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response({
            "results": [
                {"id": "b1", "type": "paragraph", "paragraph": {"rich_text": []}, "has_children": False},
            ],
            "has_more": False,
        })

        client = NotionImportClient(mock_http)
        blocks = _run(client.get_blocks("p1"))

        assert len(blocks) == 1
        assert blocks[0]["type"] == "paragraph"
        mock_http.get.assert_called_once()
        assert "/blocks/p1/children" in mock_http.get.call_args[0][0]

    def test_get_blocks_recurses_children_up_to_max_depth(self) -> None:
        mock_http = AsyncMock()
        call_count = 0

        def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            path = args[0] if args else kwargs.get("url", "")
            if "blocks" in path and "children" in path:
                if "b1" in path:
                    return _make_response({
                        "results": [
                            {"id": "b1-1", "type": "paragraph", "paragraph": {}, "has_children": False},
                        ],
                        "has_more": False,
                    })
                if "b1-1" in path:
                    return _make_response({"results": [], "has_more": False})
            return _make_response({
                "results": [
                    {"id": "b1", "type": "paragraph", "paragraph": {}, "has_children": True},
                ],
                "has_more": False,
            })

        mock_http.get.side_effect = side_effect
        client = NotionImportClient(mock_http)
        blocks = _run(client.get_blocks("page-id"))

        assert len(blocks) == 1
        assert blocks[0]["id"] == "b1"
        assert "children" in blocks[0]
        assert len(blocks[0]["children"]) == 1


class TestNotionImportClientDatabase:
    """Tests for get_database, query_database, get_page_property, get_database_rows_with_properties."""

    def test_get_database_returns_schema(self) -> None:
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response({
            "id": "db1",
            "title": [{"plain_text": "Tasks"}],
            "properties": {
                "Name": {"id": "title-id", "type": "title"},
                "Status": {"id": "status-id", "type": "select"},
            },
        })

        client = NotionImportClient(mock_http)
        db = _run(client.get_database("db1"))

        assert db["id"] == "db1"
        assert "Name" in db["properties"]
        assert db["properties"]["Name"]["type"] == "title"

    def test_query_database_returns_pages(self) -> None:
        mock_http = AsyncMock()
        mock_http.post.return_value = _make_response({
            "results": [{"id": "row1", "url": "https://notion.so/row1"}],
            "has_more": False,
        })

        client = NotionImportClient(mock_http)
        pages = _run(client.query_database("db1"))

        assert len(pages) == 1
        assert pages[0]["id"] == "row1"
        mock_http.post.assert_called_once()
        call_json = mock_http.post.call_args[1]["json"]
        assert "page_size" in call_json

    def test_get_page_property_returns_value(self) -> None:
        mock_http = AsyncMock()
        mock_http.get.return_value = _make_response({
            "type": "select",
            "select": {"name": "Done"},
        })

        client = NotionImportClient(mock_http)
        data = _run(client.get_page_property("page1", "prop-id"))

        assert data["type"] == "select"
        assert data["select"]["name"] == "Done"
        mock_http.get.assert_called_once()
        assert "/pages/page1/properties/prop-id" in mock_http.get.call_args[0][0]

    def test_get_database_rows_with_properties_two_step(self) -> None:
        mock_http = AsyncMock()
        post_calls = 0
        get_calls = []

        def post_side_effect(*args, **kwargs):
            nonlocal post_calls
            post_calls += 1
            return _make_response({
                "results": [
                    {"id": "row1", "url": "https://notion.so/row1"},
                ],
                "has_more": False,
            })

        def get_side_effect(*args, **kwargs):
            get_calls.append(args[0] if args else "")
            return _make_response({
                "type": "title",
                "title": [{"plain_text": "Task One"}],
            })

        mock_http.post.side_effect = post_side_effect
        mock_http.get.side_effect = get_side_effect

        client = NotionImportClient(mock_http)
        schema = {
            "Name": {"id": "title-id", "type": "title"},
        }
        rows = _run(client.get_database_rows_with_properties("db1", schema))

        assert len(rows) == 1
        assert rows[0]["_page_id"] == "row1"
        assert "Name" in rows[0]
        assert post_calls == 1
        assert len(get_calls) >= 1


class TestNotionImportClientErrors:
    """Tests for HTTP and API error handling."""

    def test_get_raises_on_http_error(self) -> None:
        import httpx

        mock_http = AsyncMock()
        mock_http.get.side_effect = httpx.HTTPStatusError(
            "404",
            request=MagicMock(),
            response=MagicMock(status_code=404),
        )

        client = NotionImportClient(mock_http)
        with pytest.raises(NotionClientError, match="Notion API error"):
            _run(client.get_page("p1"))

    def test_post_raises_on_http_error(self) -> None:
        import httpx

        mock_http = AsyncMock()
        mock_http.post.side_effect = httpx.HTTPStatusError(
            "401",
            request=MagicMock(),
            response=MagicMock(status_code=401),
        )

        client = NotionImportClient(mock_http)
        with pytest.raises(NotionClientError, match="Notion API error"):
            _run(client.search_all_pages())
