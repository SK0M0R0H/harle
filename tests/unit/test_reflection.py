"""Tests for harle.orchestrator.reflection — Level 4 reflection helpers."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from harle.orchestrator.reflection import (
    ReflectionConfig,
    ReflectionRunRecord,
    ReflectionVerdict,
    apply_reflection_pipeline,
    format_reflection_for_vault,
    run_improvement,
    run_reflection,
    should_reflect,
)


def _cfg(**overrides: object) -> ReflectionConfig:
    kwargs: dict[str, object] = {
        "enabled": True,
        "model": None,
        "min_tool_calls": 3,
        "trigger_keywords_csv": "research,report",
        "trigger_roles_csv": "researcher",
        "improvement_max_turns": None,
    }
    kwargs.update(overrides)
    return ReflectionConfig.from_settings_strings(
        enabled=bool(kwargs["enabled"]),
        model=kwargs["model"],  # type: ignore[arg-type]
        min_tool_calls=int(kwargs["min_tool_calls"]),
        trigger_keywords_csv=str(kwargs["trigger_keywords_csv"]),
        trigger_roles_csv=str(kwargs["trigger_roles_csv"]),
        improvement_max_turns=kwargs["improvement_max_turns"],  # type: ignore[arg-type]
    )


class TestShouldReflect:
    def test_disabled(self) -> None:
        c = _cfg(enabled=False)
        ok, reason = should_reflect(
            user_message="research X",
            tool_invocation_count=0,
            routing_method="direct",
            agent_role="researcher",
            config=c,
        )
        assert ok is False
        assert reason == "disabled"

    def test_tool_count(self) -> None:
        c = _cfg()
        ok, reason = should_reflect(
            user_message="hi",
            tool_invocation_count=3,
            routing_method="direct",
            agent_role="assistant",
            config=c,
        )
        assert ok is True
        assert reason == "tool_count"

    def test_keyword(self) -> None:
        c = _cfg()
        ok, reason = should_reflect(
            user_message="Please write a research note",
            tool_invocation_count=0,
            routing_method="direct",
            agent_role="assistant",
            config=c,
        )
        assert ok is True
        assert reason == "keyword:research"

    def test_planned(self) -> None:
        c = _cfg()
        ok, reason = should_reflect(
            user_message="hi",
            tool_invocation_count=0,
            routing_method="planned",
            agent_role="assistant",
            config=c,
        )
        assert ok is True
        assert reason == "planned"

    def test_role(self) -> None:
        c = _cfg()
        ok, reason = should_reflect(
            user_message="hi",
            tool_invocation_count=0,
            routing_method="direct",
            agent_role="researcher",
            config=c,
        )
        assert ok is True
        assert "role:" in reason

    def test_no_match(self) -> None:
        c = _cfg()
        ok, reason = should_reflect(
            user_message="hi",
            tool_invocation_count=0,
            routing_method="direct",
            agent_role="assistant",
            config=c,
        )
        assert ok is False
        assert reason == "no_match"

    def test_empty_keyword_list_disables_keyword_rule(self) -> None:
        c = _cfg(trigger_keywords_csv="")
        ok, _ = should_reflect(
            user_message="research topic",
            tool_invocation_count=0,
            routing_method="direct",
            agent_role="assistant",
            config=c,
        )
        assert ok is False

    def test_tool_count_fires_when_same_tool_called_multiple_times(self) -> None:
        """Three invocations of one tool satisfy min_tool_calls=3 (not len(unique names))."""
        c = _cfg(min_tool_calls=3)
        ok, reason = should_reflect(
            user_message="hi",
            tool_invocation_count=3,
            routing_method="direct",
            agent_role="assistant",
            config=c,
        )
        assert ok is True
        assert reason == "tool_count"

    def test_tool_count_below_threshold_one_invocation(self) -> None:
        c = _cfg(min_tool_calls=3)
        ok, reason = should_reflect(
            user_message="hi",
            tool_invocation_count=1,
            routing_method="direct",
            agent_role="assistant",
            config=c,
        )
        assert ok is False
        assert reason == "no_match"

    def test_empty_role_list_disables_role_rule(self) -> None:
        c = _cfg(trigger_roles_csv="")
        ok, _ = should_reflect(
            user_message="hi",
            tool_invocation_count=0,
            routing_method="direct",
            agent_role="researcher",
            config=c,
        )
        assert ok is False


class TestRunReflection:
    def test_valid_pass_json(self) -> None:
        mock_result = MagicMock()
        mock_result.final_output = '{"verdict": "pass", "assessment": "ok", "improvements": []}'
        mock_result.new_items = []
        mock_result.raw_responses = []
        with patch("agents.Runner") as mock_runner:
            mock_runner.run_sync.return_value = mock_result
            v, turns = run_reflection(
                user_message="q",
                draft_result="a",
                model="gpt-4o-mini",
            )
        assert v.verdict == "pass"
        assert v.assessment == "ok"
        assert v.improvements == ()
        assert turns == 0

    def test_valid_improve_json(self) -> None:
        mock_result = MagicMock()
        mock_result.final_output = (
            '{"verdict": "improve", "assessment": "gaps", "improvements": ["add sources"]}'
        )
        mock_result.new_items = []
        mock_result.raw_responses = []
        with patch("agents.Runner") as mock_runner:
            mock_runner.run_sync.return_value = mock_result
            v, turns = run_reflection(
                user_message="q",
                draft_result="a",
                model="gpt-4o-mini",
            )
        assert v.verdict == "improve"
        assert v.improvements == ("add sources",)
        assert turns == 0

    def test_malformed_json_fail_open(self) -> None:
        mock_result = MagicMock()
        mock_result.final_output = "not json"
        mock_result.new_items = []
        mock_result.raw_responses = []
        with patch("agents.Runner") as mock_runner:
            mock_runner.run_sync.return_value = mock_result
            v, turns = run_reflection(
                user_message="q",
                draft_result="a",
                model="gpt-4o-mini",
            )
        assert v.verdict == "pass"
        assert turns == 0


class TestRunImprovement:
    def test_success_returns_text(self) -> None:
        mock_result = MagicMock()
        mock_result.final_output = "improved answer"
        mock_result.new_items = []
        with patch("agents.Runner") as mock_runner:
            mock_runner.run_sync.return_value = mock_result
            text, tools, turns = run_improvement(
                user_message="q",
                draft_result="old",
                improvements=["fix"],
                base_instructions="base",
                tools=[],
                model="m",
                max_turns=5,
            )
        assert text == "improved answer"
        assert isinstance(tools, list)

    def test_max_turns_returns_none(self) -> None:
        from agents import MaxTurnsExceeded

        with patch("agents.Runner.run_sync") as mock_run:
            mock_run.side_effect = MaxTurnsExceeded("max turns")
            text, tools, turns = run_improvement(
                user_message="q",
                draft_result="old",
                improvements=["fix"],
                base_instructions="base",
                tools=[],
                model="m",
                max_turns=3,
            )
        assert text is None
        assert turns == 3


class TestApplyReflectionPipeline:
    def test_skips_when_not_triggered(self) -> None:
        c = _cfg(enabled=False)
        text, tools, tr, im, rec, post_turns = apply_reflection_pipeline(
            user_message="hi",
            draft_text="draft",
            merged_tools=[],
            tool_invocation_count=0,
            routing_method="direct",
            agent_role="assistant",
            base_instructions="b",
            tools=[],
            execution_model="m",
            reflection_config=c,
            reflection_model_override=None,
            max_iterations_default=10,
        )
        assert text == "draft"
        assert tr is False
        assert rec is None
        assert post_turns == 0

    @patch("harle.orchestrator.reflection.run_improvement")
    @patch("harle.orchestrator.reflection.run_reflection")
    def test_improvement_merges_tools(
        self,
        mock_refl: MagicMock,
        mock_imp: MagicMock,
    ) -> None:
        c = _cfg(min_tool_calls=1)
        mock_refl.return_value = (
            ReflectionVerdict(
                verdict="improve",
                assessment="x",
                improvements=("do",),
            ),
            4,
        )
        mock_imp.return_value = ("better", ["dataset_search"], 2)

        text, tools, tr, im, rec, post_turns = apply_reflection_pipeline(
            user_message="q",
            draft_text="draft",
            merged_tools=["search_web"],
            tool_invocation_count=1,
            routing_method="direct",
            agent_role="assistant",
            base_instructions="b",
            tools=[],
            execution_model="m",
            reflection_config=c,
            reflection_model_override=None,
            max_iterations_default=10,
        )
        assert text == "better"
        assert "search_web" in tools
        assert "dataset_search" in tools
        assert tr is True
        assert im is True
        assert rec is not None
        assert rec.improvement_pass_completed is True
        assert post_turns == 6

    @patch("harle.orchestrator.reflection.run_reflection")
    def test_post_turns_reflect_only_when_verdict_pass(
        self,
        mock_refl: MagicMock,
    ) -> None:
        c = _cfg(min_tool_calls=1)
        mock_refl.return_value = (
            ReflectionVerdict(verdict="pass", assessment="ok", improvements=()),
            3,
        )
        _text, _tools, tr, im, rec, post_turns = apply_reflection_pipeline(
            user_message="q",
            draft_text="draft",
            merged_tools=[],
            tool_invocation_count=1,
            routing_method="direct",
            agent_role="assistant",
            base_instructions="b",
            tools=[],
            execution_model="m",
            reflection_config=c,
            reflection_model_override=None,
            max_iterations_default=10,
        )
        assert tr is True
        assert im is False
        assert rec is not None
        assert post_turns == 3


class TestFormatReflectionForVault:
    def test_not_triggered_empty(self) -> None:
        assert format_reflection_for_vault(triggered=False, record=None, min_tool_calls=3) == ""

    def test_triggered_pass(self) -> None:
        rec = ReflectionRunRecord(
            trigger_reason="planned",
            tool_count_at_trigger=0,
            verdict="pass",
            assessment="ok",
            improvements_suggested=(),
            improvement_pass_ran=False,
            improvement_pass_completed=False,
            improvement_turns=None,
            improvement_tools_called=(),
        )
        body = format_reflection_for_vault(triggered=True, record=rec, min_tool_calls=3)
        assert "##" not in body  # no heading — section title added by service
        assert "pass" in body
        assert "planned" in body


class TestReflectionConfigFromSettings:
    def test_csv_parsing(self) -> None:
        c = ReflectionConfig.from_settings_strings(
            enabled=True,
            model=None,
            min_tool_calls=2,
            trigger_keywords_csv="a,b, c",
            trigger_roles_csv="Researcher",
            improvement_max_turns=5,
        )
        assert c.trigger_keywords == ("a", "b", "c")
        assert c.trigger_roles == ("researcher",)
