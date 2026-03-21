"""Duck-typed helpers for OpenAI Agents SDK run results."""

from __future__ import annotations

import json
from typing import Any

# Cap injected planning tool transcript size (characters) to protect context budget.
_DEFAULT_PLANNING_TOOL_CONTEXT_MAX_CHARS: int = 16_000


def count_tool_call_invocations(result: object) -> int:
    """Count every tool invocation in an Agents SDK run result.

    Each ``tool_call_item`` in ``new_items`` increments the count, including
    repeated calls to the same tool name. Use this for thresholds (e.g.
    reflection min tool calls). For ordered unique names, see
    :func:`extract_run_metadata`.

    Args:
        result: SDK run result object.

    Returns:
        Number of tool calls (invocations), zero if none.
    """
    n = 0
    for item in getattr(result, "new_items", []):
        if getattr(item, "type", "") == "tool_call_item":
            n += 1
    return n


def extract_run_metadata(result: object) -> tuple[list[str], int]:
    """Extract tool names and turn count from an Agents SDK RunResult.

    Uses duck typing so callers do not import SDK item types directly.

    **Note:** Tool names are **deduplicated** (first occurrence order only).
    For invocation counts (e.g. three ``dataset_search`` calls), use
    :func:`count_tool_call_invocations`.

    Args:
        result: SDK run result object.

    Returns:
        Tuple of (unique tool names in order, turn count estimate).
    """
    tools: list[str] = []
    turns = 0
    for item in getattr(result, "new_items", []):
        item_type = getattr(item, "type", "")
        if item_type == "tool_call_item":
            raw = getattr(item, "raw_item", None)
            name = getattr(raw, "name", None)
            if name and name not in tools:
                tools.append(name)
        elif item_type == "message_output_item":
            turns += 1
    turns = max(turns, len(getattr(result, "raw_responses", [])))
    return tools, turns


def extract_handoff_metadata(result: object) -> list[dict[str, str]]:
    """Best-effort handoff events from an Agents SDK run result (duck-typed).

    Used to cross-check :class:`~harle.orchestrator.agents.HandoffRecord` entries
    from ``on_handoff`` callbacks.

    Returns:
        List of dicts with keys ``source_agent``, ``target_agent``, ``reason`` (may be empty).
    """
    out: list[dict[str, str]] = []
    for item in getattr(result, "new_items", []):
        item_type = getattr(item, "type", "")
        if item_type != "handoff_call_item":
            continue
        raw = getattr(item, "raw_item", None)
        name = getattr(raw, "name", None) if raw is not None else None
        if not isinstance(name, str) or not name.startswith("transfer_to_"):
            continue
        target = name.removeprefix("transfer_to_").strip()
        # Source is not always in the item; leave blank if unknown.
        out.append(
            {
                "source_agent": "",
                "target_agent": target,
                "reason": "",
            },
        )
    return out


def _tool_name_from_call_raw(raw: object) -> str:
    """Best-effort tool name from a tool call ``raw_item``."""
    if raw is None:
        return "tool"
    name = getattr(raw, "name", None)
    if isinstance(name, str) and name.strip():
        return name.strip()
    if isinstance(raw, dict):
        n = raw.get("name")
        if isinstance(n, str) and n.strip():
            return n.strip()
    return "tool"


def _stringify_tool_output(output: Any) -> str:
    """Render tool output for markdown injection."""
    if output is None:
        return ""
    if isinstance(output, str):
        return output
    if isinstance(output, (dict, list)):
        try:
            return json.dumps(output, ensure_ascii=False, indent=2, default=str)
        except (TypeError, ValueError):
            return str(output)
    return str(output)


def build_planning_tool_context_section(
    result: object,
    *,
    max_chars: int = _DEFAULT_PLANNING_TOOL_CONTEXT_MAX_CHARS,
) -> str:
    """Build markdown summarizing tool outputs from a completed planning run.

    The execution agent receives a **new** ``Runner.run_sync`` session, so it
    does not see the planner's tool messages. This extracts
    ``tool_call_output_item`` payloads from ``new_items`` (paired with preceding
    ``tool_call_item`` names) and formats them for injection into execution
    instructions.

    Args:
        result: SDK ``RunResult`` from the planning ``Runner.run_sync`` call.
        max_chars: Maximum size of the body (truncated with a notice if exceeded).

    Returns:
        Markdown section including a ``##`` heading, or empty string if no tool
        outputs were found.
    """
    chunks: list[str] = []
    pending_tool_name: str | None = None

    for item in getattr(result, "new_items", []):
        item_type = getattr(item, "type", "")
        if item_type == "tool_call_item":
            raw = getattr(item, "raw_item", None)
            pending_tool_name = _tool_name_from_call_raw(raw)
        elif item_type == "tool_call_output_item":
            output = getattr(item, "output", None)
            text = _stringify_tool_output(output).strip()
            label = pending_tool_name or _tool_name_from_call_raw(
                getattr(item, "raw_item", None),
            )
            if text:
                chunks.append(f"### {label}\n\n{text}\n")
            pending_tool_name = None

    body = "\n".join(chunks).strip()
    if not body:
        return ""

    if len(body) > max_chars:
        body = body[: max_chars - 40].rstrip() + "\n\n…(truncated for size)…"

    return (
        "## Planning phase — tool results\n\n"
        "The planning agent already ran these tools. Reuse this information when "
        "possible to avoid redundant calls and to keep IDs and details consistent "
        "with what the planner saw.\n\n"
        + body
    )
