"""Tests for harle.orchestrator.planner — Level 3 planning helpers."""

from __future__ import annotations

from harle.orchestrator.planner import (
    Plan,
    PlanStep,
    classify_complexity,
    extract_plan_revisions,
    format_plan_for_injection,
    format_plan_for_vault,
    validate_plan,
)


class TestClassifyComplexity:
    def test_short_greeting_is_simple(self) -> None:
        assert classify_complexity("hi") == "simple"

    def test_what_is_question_short_is_simple(self) -> None:
        assert classify_complexity("what is Python?") == "simple"

    def test_research_long_is_complex(self) -> None:
        msg = (
            "Please research privacy solutions for our L2 architecture, compare "
            "ZK rollups with FHE approaches, and produce a structured report with "
            "sources from the dataset and the web."
        )
        assert classify_complexity(msg) == "complex"

    def test_empty_is_simple(self) -> None:
        assert classify_complexity("") == "simple"

    def test_multiple_questions_boosts_complexity(self) -> None:
        # Avoid leading "what is" / simple-prefix patterns so multi-? scoring applies.
        msg = (
            "Can you compare X and Y? What about Z? I need a detailed analysis "
            "with sources."
        )
        assert classify_complexity(msg) == "complex"


class TestValidatePlan:
    def test_valid_plan(self) -> None:
        raw = """1. [search] Find notes on auth
2. [web_search] Look up OAuth2
3. [synthesize] Compare approaches
4. [output] Write summary"""
        plan = validate_plan(raw)
        assert plan is not None
        assert len(plan.steps) == 4
        assert plan.steps[0].intent == "search"
        assert plan.steps[-1].intent == "output"

    def test_empty_returns_none(self) -> None:
        assert validate_plan("") is None

    def test_too_few_steps_returns_none(self) -> None:
        raw = "1. [output] Only one step"
        assert validate_plan(raw) is None

    def test_too_many_steps_returns_none(self) -> None:
        lines = "\n".join(f"{i}. [output] Step {i}" for i in range(1, 12))
        assert validate_plan(lines) is None

    def test_no_numbered_steps_returns_none(self) -> None:
        assert validate_plan("Just some prose without structure.") is None


class TestFormatPlanForInjection:
    def test_contains_plan_and_revision_instruction(self) -> None:
        plan = Plan(
            steps=[
                PlanStep(1, "search", "Query dataset"),
                PlanStep(2, "output", "Answer"),
            ],
            raw_text="1. [search] Query dataset\n2. [output] Answer",
        )
        out = format_plan_for_injection(plan)
        assert "Execution Plan" in out
        assert "REVISED PLAN" in out
        assert "[search]" in out


class TestExtractPlanRevisions:
    def test_extracts_one_revision(self) -> None:
        text = """Here is the answer.

REVISED PLAN:
1. [output] New approach
"""
        revs = extract_plan_revisions(text)
        assert len(revs) == 1
        assert "[output]" in revs[0]

    def test_no_revision_returns_empty(self) -> None:
        assert extract_plan_revisions("No revision here.") == []

    def test_case_insensitive_header(self) -> None:
        text = "Done.\n\nrevised plan:\n1. [output] X\n"
        assert len(extract_plan_revisions(text)) == 1


class TestFormatPlanForVault:
    def test_initial_and_revisions(self) -> None:
        s = format_plan_for_vault(
            "1. [search] A\n2. [output] B",
            ["1. [output] C"],
        )
        assert "Initial plan" in s
        assert "Revision 1" in s

    def test_includes_planning_tool_context(self) -> None:
        s = format_plan_for_vault(
            "1. [output] X",
            None,
            planning_tool_context="## Planning phase\n\nbody",
        )
        assert "Planning tool outputs" in s
        assert "body" in s
