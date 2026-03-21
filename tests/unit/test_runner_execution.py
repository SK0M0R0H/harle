"""Tests for :mod:`harle.orchestrator.runner_execution` planning + multi-agent wiring."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from harle.orchestrator.model_tier import ComplexExecutionTier, ModelTierConfig
from harle.orchestrator.planner import Plan, PlanStep, RequestComplexity


def test_planning_injection_prepends_all_multi_agent_roles(monkeypatch: pytest.MonkeyPatch) -> None:
    """Plan + planning tool context must appear in every handoff target's instructions."""
    from harle.orchestrator import runner_execution as re

    plan = Plan(
        steps=[PlanStep(1, "output", "finish")],
        raw_text="1. [output] finish",
    )

    monkeypatch.setattr(
        re,
        "classify_complexity",
        lambda m: RequestComplexity.COMPLEX,
    )
    monkeypatch.setattr(re, "generate_plan", lambda **k: (plan, [], "", 0))

    captured: dict[str, object] = {}

    class _NA:
        name = "n"

    def fake_build(**kwargs: object) -> dict[str, object]:
        captured["role_instructions"] = dict(kwargs["role_instructions"])  # type: ignore[arg-type]
        return {"researcher": _NA(), "writer": _NA()}

    monkeypatch.setattr(re, "build_execution_agents", fake_build)

    class FakeResult:
        final_output = "done"
        new_items: list[object] = []
        raw_responses = [object()]

    import agents as agents_mod

    monkeypatch.setattr(
        agents_mod.Runner,
        "run_sync",
        staticmethod(lambda *a, **k: FakeResult()),
    )

    tr = MagicMock()
    tr.list_all_tools.return_value = ["t1"]
    tr.get_agent_tools.return_value = []

    role_instructions = {"researcher": "R0", "writer": "W0"}

    tier = ModelTierConfig(
        classifier="mini",
        planner="plan-model",
        executor="exec-model",
    )

    re.run_agent_execution(
        user_message="long research query with enough complexity",
        system_prompt="sys",
        build_instructions=lambda sp, ht: "BASE",
        tool_registry=tr,
        model_tier_config=tier,
        complex_execution_tier=ComplexExecutionTier.EXECUTOR,
        reflection_critic_model="plan-model",
        max_iterations=5,
        planning_enabled=True,
        planning_max_turns=3,
        planned_max_turns=None,
        agent_role="researcher",
        multi_agent=True,
        role_instructions=role_instructions,
        reflection_config=None,
    )

    ri = captured["role_instructions"]
    assert isinstance(ri, dict)
    assert str(ri["researcher"]).startswith("## Execution Plan")
    assert str(ri["writer"]).startswith("## Execution Plan")
    assert "R0" in str(ri["researcher"])
    assert "W0" in str(ri["writer"])
