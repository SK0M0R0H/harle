"""Tests for the Tool Module Layer — Phase 1 core infrastructure.

Covers:
- BaseToolModule contract (via the DummyModule)
- ToolRegistry (register, lookup, naming conflicts, shutdown)
- Permission checking (operation modes, approval flow)
- OpenAI Agents SDK integration (FunctionTool generation)
"""

from __future__ import annotations

import asyncio
from typing import Callable

import pytest
from agents import FunctionTool

from harle.tools.base import BaseToolModule
from harle.tools.dummy.module import DummyModule
from harle.tools.dummy.tools import dummy_create, dummy_delete, dummy_read
from harle.tools.permissions import (
    OperationMode,
    check_permission,
    get_requires_approval,
    get_tool_permission,
)
from harle.tools.registry import ToolRegistry, ToolRegistryError


def _run(coro):
    """Run an async coroutine synchronously (no pytest-asyncio needed)."""
    return asyncio.get_event_loop().run_until_complete(coro)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _SecondDummyModule(BaseToolModule):
    """A second module that deliberately reuses a tool name for conflict tests."""

    @property
    def name(self) -> str:
        return "second_dummy"

    @property
    def description(self) -> str:
        return "Second dummy for conflict testing"

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def get_tools(self) -> list[Callable]:
        return [dummy_read]


class _FailingShutdownModule(BaseToolModule):
    """Module whose shutdown raises to test error resilience."""

    @property
    def name(self) -> str:
        return "failing"

    @property
    def description(self) -> str:
        return "Module that fails on shutdown"

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        raise RuntimeError("Simulated shutdown failure")

    def get_tools(self) -> list[Callable]:
        async def noop_tool(x: str) -> str:
            """A no-op tool.

            Args:
                x: Placeholder argument.
            """
            return x

        return [noop_tool]


class _EmptyModule(BaseToolModule):
    """Module with no tools — valid but empty."""

    @property
    def name(self) -> str:
        return "empty"

    @property
    def description(self) -> str:
        return "Module with zero tools"

    async def initialize(self, config: dict) -> None:
        pass

    async def shutdown(self) -> None:
        pass

    def get_tools(self) -> list[Callable]:
        return []


# ---------------------------------------------------------------------------
# BaseToolModule
# ---------------------------------------------------------------------------


class TestBaseToolModule:
    """Tests for the BaseToolModule contract via DummyModule."""

    def test_name_and_description(self) -> None:
        mod = DummyModule()
        assert mod.name == "dummy"
        assert "dummy" in mod.description.lower()

    def test_get_tools_returns_callables(self) -> None:
        mod = DummyModule()
        tools = mod.get_tools()
        assert len(tools) == 3
        assert all(callable(fn) for fn in tools)

    def test_initialize_and_shutdown(self) -> None:
        mod = DummyModule()
        _run(mod.initialize({"key": "value"}))
        _run(mod.shutdown())

    def test_health_check_default(self) -> None:
        mod = DummyModule()
        assert _run(mod.health_check()) is True


# ---------------------------------------------------------------------------
# Permissions
# ---------------------------------------------------------------------------


class TestPermissions:
    """Tests for the permission checking layer."""

    def test_get_tool_permission_read(self) -> None:
        assert get_tool_permission(dummy_read) == "read"

    def test_get_tool_permission_write(self) -> None:
        assert get_tool_permission(dummy_create) == "write"

    def test_get_tool_permission_delete(self) -> None:
        assert get_tool_permission(dummy_delete) == "delete"

    def test_get_tool_permission_default(self) -> None:
        def bare_fn() -> None:
            pass

        assert get_tool_permission(bare_fn) == "read"

    def test_get_requires_approval(self) -> None:
        assert get_requires_approval(dummy_read) is False
        assert get_requires_approval(dummy_create) is True
        assert get_requires_approval(dummy_delete) is True

    def test_read_only_mode_allows_read(self) -> None:
        result = check_permission(dummy_read, OperationMode.READ_ONLY)
        assert result["allowed"] is True
        assert result["needs_approval"] is False

    def test_read_only_mode_blocks_write(self) -> None:
        result = check_permission(dummy_create, OperationMode.READ_ONLY)
        assert result["allowed"] is False
        assert "read_only" in result["reason"]

    def test_read_only_mode_blocks_delete(self) -> None:
        result = check_permission(dummy_delete, OperationMode.READ_ONLY)
        assert result["allowed"] is False

    def test_propose_mode_read_no_approval(self) -> None:
        result = check_permission(dummy_read, OperationMode.PROPOSE)
        assert result["allowed"] is True
        assert result["needs_approval"] is False

    def test_propose_mode_write_needs_approval(self) -> None:
        result = check_permission(dummy_create, OperationMode.PROPOSE)
        assert result["allowed"] is True
        assert result["needs_approval"] is True

    def test_propose_mode_delete_needs_approval(self) -> None:
        result = check_permission(dummy_delete, OperationMode.PROPOSE)
        assert result["allowed"] is True
        assert result["needs_approval"] is True

    def test_auto_mode_allows_all(self) -> None:
        for fn in (dummy_read, dummy_create, dummy_delete):
            result = check_permission(fn, OperationMode.AUTO)
            assert result["allowed"] is True
            assert result["needs_approval"] is False

    def test_mode_from_string(self) -> None:
        result = check_permission(dummy_create, "propose")
        assert result["allowed"] is True
        assert result["needs_approval"] is True

    def test_invalid_permission_defaults_to_read(self) -> None:
        def bad_fn() -> None:
            pass

        bad_fn.permission = "execute"  # type: ignore[attr-defined]

        assert get_tool_permission(bad_fn) == "read"


