"""Level 4 reflection and self-critique — trigger, critic LLM, improvement pass."""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from harle.debug import etrace

logger = logging.getLogger(__name__)

_REFLECTION_SYSTEM = """You are a quality reviewer for an AI assistant's output. Your task is to evaluate \
whether the assistant's response adequately addresses the user's request.

## Evaluation criteria

Review the draft response against the original request. Check each criterion:

1. **Completeness:** Does it answer the actual question? Are all parts of the request addressed?
2. **Evidence:** Are claims supported by data gathered during the run? Are there unsupported assertions?
3. **Gaps:** Is there information the user likely needs that was not included? Were there tools available \
that should have been called but were not?
4. **Accuracy:** Are there factual inconsistencies or contradictions within the response?
5. **Clarity:** Is the response well-structured and easy to follow?

## Output format

Respond with a JSON object only (no markdown fences):

{"verdict": "pass" | "improve", "assessment": "Brief overall assessment (1-2 sentences)", \
"improvements": ["specific improvement 1", "specific improvement 2"]}

If the response is adequate, set verdict to "pass" and leave improvements empty.
If improvements are needed, set verdict to "improve" and list SPECIFIC, ACTIONABLE improvements. \
Do not suggest improvements that would require information the assistant cannot obtain.
"""


def _build_reflection_user_content(user_message: str, draft_result: str) -> str:
    return f"""## Original user request

{user_message}

## Assistant's draft response

{draft_result}
"""


