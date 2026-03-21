"""Level 3 plan-then-execute: complexity classification and plan handling.

Heuristic complexity gating, tool-assisted planning via the Agents SDK,
plan validation, injection into execution instructions, and revision
extraction from agent output for run logging.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass

from harle.debug import etrace
from harle.orchestrator.sdk_result import (
    build_planning_tool_context_section,
    count_tool_call_invocations,
    extract_run_metadata,
)

logger = logging.getLogger(__name__)

# Complexity classifier
_COMPLEX_THRESHOLD = 4
_SIMPLE_MAX_LEN = 80

_COMPLEX_KEYWORDS = frozenset(
    {
        "research",
        "compare",
        "comparison",
        "analyze",
        "analysis",
        "report",
        "investigate",
        "investigation",
        "summarize",
        "synthesize",
        "evaluate",
        "review",
        "multi",
        "several",
        "sources",
        "dataset",
        "trello",
        "search the web",
        "web search",
        "look up",
        "check trello",
    }
)

_MULTI_STEP_PHRASES = (
    "first ",
    "then ",
    "after that",
    "step by step",
    "steps:",
    "following steps",
)

_SIMPLE_PREFIXES = (
    "what is ",
    "what are ",
    "who is ",
    "when did ",
    "where is ",
    "define ",
    "explain ",
    "hello",
    "hi ",
    "thanks",
)

_MIN_PLAN_STEPS = 2
_MAX_PLAN_STEPS = 10

_STEP_LINE_RE = re.compile(
    r"^\s*(\d+)\.\s*\[(\w+)\]\s+(.+?)\s*$",
    re.IGNORECASE,
)

_REVISION_HEADER_RE = re.compile(
    r"(?im)^\s*REVISED\s+PLAN\s*:?\s*",
)

_PLANNING_META_INSTRUCTIONS = """
You are a planning agent. Your job is to create an execution plan for the user's
request -- NOT to answer it directly.

You have access to tools. Use them to understand the situation before creating
your plan (e.g. search the dataset to see what information is available, check
Trello for relevant tasks, etc.). Keep tool use focused -- only gather what you
need to make a good plan.

When you are ready, output your final plan as a numbered list. Each step must
have an intent tag in brackets. Valid intents: search, web_search, trello,
read_file, synthesize, analyze, draft, output.
Format:
1. [intent] Description of what to do
2. [intent] Description of what to do
...
End with a step tagged [output] or [synthesize] for the final response.