# ---------------------------------------------------------------------------
# ToolRegistry
# ---------------------------------------------------------------------------


class TestToolRegistry:
    """Tests for the ToolRegistry class."""

    def _make_registry_with_dummy(
        self,
        mode: OperationMode = OperationMode.PROPOSE,
    ) -> ToolRegistry:
        registry = ToolRegistry()
        mod = DummyModule()
        registry.register_module(mod, mode=mode)
        return registry

    def test_register_and_list_tools(self) -> None:
        registry = self._make_registry_with_dummy()
        tools = registry.list_all_tools()
        assert "dummy_read" in tools
        assert "dummy_create" in tools
        assert "dummy_delete" in tools
        assert len(tools) == 3

    def test_list_modules(self) -> None:
        registry = self._make_registry_with_dummy()
        assert registry.list_modules() == ["dummy"]

    def test_len_and_contains(self) -> None:
        registry = self._make_registry_with_dummy()
        assert len(registry) == 3
        assert "dummy_read" in registry
        assert "nonexistent" not in registry

    def test_get_module(self) -> None:
        registry = self._make_registry_with_dummy()
        mod = registry.get_module("dummy")
        assert mod is not None
        assert mod.name == "dummy"
        assert registry.get_module("nonexistent") is None

    def test_get_module_for_tool(self) -> None:
        registry = self._make_registry_with_dummy()
        mod = registry.get_module_for_tool("dummy_read")
        assert mod is not None
        assert mod.name == "dummy"
        assert registry.get_module_for_tool("nonexistent") is None

    def test_get_agent_tools_returns_function_tools(self) -> None:
        registry = self._make_registry_with_dummy()
        sdk_tools = registry.get_agent_tools(["dummy_read", "dummy_create"])
        assert len(sdk_tools) == 2
        assert all(isinstance(t, FunctionTool) for t in sdk_tools)

    def test_get_agent_tools_schema_from_docstring(self) -> None:
        registry = self._make_registry_with_dummy()
        [tool] = registry.get_agent_tools(["dummy_read"])
        assert tool.name == "dummy_read"
        assert "item" in tool.description.lower() or "read" in tool.description.lower()
        assert "item_id" in tool.params_json_schema.get("properties", {})

    def test_get_agent_tools_skips_unknown(self) -> None:
        registry = self._make_registry_with_dummy()
        sdk_tools = registry.get_agent_tools(["dummy_read", "nonexistent"])
        assert len(sdk_tools) == 1

    def test_duplicate_module_name_raises(self) -> None:
        registry = self._make_registry_with_dummy()
        with pytest.raises(ToolRegistryError, match="already registered"):
            registry.register_module(DummyModule())

    def test_duplicate_tool_name_raises(self) -> None:
        registry = self._make_registry_with_dummy()
        with pytest.raises(ToolRegistryError, match="dummy_read"):
            registry.register_module(_SecondDummyModule())

    def test_register_empty_module(self) -> None:
        registry = ToolRegistry()
        registry.register_module(_EmptyModule())
        assert registry.list_modules() == ["empty"]
        assert registry.list_all_tools() == []
        assert len(registry) == 0

    def test_check_tool_permission(self) -> None:
        registry = self._make_registry_with_dummy()
        result = registry.check_tool_permission("dummy_create")
        assert result["allowed"] is True
        assert result["needs_approval"] is True
        assert result["permission"] == "write"
        assert result["mode"] == "propose"

    def test_check_tool_permission_read_only(self) -> None:
        registry = self._make_registry_with_dummy(mode=OperationMode.READ_ONLY)
        result = registry.check_tool_permission("dummy_create")
        assert result["allowed"] is False

    def test_check_tool_permission_unknown_raises(self) -> None:
        registry = self._make_registry_with_dummy()
        with pytest.raises(KeyError, match="nonexistent"):
            registry.check_tool_permission("nonexistent")

    def test_shutdown_all(self) -> None:
        registry = self._make_registry_with_dummy()
        _run(registry.shutdown_all())

    def test_shutdown_all_resilient_to_errors(self) -> None:
        registry = ToolRegistry()
        registry.register_module(_FailingShutdownModule())
        _run(registry.shutdown_all())


# ---------------------------------------------------------------------------
# End-to-end: DummyModule → Registry → FunctionTool → SDK acceptance
# ---------------------------------------------------------------------------


class TestEndToEnd:
    """Verify the full Phase 1 flow as described in the TRD."""

    def test_full_lifecycle(self) -> None:
        mod = DummyModule()
        _run(mod.initialize({"test_key": "test_value"}))
        assert _run(mod.health_check()) is True

        registry = ToolRegistry()
        registry.register_module(mod, mode=OperationMode.PROPOSE)

        assert len(registry) == 3
        assert "dummy" in registry.list_modules()

        sdk_tools = registry.get_agent_tools(["dummy_read", "dummy_create", "dummy_delete"])
        assert len(sdk_tools) == 3

        for st in sdk_tools:
            assert isinstance(st, FunctionTool)
            assert st.name in ("dummy_read", "dummy_create", "dummy_delete")
            assert st.description
            assert st.params_json_schema

        _run(registry.shutdown_all())

    def test_tool_functions_are_callable(self) -> None:
        result = _run(dummy_read("abc123"))
        assert "abc123" in result

        result = _run(dummy_create("My Task", category="work"))
        assert "My Task" in result

        result = _run(dummy_delete("item_99"))
        assert "item_99" in result
