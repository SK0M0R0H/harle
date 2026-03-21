"""Duck-typed helpers for OpenAI Agents SDK run results."""

from __future__ import annotations


def extract_run_metadata(result: object) -> tuple[list[str], int]:
    """Extract tool names and turn count from an Agents SDK RunResult.

    Uses duck typing so callers do not import SDK item types directly.

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
