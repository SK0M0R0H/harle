"""Agents SDK runner loop with optional Level 3 planning."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field, replace
from typing import Callable

from harle.debug import etrace
from harle.orchestrator.model_tier import ComplexExecutionTier, ModelTierConfig
from harle.orchestrator.planner import (
    RequestComplexity,
    classify_complexity,
    extract_plan_revisions,
    format_plan_for_injection,
    generate_plan,
)
from harle.orchestrator.reflection import (
    ReflectionConfig,
    ReflectionRunRecord,
    apply_reflection_pipeline,
)
from harle.orchestrator.agents import (
    HandoffRecord,
    build_execution_agents,
    final_agent_from_handoffs,
    tool_names_for_role,
)
from harle.orchestrator.role_tool_modules import DEFAULT_ROLE_TOOL_MODULES
from harle.orchestrator.sdk_result import (
    count_tool_call_invocations,
    extract_handoff_metadata,
    extract_run_metadata,
)
from harle.tools.registry import ToolRegistry

logger = logging.getLogger(__name__)

DEFAULT_AGENT_ROLE = "assistant"


@dataclass(frozen=True)
class AgentExecutionResult:
    """Result from the Agents SDK runner (with optional planning)."""

    text: str
    tools_called: list[str] = field(default_factory=list)
    #: Main execution ``Runner`` turn estimate (``extract_run_metadata``) plus
    #: reflection critic and improvement passes when Level 4 runs. Planning-agent
    #: turns are not included (separate ``Runner``).
    turns_used: int = 0
    plan_text: str | None = None
    plan_revisions: list[str] | None = None
    planning_tool_context: str | None = None
    routing_method: str | None = None
    reflection_triggered: bool | None = None
    reflection_improved: bool | None = None
    reflection_record: ReflectionRunRecord | None = None
    handoffs: list[HandoffRecord] | None = None
    final_agent: str | None = None
    models_used: dict[str, str] = field(default_factory=dict)


def run_agent_execution(
    *,
    user_message: str,
    system_prompt: str | None,
    build_instructions: Callable[[str | None, bool], str],
    tool_registry: ToolRegistry | None,
    model_tier_config: ModelTierConfig,
    complex_execution_tier: ComplexExecutionTier,
    reflection_critic_model: str,
    max_iterations: int,
    planning_enabled: bool,
    planning_max_turns: int,
    planned_max_turns: int | None,
    reflection_config: ReflectionConfig | None = None,
    agent_role: str = DEFAULT_AGENT_ROLE,
    multi_agent: bool = False,
    role_instructions: dict[str, str] | None = None,
    handoff_records_out: list[HandoffRecord] | None = None,
    routing_method_from_router: str | None = None,
    role_tool_modules: dict[str, list[str]] | None = None,
) -> AgentExecutionResult:
    """Execute via the Agents SDK Runner with optional plan-then-execute.

    Args:
        user_message: User message for the agent.
        system_prompt: Assembled context (P0--P4) from the context assembler.
        build_instructions: Callable ``(system_prompt, has_tools) -> str`` that
            builds full instructions including tool skills.
        tool_registry: Optional registry for SDK tools.
        model_tier_config: Resolved classifier / planner / executor models.
        complex_execution_tier: When :attr:`RequestComplexity.COMPLEX`, use
            :attr:`ComplexExecutionTier.PLANNER` to run execution on the planner model.
        reflection_critic_model: Model for the reflection critic (Level 4).
        max_iterations: Default max turns for the execution loop.
        planning_enabled: When ``False``, skip planning (Level 2 only).
        planning_max_turns: Max turns for the planning agent's tool loop.
        planned_max_turns: Max turns for execution when a plan exists; ``None``
            means use *max_iterations*.
        reflection_config: Level 4 reflection settings; ``None`` skips reflection.
        agent_role: Role name for reflection triggers (e.g. ``researcher``).
        multi_agent: When ``True``, build a handoff graph via :func:`build_execution_agents`.
        role_instructions: Per-role instruction strings (including skills) for multi-agent mode.
        handoff_records_out: Mutable list populated by handoff callbacks.
        routing_method_from_router: Router method (``keyword_match``, ``default``, etc.).
        role_tool_modules: Per-role tool module allowlist; ``None`` uses built-in defaults.

    Returns:
        :class:`AgentExecutionResult` with optional plan metadata.
    """
    from agents import Agent, MaxTurnsExceeded, Runner

    rt_modules = role_tool_modules if role_tool_modules is not None else DEFAULT_ROLE_TOOL_MODULES

    tools: list[object] = []
    if tool_registry:
        all_tool_names = tool_registry.list_all_tools()
        tools = tool_registry.get_agent_tools(all_tool_names)

    routing_method = routing_method_from_router or "direct"

    base_instructions = build_instructions(system_prompt, bool(tools))
    max_turns = max_iterations
    plan = None
    plan_tools: list[str] = []
    plan_invocations = 0
    planning_tool_context = ""
    models_used: dict[str, str] = {}

    exec_model = model_tier_config.executor

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
            complexity = RequestComplexity.SIMPLE

        etrace.detail(
            "Complexity classified",
            module="orchestrator",
            complexity=complexity.value,
        )

        if complexity is RequestComplexity.COMPLEX:
            if complex_execution_tier is ComplexExecutionTier.PLANNER:
                exec_model = model_tier_config.planner
                etrace.detail(
                    "Complex execution tier boost",
                    module="orchestrator",
                    boost_to=ComplexExecutionTier.PLANNER.value,
                    model=exec_model,
                )

            pm = model_tier_config.planner
            etrace.detail(
                "Model tier resolved",
                module="orchestrator",
                phase="planning",
                tier="planner",
                model=pm,
                source="config",
            )
            plan, plan_tools, planning_tool_context, plan_invocations = generate_plan(
                user_message=user_message,
                base_instructions=base_instructions,
                model=pm,
                tools=tools,
                max_turns=planning_max_turns,
            )
            models_used["planning"] = pm
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
                joined = "\n\n".join(injection_blocks) + "\n\n"
                base_instructions = joined + base_instructions
                # Handoff targets must see the plan and planning tool transcript too;
                # otherwise only the starting agent's instructions include them.
                if multi_agent and role_instructions:
                    for role_key in role_instructions:
                        role_instructions[role_key] = (
                            joined + role_instructions[role_key]
                        )

    tier_for_agents = replace(model_tier_config, executor=exec_model)
    etrace.detail(
        "Model tier resolved",
        module="orchestrator",
        phase="execution",
        tier="executor" if exec_model == model_tier_config.executor else "planner",
        model=exec_model,
        source="config",
    )
    models_used["execution"] = exec_model
    models_used["handoff"] = tier_for_agents.executor

    etrace.detail(
        "Agent execution started",
        module="orchestrator",
        model=exec_model,
        max_turns=max_turns,
        has_tools=bool(tool_registry),
        routing_method=routing_method,
    )

    handoff_records: list[HandoffRecord] = []
    if handoff_records_out is not None:
        handoff_records_out.clear()
        handoff_records = handoff_records_out

    use_multi = (
        multi_agent
        and role_instructions
        and tool_registry is not None
        and len(role_instructions) > 0
    )

    if use_multi:
        try:
            from agents.extensions.handoff_prompt import RECOMMENDED_PROMPT_PREFIX
        except ImportError:
            RECOMMENDED_PROMPT_PREFIX = ""

        agents_map = build_execution_agents(
            model_tier_config=tier_for_agents,
            tool_registry=tool_registry,
            role_instructions=dict(role_instructions),
            handoff_records_out=handoff_records,
            handoff_prompt_prefix=RECOMMENDED_PROMPT_PREFIX,
            role_tool_modules=rt_modules,
        )
        agent = agents_map.get(agent_role) or Agent(
            name=agent_role,
            instructions=base_instructions,
            tools=tools,
            model=exec_model,
        )
    else:
        agent = Agent(
            name=agent_role,
            instructions=base_instructions,
            tools=tools,
            model=exec_model,
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
            reflection_triggered=None,
            reflection_improved=None,
            reflection_record=None,
            handoffs=None,
            final_agent=None,
            models_used=models_used,
        )

    exec_tools, turns_used = extract_run_metadata(result)
    exec_invocations = count_tool_call_invocations(result)
    tool_invocation_total = plan_invocations + exec_invocations
    merged_tools = list(dict.fromkeys([*plan_tools, *exec_tools]))

    text = result.final_output
    text_str = str(text).strip() if text else ""

    sdk_handoffs = extract_handoff_metadata(result)
    if not handoff_records and sdk_handoffs:
        handoff_records = [
            HandoffRecord(
                source_agent=h.get("source_agent", ""),
                target_agent=h.get("target_agent", ""),
                reason=h.get("reason", ""),
            )
            for h in sdk_handoffs
        ]
    final_agent_name = final_agent_from_handoffs(agent_role, handoff_records)

    reflection_triggered: bool | None = None
    reflection_improved: bool | None = None
    reflection_record: ReflectionRunRecord | None = None

    post_execution_turns = 0
    reflect_tools = tools
    reflect_base = base_instructions
    improvement_model = model_tier_config.executor
    if use_multi and tool_registry is not None:
        rt_names = tool_names_for_role(
            tool_registry,
            agent_role,
            role_tool_modules=rt_modules,
        )
        reflect_tools = tool_registry.get_agent_tools(rt_names)
        if role_instructions and agent_role in role_instructions:
            reflect_base = role_instructions[agent_role]

    if reflection_config is not None:
        etrace.detail(
            "Model tier resolved",
            module="orchestrator",
            phase="reflection",
            tier="planner",
            model=reflection_critic_model,
            source="config",
        )
        (
            text_str,
            merged_tools,
            reflection_triggered,
            reflection_improved,
            reflection_record,
            post_execution_turns,
        ) = apply_reflection_pipeline(
            user_message=user_message,
            draft_text=text_str,
            merged_tools=merged_tools,
            tool_invocation_count=tool_invocation_total,
            routing_method=routing_method,
            agent_role=agent_role,
            base_instructions=reflect_base,
            tools=reflect_tools,
            critic_model=reflection_critic_model,
            improvement_model=improvement_model,
            reflection_config=reflection_config,
            max_iterations_default=max_iterations,
        )
        if reflection_triggered:
            models_used["reflection"] = reflection_critic_model
        if reflection_record is not None and reflection_record.improvement_pass_ran:
            models_used["improvement"] = improvement_model

    if plan is not None:
        revisions = extract_plan_revisions(text_str)
        plan_revisions = revisions if revisions else None
    else:
        plan_revisions = None

    return AgentExecutionResult(
        text=text_str,
        tools_called=merged_tools,
        turns_used=turns_used + post_execution_turns,
        plan_text=plan.raw_text if plan else None,
        plan_revisions=plan_revisions,
        planning_tool_context=planning_tool_context or None,
        routing_method=routing_method,
        reflection_triggered=reflection_triggered,
        reflection_improved=reflection_improved,
        reflection_record=reflection_record,
        handoffs=handoff_records or None,
        final_agent=final_agent_name,
        models_used=dict(models_used),
    )
