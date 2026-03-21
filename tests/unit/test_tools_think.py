"""Unit tests for the think (scratchpad) tool module."""

from __future__ import annotations

import asyncio

from harle.tools.think.module import ThinkToolModule, think


def _run(coro):
    return asyncio.run(coro)


class TestThinkFunction:
    def test_returns_empty_string(self) -> None:
        assert _run(think(reasoning="step one")) == ""

    def test_returns_empty_for_empty_reasoning(self) -> None:
        assert _run(think(reasoning="")) == ""

    def test_permission_is_read(self) -> None:
        assert getattr(think, "permission", None) == "read"

    def test_requires_approval_false(self) -> None:
        assert getattr(think, "requires_approval", None) is False


class TestThinkToolModule:
    def test_name_and_description(self) -> None:
        mod = ThinkToolModule()
        assert mod.name == "think"
        assert "scratchpad" in mod.description.lower()

    def test_get_tools_returns_think(self) -> None:
        mod = ThinkToolModule()
        tools = mod.get_tools()
        assert len(tools) == 1
        assert tools[0] is think

    def test_initialize_and_shutdown(self) -> None:
        async def _lifecycle() -> None:
            mod = ThinkToolModule()
            await mod.initialize({}, connections=None)
            await mod.shutdown()

        _run(_lifecycle())