def _parse_reflection_json(raw: str) -> dict[str, object] | None:
    """Parse reflection JSON from model output; strips optional markdown fences."""
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*([\s\S]*?)```", text)
    if fence:
        text = fence.group(1).strip()
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


@dataclass(frozen=True)
class ReflectionConfig:
    """Parsed reflection settings for orchestrator runs."""

    enabled: bool
    model: str | None
    min_tool_calls: int
    trigger_keywords: tuple[str, ...]
    trigger_roles: tuple[str, ...]
    improvement_max_turns: int | None

    @staticmethod
    def from_settings_strings(
        *,
        enabled: bool,
        model: str | None,
        min_tool_calls: int,
        trigger_keywords_csv: str,
        trigger_roles_csv: str,
        improvement_max_turns: int | None,
    ) -> ReflectionConfig:
        """Build from :class:`~harle.config.Settings` string fields."""
        kw = _split_csv(trigger_keywords_csv)
        roles = _split_csv(trigger_roles_csv)
        return ReflectionConfig(
            enabled=enabled,
            model=model,
            min_tool_calls=min_tool_calls,
            trigger_keywords=tuple(kw),
            trigger_roles=tuple(r.lower() for r in roles),
            improvement_max_turns=improvement_max_turns,
        )


def _split_csv(s: str) -> list[str]:
    parts = [p.strip().lower() for p in s.split(",") if p.strip()]
    return parts


@dataclass(frozen=True)
class ReflectionVerdict:
    """Structured output of the reflection LLM call."""

    verdict: str  # "pass" or "improve"
    assessment: str
    improvements: tuple[str, ...]


@dataclass(frozen=True)
class ReflectionRunRecord:
    """Metadata for vault logging and API (single run)."""

    trigger_reason: str
    tool_count_at_trigger: int
    verdict: str | None
    assessment: str | None
    improvements_suggested: tuple[str, ...]
    improvement_pass_ran: bool
    improvement_pass_completed: bool
    improvement_turns: int | None
    improvement_tools_called: tuple[str, ...]


def should_reflect(
    *,
    user_message: str,
    tools_called: list[str],
    routing_method: str | None,
    agent_role: str,
    config: ReflectionConfig,
) -> tuple[bool, str]:
    """Determine whether a reflection pass should run (OR logic).

    Returns:
        Tuple of (should_reflect, trigger_reason) for logging.
    """
    if not config.enabled:
        return False, "disabled"

    role_l = agent_role.strip().lower()
    routing = (routing_method or "direct").strip().lower()
    msg_l = user_message.lower()

    if len(tools_called) >= config.min_tool_calls:
        return True, "tool_count"

    if config.trigger_keywords:
        for kw in config.trigger_keywords:
            if kw and kw in msg_l:
                return True, f"keyword:{kw}"

    if routing == "planned":
        return True, "planned"

    if config.trigger_roles and role_l in config.trigger_roles:
        return True, f"role:{agent_role}"

    return False, "no_match"


def run_reflection(
    *,
    user_message: str,
    draft_result: str,
    model: str,
) -> ReflectionVerdict:
    """Run the reflection critic (no tools, single turn). Fail-open on parse errors."""
    from agents import Agent, Runner

    agent = Agent(
        name="reflection",
        instructions=_REFLECTION_SYSTEM,
        tools=[],
        model=model,
    )
    user_content = _build_reflection_user_content(user_message, draft_result)

    try:
        with etrace.span(
            "Reflection call",
            level=etrace.STEP,
            module="orchestrator",
        ):
            result = Runner.run_sync(agent, user_content, max_turns=1)
    except Exception as exc:
        logger.warning("Reflection call failed: %s", exc, exc_info=True)
        etrace.detail(
            "Reflection call error",
            module="orchestrator",
            error_type=type(exc).__name__,
        )
        return ReflectionVerdict(verdict="pass", assessment="", improvements=())

    raw = getattr(result, "final_output", None)
    if not raw or not str(raw).strip():
        logger.warning("Reflection call returned empty output; treating as pass")
        return ReflectionVerdict(verdict="pass", assessment="", improvements=())

    parsed = _parse_reflection_json(str(raw))
    if parsed is None:
        logger.warning(
            "Reflection output not valid JSON; treating as pass. Raw: %.200s",
            raw,
        )
        return ReflectionVerdict(verdict="pass", assessment="", improvements=())

    verdict_raw = parsed.get("verdict")
    verdict = str(verdict_raw).strip().lower() if verdict_raw is not None else "pass"
    if verdict not in {"pass", "improve"}:
        verdict = "pass"

    assessment = str(parsed.get("assessment", "") or "").strip()
    improvements: list[str] = []
    imp = parsed.get("improvements")
    if isinstance(imp, list):
        improvements = [str(x).strip() for x in imp if str(x).strip()]

    etrace.detail(
        "Reflection call",
        module="orchestrator",
        verdict=verdict,
        improvements_count=len(improvements),
    )

    return ReflectionVerdict(
        verdict=verdict,
        assessment=assessment,
        improvements=tuple(improvements),
    )


def _build_improvement_instructions(
    *,
    base_instructions: str,
    user_message: str,
    draft_result: str,
    improvements: list[str],
) -> str:
    numbered = "\n".join(f"{i + 1}. {item}" for i, item in enumerate(improvements))
    preamble = f"""## Reflection feedback — improvements required

The following improvements were identified by quality review. Incorporate \
them into your response:

{numbered}

## Original user request

{user_message}

## Your previous draft

{draft_result}

Produce an improved version of the response that addresses the feedback above.
You may call tools if additional information is needed.
"""
    return f"{preamble}\n\n{base_instructions}"


def run_improvement(
    *,
    user_message: str,
    draft_result: str,
    improvements: list[str],
    base_instructions: str,
    tools: list[object],
    model: str,
    max_turns: int,
) -> tuple[str | None, list[str], int]:
    """Run one improvement pass with the same tools as execution.

    Returns:
        Tuple of (improved text or None on failure, tool names called, turns used).
    """
    from agents import Agent, MaxTurnsExceeded, Runner

    from harle.orchestrator.sdk_result import extract_run_metadata

    if not improvements:
        return None, [], 0

    instr = _build_improvement_instructions(
        base_instructions=base_instructions,
        user_message=user_message,
        draft_result=draft_result,
        improvements=improvements,
    )
    agent = Agent(
        name="improvement",
        instructions=instr,
        tools=tools,
        model=model,
    )

    try:
        with etrace.span(
            "Improvement pass",
            level=etrace.STEP,
            module="orchestrator",
        ):
            result = Runner.run_sync(agent, user_message, max_turns=max_turns)
    except MaxTurnsExceeded:
        logger.warning(
            "Improvement pass exceeded max_turns=%d; keeping draft",
            max_turns,
        )
        etrace.detail(
            "Improvement pass failed",
            module="orchestrator",
            status="failed",
            reason="max_turns",
        )
        return None, [], max_turns
    except Exception as exc:
        logger.warning("Improvement pass failed: %s", exc, exc_info=True)
        etrace.detail(
            "Improvement pass error",
            module="orchestrator",
            error_type=type(exc).__name__,
        )
        return None, [], 0

    tools_called, turns_used = extract_run_metadata(result)
    out = getattr(result, "final_output", None)
    text = str(out).strip() if out else ""
    if not text:
        return None, tools_called, turns_used

    etrace.detail(
        "Improvement pass",
        module="orchestrator",
        status="completed",
        turns_used=turns_used,
        tools_called=len(tools_called),
    )
    return text, tools_called, turns_used


def apply_reflection_pipeline(
    *,
    user_message: str,
    draft_text: str,
    merged_tools: list[str],
    routing_method: str | None,
    agent_role: str,
    base_instructions: str,
    tools: list[object],
    execution_model: str,
    reflection_config: ReflectionConfig,
    reflection_model_override: str | None,
    max_iterations_default: int,
) -> tuple[str, list[str], bool, bool, ReflectionRunRecord | None]:
    """After execution, optionally run reflection and at most one improvement pass.

    Returns:
        Tuple of (final text, merged tool names including improvement,
        reflection_triggered, reflection_improved, record for vault).
    """
    triggered, reason = should_reflect(
        user_message=user_message,
        tools_called=merged_tools,
        routing_method=routing_method,
        agent_role=agent_role,
        config=reflection_config,
    )
    etrace.detail(
        "Reflection trigger evaluated",
        module="orchestrator",
        triggered=triggered,
        reason=reason,
    )

    if not triggered:
        return draft_text, merged_tools, False, False, None

    count_at_trigger = len(merged_tools)
    r_model = reflection_model_override or reflection_config.model or execution_model
    verdict = run_reflection(
        user_message=user_message,
        draft_result=draft_text,
        model=r_model,
    )

    if verdict.verdict != "improve" or not verdict.improvements:
        record = ReflectionRunRecord(
            trigger_reason=reason,
            tool_count_at_trigger=count_at_trigger,
            verdict=verdict.verdict,
            assessment=verdict.assessment,
            improvements_suggested=verdict.improvements,
            improvement_pass_ran=False,
            improvement_pass_completed=False,
            improvement_turns=None,
            improvement_tools_called=(),
        )
        return draft_text, merged_tools, True, False, record

    imp_cap = reflection_config.improvement_max_turns
    imp_turns = imp_cap if imp_cap is not None else max_iterations_default

    improved, imp_tools, imp_turn_used = run_improvement(
        user_message=user_message,
        draft_result=draft_text,
        improvements=list(verdict.improvements),
        base_instructions=base_instructions,
        tools=tools,
        model=execution_model,
        max_turns=imp_turns,
    )

    merged_out = list(dict.fromkeys([*merged_tools, *imp_tools]))
    completed = improved is not None and bool(improved.strip())

    record = ReflectionRunRecord(
        trigger_reason=reason,
        tool_count_at_trigger=count_at_trigger,
        verdict=verdict.verdict,
        assessment=verdict.assessment,
        improvements_suggested=tuple(verdict.improvements),
        improvement_pass_ran=True,
        improvement_pass_completed=completed,
        improvement_turns=imp_turn_used,
        improvement_tools_called=tuple(imp_tools),
    )

    if completed:
        return improved.strip(), merged_out, True, True, record
    return draft_text, merged_out, True, False, record


def format_reflection_for_vault(
    *,
    triggered: bool,
    record: ReflectionRunRecord | None,
    min_tool_calls: int,
) -> str:
    """Build the ``## Reflection`` markdown section for vault result logs."""
    if not triggered or record is None:
        return ""

    lines = [
        "**Triggered:** yes",
        (
            f"**Trigger reason:** {record.trigger_reason} "
            f"({record.tool_count_at_trigger} tool call(s); threshold {min_tool_calls})"
            if record.trigger_reason == "tool_count"
            else f"**Trigger reason:** {record.trigger_reason}"
        ),
    ]
    if record.verdict is not None:
        lines.append(f"**Verdict:** {record.verdict}")
    if record.assessment:
        lines.append(f"**Assessment:** {record.assessment}")

    if record.improvements_suggested:
        lines.append("**Improvements suggested:**")
        for i, imp in enumerate(record.improvements_suggested, start=1):
            lines.append(f"{i}. {imp}")

    if record.improvement_pass_ran:
        if record.improvement_pass_completed:
            tools_n = len(record.improvement_tools_called)
            turns = record.improvement_turns
            lines.append(
                f"**Improvement pass:** completed ({turns} turns, {tools_n} tool call(s))"
            )
        else:
            lines.append("**Improvement pass:** failed or skipped (draft kept)")

    return "\n".join(lines) + "\n"
