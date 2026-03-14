"""Tests for tool factory connection/module bootstrap behavior."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from harle.tools.factory import build_connections, build_tool_registry


class TestBuildConnections:
    @patch("harle.tools.factory._run_coro_sync")
    @patch("harle.tools.factory.ConnectionRegistry")
    @patch("harle.tools.factory.TrelloConnection")
    @patch("harle.tools.factory.TavilyConnection")
    @patch("harle.tools.factory.os.getenv")
    def test_build_connections_returns_none_without_any_credentials(
        self,
        mock_getenv: MagicMock,
        mock_tavily_cls: MagicMock,
        mock_trello_cls: MagicMock,
        mock_registry_cls: MagicMock,
        mock_run_coro_sync: MagicMock,
    ) -> None:
        del mock_tavily_cls, mock_trello_cls
        mock_getenv.side_effect = lambda key, default="": {
            "TAVILY_API_KEY": "",
            "TRELLO_API_KEY": "",
            "TRELLO_API_TOKEN": "",
            "NOTION_API_TOKEN": "",
        }.get(key, default)

        result = build_connections()

        assert result is None
        mock_registry_cls.assert_not_called()
        mock_run_coro_sync.assert_not_called()

    @patch("harle.tools.factory._run_coro_sync")
    @patch("harle.tools.factory.ConnectionRegistry")
    @patch("harle.tools.factory.TrelloConnection")
    @patch("harle.tools.factory.TavilyConnection")
    @patch("harle.tools.factory.os.getenv")
    def test_build_connections_registers_only_trello_when_only_trello_credentials_present(
        self,
        mock_getenv: MagicMock,
        mock_tavily_cls: MagicMock,
        mock_trello_cls: MagicMock,
        mock_registry_cls: MagicMock,
        mock_run_coro_sync: MagicMock,
    ) -> None:
        mock_getenv.side_effect = lambda key, default="": {
            "TAVILY_API_KEY": "",
            "TRELLO_API_KEY": "trello-key",
            "TRELLO_API_TOKEN": "trello-token",
            "NOTION_API_TOKEN": "",
        }.get(key, default)

        registry = MagicMock()
        mock_registry_cls.return_value = registry
        registry.register.return_value = "trello-register-coro"

        result = build_connections()

        assert result is registry
        mock_tavily_cls.assert_not_called()
        mock_trello_cls.assert_called_once()
        registry.register.assert_called_once_with(
            mock_trello_cls.return_value,
            {"api_key": "trello-key", "api_token": "trello-token"},
        )
        mock_run_coro_sync.assert_called_once_with("trello-register-coro")

    @patch("harle.tools.factory._run_coro_sync")
    @patch("harle.tools.factory.ConnectionRegistry")
    @patch("harle.tools.factory.TrelloConnection")
    @patch("harle.tools.factory.TavilyConnection")
    @patch("harle.tools.factory.os.getenv")
    def test_build_connections_registers_both_services_when_both_credentials_present(
        self,
        mock_getenv: MagicMock,
        mock_tavily_cls: MagicMock,
        mock_trello_cls: MagicMock,
        mock_registry_cls: MagicMock,
        mock_run_coro_sync: MagicMock,
    ) -> None:
        mock_getenv.side_effect = lambda key, default="": {
            "TAVILY_API_KEY": "tavily-key",
            "TRELLO_API_KEY": "trello-key",
            "TRELLO_API_TOKEN": "trello-token",
            "NOTION_API_TOKEN": "",
        }.get(key, default)

        registry = MagicMock()
        mock_registry_cls.return_value = registry
        registry.register.side_effect = ["tavily-register-coro", "trello-register-coro"]

        result = build_connections()

        assert result is registry
        assert registry.register.call_count == 2
        registry.register.assert_any_call(
            mock_tavily_cls.return_value,
            {"api_key": "tavily-key"},
        )
        registry.register.assert_any_call(
            mock_trello_cls.return_value,
            {"api_key": "trello-key", "api_token": "trello-token"},
        )
        assert mock_run_coro_sync.call_count == 2


class TestBuildToolRegistry:
    @patch("harle.tools.factory._register_notion")
    @patch("harle.tools.factory._register_trello")
    @patch("harle.tools.factory._register_web_search")
    @patch("harle.tools.factory._register_vault")
    @patch("harle.tools.factory.build_connections")
    def test_build_tool_registry_returns_none_when_no_modules_register(
        self,
        mock_build_connections: MagicMock,
        mock_register_vault: MagicMock,
        mock_register_web: MagicMock,
        mock_register_trello: MagicMock,
        mock_register_notion: MagicMock,
    ) -> None:
        mock_build_connections.return_value = None
        mock_register_vault.return_value = False
        mock_register_web.return_value = False
        mock_register_trello.return_value = False
        mock_register_notion.return_value = False

        registry = build_tool_registry(search_engine=None, dataset_reader=None)

        assert registry is None

    @patch("harle.tools.factory._register_notion")
    @patch("harle.tools.factory._register_trello")
    @patch("harle.tools.factory._register_web_search")
    @patch("harle.tools.factory._register_vault")
    @patch("harle.tools.factory.build_connections")
    def test_build_tool_registry_keeps_partial_module_availability(
        self,
        mock_build_connections: MagicMock,
        mock_register_vault: MagicMock,
        mock_register_web: MagicMock,
        mock_register_trello: MagicMock,
        mock_register_notion: MagicMock,
    ) -> None:
        connections = MagicMock()
        mock_build_connections.return_value = connections
        mock_register_vault.return_value = False
        mock_register_web.return_value = False
        mock_register_trello.return_value = True
        mock_register_notion.return_value = False

        registry = build_tool_registry(search_engine=None, dataset_reader=None)

        assert registry is not None
        assert registry.list_modules() == []
        mock_register_web.assert_called_once()
        mock_register_trello.assert_called_once()
