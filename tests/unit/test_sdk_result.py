"""Unit tests for orchestrator SDK result helpers."""

from __future__ import annotations

from types import SimpleNamespace

from harle.orchestrator.sdk_result import (
    build_planning_tool_context_section,
    count_tool_call_invocations,
    extract_run_metadata,
)


class TestExtractRunMetadata:
    def test_empty_result(self) -> None:
        r = SimpleNamespace(new_items=[], raw_responses=[])
        tools, turns = extract_run_metadata(r)
        assert tools == []
        assert turns == 0

    def test_dedupes_tool_names_but_invocation_count_sees_repeats(self) -> None:
        """extract_run_metadata keeps unique names; count_tool_call_invocations counts each call."""
        calls = [
            SimpleNamespace(type="tool_call_item", raw_item=SimpleNamespace(name="dataset_search")),
            SimpleNamespace(type="tool_call_item", raw_item=SimpleNamespace(name="dataset_search")),
            SimpleNamespace(type="tool_call_item", raw_item=SimpleNamespace(name="dataset_search")),
        ]
        r = SimpleNamespace(new_items=calls, raw_responses=[])
        tools, _turns = extract_run_metadata(r)
        assert tools == ["dataset_search"]
        assert count_tool_call_invocations(r) == 3


class TestCountToolCallInvocations:
    def test_empty(self) -> None:
        r = SimpleNamespace(new_items=[], raw_responses=[])
        assert count_tool_call_invocations(r) == 0

    def test_ignores_non_tool_items(self) -> None:
        msg = SimpleNamespace(type="message_output_item")
        r = SimpleNamespace(new_items=[msg], raw_responses=[])
        assert count_tool_call_invocations(r) == 0


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