Your final message must contain ONLY the plan -- no preamble, no explanation.
""".strip()


@dataclass(frozen=True)
class PlanStep:
    """A single step in an execution plan."""

    number: int
    intent: str
    description: str


@dataclass(frozen=True)
class Plan:
    """Validated execution plan from the planning agent."""

    steps: list[PlanStep]
    raw_text: str


def classify_complexity(message: str) -> str:
    """Classify request complexity as ``simple`` or ``complex`` using heuristics.

    Args:
        message: User message text.

    Returns:
        ``"simple"`` or ``"complex"``.
    """
    text = (message or "").strip().lower()
    if not text:
        return "simple"

    score = 0
    if len(text) > 150:
        score += 2
    elif len(text) > _SIMPLE_MAX_LEN:
        score += 1

    for kw in _COMPLEX_KEYWORDS:
        if kw in text:
            score += 2
            break

    for phrase in _MULTI_STEP_PHRASES:
        if phrase in text:
            score += 1
            break

    if text.count("?") >= 2:
        score += 2

    for prefix in _SIMPLE_PREFIXES:
        if text.startswith(prefix) and len(text) < 120:
            score -= 2
            break

    if len(text) <= _SIMPLE_MAX_LEN and "?" not in text:
        score -= 1

    return "complex" if score >= _COMPLEX_THRESHOLD else "simple"


def validate_plan(raw_output: str) -> Plan | None:
    """Parse and validate a raw plan string.

    Args:
        raw_output: Final assistant text from the planning agent.

    Returns:
        A :class:`Plan` if valid, otherwise ``None`` (caller falls back to
        Level 2 execution).
    """
    if not raw_output or not raw_output.strip():
        return None

    steps: list[PlanStep] = []
    for line in raw_output.splitlines():
        m = _STEP_LINE_RE.match(line)
        if not m:
            continue
        num_s, intent, desc = m.groups()
        try:
            num = int(num_s)
        except ValueError:
            continue
        steps.append(
            PlanStep(
                number=num,
                intent=intent.lower(),
                description=desc.strip(),
            )
        )

    if len(steps) < _MIN_PLAN_STEPS or len(steps) > _MAX_PLAN_STEPS:
        return None

    last_intent = steps[-1].intent
    if last_intent not in {"output", "synthesize"}:
        logger.warning(
            "Plan last step intent is %r (expected output or synthesize); accepting anyway",
            last_intent,
        )

    return Plan(steps=steps, raw_text=raw_output.strip())


def format_plan_for_injection(plan: Plan) -> str:
    """Format a validated plan for prepending to execution agent instructions.

    Args:
        plan: Validated plan.

    Returns:
        Markdown section to inject before the rest of the system instructions.
    """
    lines = [
        "## Execution Plan",
        "",
        "Follow this plan to answer the user's request. You may deviate if your "
        "findings make it necessary. If you revise the plan, output a section "
        'starting with "REVISED PLAN:" followed by the updated numbered steps.',
        "",
        plan.raw_text,
    ]
    return "\n".join(lines)


def extract_plan_revisions(output: str) -> list[str]:
    """Extract ``REVISED PLAN:`` blocks from agent final output.

    Args:
        output: Full assistant response text.

    Returns:
        List of revision bodies (text after each header), in order.
    """
    if not output or "REVISED PLAN" not in output.upper():
        return []

    parts = _REVISION_HEADER_RE.split(output)
    if len(parts) <= 1:
        return []

    revisions: list[str] = []
    for chunk in parts[1:]:
        text = chunk.strip()
        if text:
            revisions.append(text)
    return revisions


def build_planning_instructions(base_instructions: str) -> str:
    """Combine assembled agent instructions with planning meta-prompt.

    Args:
        base_instructions: Output of context assembly plus tool skills and
            thinking instruction (same as execution agent base).

    Returns:
        Full instructions string for the planning Agent.
    """
    return f"{base_instructions}\n\n{_PLANNING_META_INSTRUCTIONS}"


def generate_plan(
    *,
    user_message: str,
    base_instructions: str,
    model: str,
    tools: list[object],
    max_turns: int,
) -> tuple[Plan | None, list[str], str, int]:
    """Run the planning agent (with tools) and return a validated plan.

    On any failure (SDK error, empty output, validation failure), returns
    ``(None, [...], tool_context, 0)`` so the orchestrator can fall back to Level 2
    while still injecting *tool_context* (tool outputs from the planning run)
    when present.

    Args:
        user_message: Original user request.
        base_instructions: Same base as execution (system prompt + skills).
        model: Model name for the planning Agent.
        tools: SDK tool objects (same registry as execution).
        max_turns: Maximum turns for the planning loop.

    Returns:
        ``(validated Plan or None, unique tool names used during planning,
        markdown tool-context section or "", planning-phase tool invocation count)``.
    """
    from agents import Agent, MaxTurnsExceeded, Runner

    planning_instructions = build_planning_instructions(base_instructions)

    etrace.step(
        "Planning agent starting",
        module="orchestrator",
        model=model,
        max_turns=max_turns,
        tool_count=len(tools),
    )

    agent = Agent(
        name="planner",
        instructions=planning_instructions,
        tools=tools,
        model=model,
    )

    try:
        result = Runner.run_sync(agent, user_message, max_turns=max_turns)
    except MaxTurnsExceeded:
        logger.warning(
            "Planning agent exceeded max_turns=%d; falling back to Level 2",
            max_turns,
        )
        etrace.detail(
            "Planning max turns exceeded",
            module="orchestrator",
            max_turns=max_turns,
        )
        return None, [], "", 0
    except Exception as exc:
        logger.warning("Planning agent failed: %s", exc, exc_info=True)
        etrace.detail(
            "Planning agent error",
            module="orchestrator",
            error_type=type(exc).__name__,
        )
        return None, [], "", 0

    plan_tools, _plan_turns = extract_run_metadata(result)
    plan_invocations = count_tool_call_invocations(result)
    tool_context = build_planning_tool_context_section(result)

    raw = getattr(result, "final_output", None)
    if not raw or not str(raw).strip():
        etrace.detail("Planning empty output", module="orchestrator")
        return None, plan_tools, tool_context, plan_invocations

    plan = validate_plan(str(raw))
    if plan is None:
        etrace.detail("Plan validation failed", module="orchestrator")
        return None, plan_tools, tool_context, plan_invocations

    etrace.detail(
        "Planning tool context captured",
        module="orchestrator",
        chars=len(tool_context),
    )
    etrace.step(
        "Plan validated",
        module="orchestrator",
        steps=len(plan.steps),
    )
    return plan, plan_tools, tool_context, plan_invocations


def format_plan_for_vault(
    plan_text: str | None,
    plan_revisions: list[str] | None,
    planning_tool_context: str | None = None,
) -> str:
    """Build markdown for the ``## Plan`` section in vault result logs.

    Args:
        plan_text: Initial plan text, if any.
        plan_revisions: Extracted revision bodies, if any.
        planning_tool_context: Markdown from planning-phase tool outputs, if any.

    Returns:
        Markdown fragment (may be empty if no plan).
    """
    parts: list[str] = []
    if plan_text:
        parts.append("### Initial plan\n\n")
        parts.append(plan_text)
    if plan_revisions:
        for i, rev in enumerate(plan_revisions, start=1):
            parts.append(f"\n\n### Revision {i}\n\n")
            parts.append(rev)
    if planning_tool_context and planning_tool_context.strip():
        parts.append("\n\n### Planning tool outputs\n\n")
        parts.append(planning_tool_context.strip())
    return "".join(parts)
