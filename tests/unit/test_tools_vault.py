"""Tests for the Vault tool module — dataset_search, dataset_read_file.

Covers:
- VaultModule lifecycle (init, shutdown, health check)
- Tool function behaviour with and without backends
- Registry integration (FunctionTool generation)
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from textwrap import dedent
from typing import Callable
from unittest.mock import MagicMock

import pytest
from agents import FunctionTool

from harle.tools.registry import ToolRegistry
from harle.tools.vault.module import VaultModule
from harle.tools.vault.tools import (
    clear_vault_accessors,
    dataset_read_file,
    dataset_search,
    get_dataset_reader,
    get_search_engine,
    set_dataset_reader,
    set_search_engine,
)


def _run(coro):
    """Run an async coroutine synchronously."""
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# Module-level accessors
# ---------------------------------------------------------------------------


class TestVaultAccessors:
    """Test module-level get/set/clear for search engine and reader."""

    def setup_method(self) -> None:
        clear_vault_accessors()

    def teardown_method(self) -> None:
        clear_vault_accessors()

    def test_initial_state_is_none(self) -> None:
        assert get_search_engine() is None
        assert get_dataset_reader() is None

    def test_set_and_get_search_engine(self) -> None:
        sentinel = object()
        set_search_engine(sentinel)
        assert get_search_engine() is sentinel

    def test_set_and_get_dataset_reader(self) -> None:
        sentinel = object()
        set_dataset_reader(sentinel)
        assert get_dataset_reader() is sentinel

    def test_clear_resets_both(self) -> None:
        set_search_engine(object())
        set_dataset_reader(object())
        clear_vault_accessors()
        assert get_search_engine() is None
        assert get_dataset_reader() is None


# ---------------------------------------------------------------------------
# VaultModule lifecycle
# ---------------------------------------------------------------------------


class TestVaultModule:
    def test_name_and_description(self) -> None:
        mod = VaultModule()
        assert mod.name == "vault"
        assert "dataset" in mod.description.lower() or "search" in mod.description.lower()

    def test_get_tools_returns_two_callables(self) -> None:
        mod = VaultModule()
        tools = mod.get_tools()
        assert len(tools) == 2
        names = {fn.__name__ for fn in tools}
        assert names == {"dataset_search", "dataset_read_file"}

    def test_initialize_sets_accessors(self) -> None:
        engine = object()
        reader = object()
        mod = VaultModule(search_engine=engine, dataset_reader=reader)
        _run(mod.initialize({}))
        assert get_search_engine() is engine
        assert get_dataset_reader() is reader
        _run(mod.shutdown())

    def test_shutdown_clears_accessors(self) -> None:
        mod = VaultModule(search_engine=object(), dataset_reader=object())
        _run(mod.initialize({}))
        _run(mod.shutdown())
        assert get_search_engine() is None
        assert get_dataset_reader() is None

    def test_health_check_true_with_reader(self) -> None:
        mod = VaultModule(dataset_reader=object())
        assert _run(mod.health_check()) is True

    def test_health_check_true_with_engine(self) -> None:
        mod = VaultModule(search_engine=object())
        assert _run(mod.health_check()) is True

    def test_health_check_false_with_nothing(self) -> None:
        mod = VaultModule()
        assert _run(mod.health_check()) is False


# ---------------------------------------------------------------------------
# Tool functions — without backends
# ---------------------------------------------------------------------------


class TestToolFunctionsWithoutBackends:
    """Verify graceful error handling when backends are not configured."""

    def setup_method(self) -> None:
        clear_vault_accessors()

    def teardown_method(self) -> None:
        clear_vault_accessors()

    def test_dataset_search_returns_error(self) -> None:
        result = json.loads(_run(dataset_search("test query")))
        assert result["query"] == "test query"
        assert "error" in result
        assert result["results"] == []

    def test_dataset_read_file_returns_error(self) -> None:
        result = json.loads(_run(dataset_read_file("some/path.md")))
        assert result["file_path"] == "some/path.md"
        assert result["error"] is True


# ---------------------------------------------------------------------------
# Tool functions — with real dataset
# ---------------------------------------------------------------------------


class TestToolFunctionsWithDataset:
    """Verify tools work with a real DatasetReader and SearchEngine."""

    @pytest.fixture(autouse=True)
    def _setup_dataset(self, tmp_path: Path) -> None:
        knowledge_dir = tmp_path / "knowledge" / "work"
        knowledge_dir.mkdir(parents=True)
        (knowledge_dir / "architecture.md").write_text(
            dedent("""\
                ---
                title: Architecture Overview
                tags: [architecture, design]
                context: work
                ---
                This document describes the modular architecture.
            """),
            encoding="utf-8",
        )
        (knowledge_dir / "privacy.md").write_text(
            dedent("""\
                ---
                title: Privacy Solutions
                tags: [privacy, security]
                context: work
                ---
                Privacy is important for data handling.
            """),
            encoding="utf-8",
        )

        from harle.dataset.reader import DatasetReader

        self.reader = DatasetReader(str(tmp_path))
        set_dataset_reader(self.reader)
        yield
        clear_vault_accessors()

    def test_dataset_read_file_success(self) -> None:
        result = json.loads(
            _run(dataset_read_file("knowledge/work/architecture.md"))
        )
        assert result["title"] == "Architecture Overview"
        assert "modular architecture" in result["content"]
        assert result["tags"] == ["architecture", "design"]
        assert result["context"] == "work"

    def test_dataset_read_file_not_found(self) -> None:
        result = json.loads(_run(dataset_read_file("nonexistent.md")))
        assert result["error"] is True
        assert "not found" in result["content"].lower() or "Failed" in result["content"]

    def test_dataset_read_file_max_results_clamped(self) -> None:
        """max_results is clamped to 1–10."""
        clear_vault_accessors()
        result = json.loads(_run(dataset_search("test", max_results=0)))
        assert "error" in result


# ---------------------------------------------------------------------------
# Registry integration
# ---------------------------------------------------------------------------


class TestVaultRegistryIntegration:
    """Verify vault tools work with the ToolRegistry."""

    def test_register_vault_module(self) -> None:
        mod = VaultModule()
        registry = ToolRegistry()
        registry.register_module(mod)

        assert "vault" in registry.list_modules()
        assert "dataset_search" in registry
        assert "dataset_read_file" in registry
        assert len(registry.get_agent_tools(["dataset_search", "dataset_read_file"])) == 2

    def test_function_tools_have_schemas(self) -> None:
        mod = VaultModule()
        registry = ToolRegistry()
        registry.register_module(mod)

        [search_tool] = registry.get_agent_tools(["dataset_search"])
        assert isinstance(search_tool, FunctionTool)
        assert search_tool.name == "dataset_search"
        props = search_tool.params_json_schema.get("properties", {})
        assert "query" in props

        [read_tool] = registry.get_agent_tools(["dataset_read_file"])
        assert isinstance(read_tool, FunctionTool)
        assert read_tool.name == "dataset_read_file"
        props = read_tool.params_json_schema.get("properties", {})
        assert "file_path" in props

    def test_full_lifecycle(self) -> None:
        mod = VaultModule(dataset_reader=MagicMock())
        _run(mod.initialize({}))

        registry = ToolRegistry()
        registry.register_module(mod)

        assert len(registry) == 2
        tools = registry.get_agent_tools(["dataset_search", "dataset_read_file"])
        assert len(tools) == 2

        _run(registry.shutdown_all())
