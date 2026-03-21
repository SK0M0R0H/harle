"""Unit tests for orchestrator SDK result helpers."""

from __future__ import annotations

from types import SimpleNamespace

from harle.orchestrator.sdk_result import (
    build_planning_tool_context_section,
    extract_run_metadata,
)


class TestExtractRunMetadata:
    def test_empty_result(self) -> None:
        r = SimpleNamespace(new_items=[], raw_responses=[])
        tools, turns = extract_run_metadata(r)
        assert tools == []
        assert turns == 0


class TestBuildPlanningToolContextSection:
    def test_empty_items(self) -> None:
        r = SimpleNamespace(new_items=[])
        assert build_planning_tool_context_section(r) == ""

    def test_pairs_call_and_output(self) -> None:
        call = SimpleNamespace(
            type="tool_call_item",
            raw_item=SimpleNamespace(name="dataset_search"),
        )
        out = SimpleNamespace(
            type="tool_call_output_item",
            output={"hits": [{"id": "a"}]},
            raw_item=None,
        )
        r = SimpleNamespace(new_items=[call, out])
        s = build_planning_tool_context_section(r)
        assert "Planning phase" in s
        assert "dataset_search" in s
        assert '"hits"' in s or "hits" in s

    def test_truncation(self) -> None:
        long_text = "x" * 500
        call = SimpleNamespace(
            type="tool_call_item",
            raw_item=SimpleNamespace(name="t"),
        )
        out = SimpleNamespace(
            type="tool_call_output_item",
            output=long_text,
            raw_item=None,
        )
        r = SimpleNamespace(new_items=[call, out])
        s = build_planning_tool_context_section(r, max_chars=200)
        assert "truncated" in s.lower()
