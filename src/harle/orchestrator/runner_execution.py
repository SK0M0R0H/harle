"""Agents SDK runner loop with optional Level 3 planning."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Callable

from harle.debug import etrace
from harle.orchestrator.planner import (
    classify_complexity,
    extract_plan_revisions,
    format_plan_for_injection,
    generate_plan,
)
from harle.orchestrator.sdk_result import extract_run_metadata
from harle.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ROLE = "researcher"


@dataclass(frozen=True)
class AgentExecutionResult:
    """Result from the Agents SDK runner (with optional planning)."""

    text: str
    tools_called: list[str] = field(default_factory=list)
    turns_used: int = 0
    plan_text: str | None = None
    plan_revisions: list[str] | None = None
    planning_tool_context: str | None = None
    routing_method: str | None = None


def run_agent_execution(
    *,
    user_message: str,
    system_prompt: str | None,
    build_instructions: Callable[[str | None, bool], str],
    tool_registry: ToolRegistry | None,
    model: str,
    max_iterations: int,
    planning_enabled: bool,
    planning_model: str | None,
    planning_max_turns: int,
    planned_max_turns: int | None,
) -> AgentExecutionResult:
    """Execute via the Agents SDK Runner with optional plan-then-execute.

    Args:
        user_message: User message for the agent.
        system_prompt: Assembled context (P0--P4) from the context assembler.
        build_instructions: Callable ``(system_prompt, has_tools) -> str`` that
            builds full instructions including tool skills.
        tool_registry: Optional registry for SDK tools.
        model: Execution model name.
        max_iterations: Default max turns for the execution loop.
        planning_enabled: When ``False``, skip planning (Level 2 only).
        planning_model: Model for planning; ``None`` means same as *model*.
        planning_max_turns: Max turns for the planning agent's tool loop.
        planned_max_turns: Max turns for execution when a plan exists; ``None``
            means use *max_iterations*.

    Returns:
        :class:`AgentExecutionResult` with optional plan metadata.
    """
    from agents import Agent, MaxTurnsExceeded, Runner

    tools: list[object] = []
    if tool_registry:
        all_tool_names = tool_registry.list_all_tools()
        tools = tool_registry.get_agent_tools(all_tool_names)

    base_instructions = build_instructions(system_prompt, bool(tools))
    max_turns = max_iterations
    plan = None
    plan_tools: list[str] = []
    planning_tool_context = ""
    routing_method = "direct"

    if planning_enabled:
        try:
            complexity = classify_complexity(user_message)
        except Exception as exc:
            logger.warning(
                "Complexity classifier failed; falling back to Level 2: %s",
                exc,
                exc_info=True,
            )
            etrace.detail(
                "Complexity classifier error",
                module="orchestrator",
                error_type=type(exc).__name__,
            )
            complexity = "simple"

        etrace.detail(
            "Complexity classified",
            module="orchestrator",
            complexity=complexity,
        )

        if complexity == "complex":
            pm = planning_model or model
            plan, plan_tools, planning_tool_context = generate_plan(
                user_message=user_message,
                base_instructions=base_instructions,
                model=pm,
                tools=tools,
                max_turns=planning_max_turns,
            )
            injection_blocks: list[str] = []
            if plan is not None:
                injection_blocks.append(format_plan_for_injection(plan))
                max_turns = planned_max_turns if planned_max_turns is not None else max_iterations
                routing_method = "planned"
                etrace.step(
                    "Plan generated",
                    module="orchestrator",
                    steps=len(plan.steps),
                )
            else:
                etrace.detail(
                    "Planning failed, falling back to Level 2",
                    module="orchestrator",
                )
            ctx = planning_tool_context.strip()
            if ctx:
                injection_blocks.append(ctx)
            if injection_blocks:
                base_instructions = (
                    "\n\n".join(injection_blocks) + "\n\n" + base_instructions
                )

    etrace.detail(
        "Agent execution started",
        module="orchestrator",
        model=model,
        max_turns=max_turns,
        has_tools=bool(tool_registry),
        routing_method=routing_method,
    )

    agent = Agent(
        name=DEFAULT_AGENT_ROLE,
        instructions=base_instructions,
        tools=tools,
        model=model,
    )

    try:
        result = Runner.run_sync(agent, user_message, max_turns=max_turns)
    except MaxTurnsExceeded:
        logger.warning(
            "Agent exceeded max_turns=%d for message: %.80s",
            max_turns,
            user_message,
        )
        return AgentExecutionResult(
            text=(
                "I used all available reasoning steps but could not "
                "finish.  Please try a more specific request or "
                "increase the iteration limit."
            ),
            tools_called=plan_tools,
            turns_used=max_turns,
            plan_text=plan.raw_text if plan else None,
            plan_revisions=None,
            planning_tool_context=planning_tool_context or None,
            routing_method=routing_method,
        )

    exec_tools, turns_used = extract_run_metadata(result)
    merged_tools = list(dict.fromkeys([*plan_tools, *exec_tools]))

    text = result.final_output
    if plan is not None:
        revisions = extract_plan_revisions(text)
        plan_revisions = revisions if revisions else None
    else:
        plan_revisions = None

    return AgentExecutionResult(
        text=text,
        tools_called=merged_tools,
        turns_used=turns_used,
        plan_text=plan.raw_text if plan else None,
        plan_revisions=plan_revisions,
        planning_tool_context=planning_tool_context or None,
        routing_method=routing_method,
    )
