"""Multi-agent definitions: roles, handoffs, and Agents SDK Agent graph."""

from __future__ import annotations

import logging
from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Any, Callable

from pydantic import BaseModel, Field

from harle.debug import etrace
from harle.orchestrator.model_tier import ModelTierConfig
from harle.orchestrator.role_tool_modules import DEFAULT_ROLE_TOOL_MODULES

if TYPE_CHECKING:
    from agents import Agent

logger = logging.getLogger(__name__)

KNOWN_ROLES: tuple[str, ...] = (
    "assistant",
    "researcher",
    "secretary",
    "specialist",
    "writer",
)

# Module names as registered in ToolRegistry (see tools/factory.py).
# Built-in defaults; runtime overrides come from JSON via ``get_role_tool_modules()``.
ROLE_TOOL_MODULES = DEFAULT_ROLE_TOOL_MODULES

# Declared handoff targets per role (SDK Runner carries conversation across handoffs).
# Complete graph: any role may hand off to any other role (not to self).
HANDOFF_GRAPH: dict[str, list[str]] = {
    r: [t for t in KNOWN_ROLES if t != r] for r in KNOWN_ROLES
}


class HandoffReason(BaseModel):
    """Structured input the model must provide when invoking a handoff."""

    reason: str = Field(
        ...,
        description="Short explanation of why you are handing off to the other agent.",
    )


@dataclass(frozen=True)
class HandoffRecord:
    """One handoff event for run logging."""

    source_agent: str
    target_agent: str
    reason: str


def tool_names_for_role(
    registry: Any,
    role: str,
    *,
    role_tool_modules: dict[str, list[str]] | None = None,
) -> list[str]:
    """Collect registered tool function names allowed for *role*."""
    from harle.tools.registry import ToolRegistry

    if not isinstance(registry, ToolRegistry):
        return []
    mapping = role_tool_modules if role_tool_modules is not None else DEFAULT_ROLE_TOOL_MODULES
    modules = mapping.get(role, [])
    names: list[str] = []
    for mod in modules:
        names.extend(registry.get_module_tool_names(mod))
    # Preserve stable order, dedupe
    return list(dict.fromkeys(names))


def build_role_instructions(
    *,
    base_system_prompt: str,
    tool_registry: Any,
    tool_names: list[str],
    thinking_instruction: str,
) -> str:
    """Merge P0/system text, tool skills for *tool_names*, and thinking hint."""
    from harle.tools.registry import ToolRegistry

    parts = [base_system_prompt]
    if tool_names and isinstance(tool_registry, ToolRegistry):
        skills = tool_registry.get_skills_for_tools(tool_names)
        if skills:
            skill_sections = [
                f"## Tool Skill: {s.name}\n\n{s.content}" for s in skills
            ]
            parts.append("\n\n".join(skill_sections))
    parts.append(thinking_instruction)
    return "\n\n".join(parts)


def _append_handoff_record(
    records: list[HandoffRecord],
    *,
    source: str,
    target: str,
) -> Callable[..., None]:
    def _on_handoff(_ctx: Any, input_data: HandoffReason | None = None) -> None:
        reason = ""
        if input_data is not None:
            reason = (input_data.reason or "").strip()
        records.append(
            HandoffRecord(source_agent=source, target_agent=target, reason=reason),
        )
        etrace.detail(
            "Handoff recorded",
            module="orchestrator",
            source_agent=source,
            target_agent=target,
            has_reason=bool(reason),
        )

    return _on_handoff


def build_execution_agents(
    *,
    model_tier_config: ModelTierConfig,
    tool_registry: Any,
    role_instructions: dict[str, str],
    handoff_records_out: list[HandoffRecord],
    handoff_prompt_prefix: str,
    role_tool_modules: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Build one Agents SDK :class:`~agents.Agent` per role with handoffs wired.

    Handoffs form a directed graph with cycles; we re-wire iteratively so each
    :func:`handoff` captures the latest target :class:`~agents.Agent` (SDK returns
    that object when a handoff runs).

    Args:
        model_tier_config: Tier mapping; handoff agents use the executor tier.
        tool_registry: :class:`~harle.tools.registry.ToolRegistry`.
        role_instructions: Full instruction string per role (P0 or assembled).
        handoff_records_out: Mutable list; ``on_handoff`` appends :class:`HandoffRecord`.
        handoff_prompt_prefix: e.g. :data:`agents.extensions.handoff_prompt.RECOMMENDED_PROMPT_PREFIX`.
        role_tool_modules: Per-role tool module allowlist; ``None`` uses built-in defaults.

    Returns:
        Mapping ``role_name -> Agent`` for all :data:`KNOWN_ROLES`.
    """
    from agents import Agent, handoff

    exec_model = model_tier_config.executor

    agents: dict[str, Any] = {}
    for role in KNOWN_ROLES:
        text = role_instructions.get(role, "").strip() or (
            f"You are the {role} agent for Harle. Follow the user's request."
        )
        full_instructions = f"{handoff_prompt_prefix}\n\n{text}" if handoff_prompt_prefix else text
        tool_names = tool_names_for_role(
            tool_registry,
            role,
            role_tool_modules=role_tool_modules,
        )
        tools = (
            tool_registry.get_agent_tools(tool_names)
            if tool_registry and tool_names
            else []
        )
        agents[role] = Agent(
            name=role,
            instructions=full_instructions,
            tools=tools,
            model=exec_model,
            handoffs=[],
        )

    # Fixed-point: circular handoffs must reference updated Agent instances.
    for _ in range(len(KNOWN_ROLES)):
        for role in KNOWN_ROLES:
            targets = HANDOFF_GRAPH.get(role, [])
            ho: list[Any] = []
            for target in targets:
                if target not in agents:
                    continue
                ho.append(
                    handoff(
                        agent=agents[target],
                        on_handoff=_append_handoff_record(
                            handoff_records_out,
                            source=role,
                            target=target,
                        ),
                        input_type=HandoffReason,
                    ),
                )
            agents[role] = replace(agents[role], handoffs=ho)

    return agents


def final_agent_from_handoffs(
    starting_role: str,
    handoffs: list[HandoffRecord],
) -> str:
    """Return the agent that produced the final output (last handoff target or starting role)."""
    if not handoffs:
        return starting_role
    return handoffs[-1].target_agent
