"""Deterministic agent role routing for the orchestrator.

Chooses the starting agent role from the user message using explicit
override (``as <role>: ...``) and keyword rules. No LLM calls.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from harle.orchestrator.agents import KNOWN_ROLES

# Explicit override: "as researcher: do something" (case-insensitive role name).
_EXPLICIT_OVERRIDE = re.compile(
    r"^\s*as\s+([a-z_]+)\s*:\s*(.*)$",
    re.IGNORECASE | re.DOTALL,
)

# Keyword patterns (order matters: first match wins).
_SECRETARY_PATTERN = re.compile(
    r"\b(trello|tasks?|schedule|board|cards?|organize|calendar)\b",
    re.IGNORECASE,
)
_RESEARCHER_PATTERN = re.compile(
    r"\b(research|report|analyze|compare|market|study)\b",
    re.IGNORECASE,
)
_SPECIALIST_PATTERN = re.compile(
    r"\b(dataset|prompts?|agent\s+logs?|harle|system\s+improvement)\b",
    re.IGNORECASE,
)
_WRITER_PATTERN = re.compile(
    r"\b(write|draft|compose|edit|rewrite|summarize|email)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class RouteResult:
    """Outcome of :func:`route`."""

    agent_role: str
    routing_method: str  # explicit_override | keyword_match | default | conversation_continue
    original_message: str  # Message with explicit override prefix stripped, if any


def route(message: str) -> RouteResult:
    """Select starting agent role from *message*.

    1. If the message starts with ``as <role>:``, use that role (must be in
       :data:`KNOWN_ROLES`) and strip the prefix for downstream use.
    2. Else match keyword patterns (secretary, researcher, specialist, writer).
    3. Else default to ``assistant`` (generic Harle assistant).
    """
    stripped = message.strip()
    m = _EXPLICIT_OVERRIDE.match(stripped)
    if m:
        role = m.group(1).strip().lower()
        rest = m.group(2).strip()
        if role in KNOWN_ROLES:
            return RouteResult(
                agent_role=role,
                routing_method="explicit_override",
                original_message=rest if rest else stripped,
            )
        # Unknown role after "as ...:" — fall through to keywords / default
        stripped = rest if rest else stripped

    lower = stripped.lower()
    if _SECRETARY_PATTERN.search(lower):
        return RouteResult(
            agent_role="secretary",
            routing_method="keyword_match",
            original_message=stripped,
        )
    if _RESEARCHER_PATTERN.search(lower):
        return RouteResult(
            agent_role="researcher",
            routing_method="keyword_match",
            original_message=stripped,
        )
    if _SPECIALIST_PATTERN.search(lower):
        return RouteResult(
            agent_role="specialist",
            routing_method="keyword_match",
            original_message=stripped,
        )
    if _WRITER_PATTERN.search(lower):
        return RouteResult(
            agent_role="writer",
            routing_method="keyword_match",
            original_message=stripped,
        )
    return RouteResult(
        agent_role="assistant",
        routing_method="default",
        original_message=stripped,
    )


def route_with_pinned_role(message: str, pinned_role: str) -> RouteResult:
    """Select role for a **follow-up** turn in an existing conversation.

    Reuses *pinned_role* (the conversation's stored ``agent_role``) so keyword
    routing does not re-run on every message. Still honors ``as <role>:`` when
    the user explicitly switches role mid-thread (same as :func:`route`).

    Args:
        message: Raw user message.
        pinned_role: Role from :class:`~harle.db.models.Conversation.agent_role`.

    Returns:
        :class:`RouteResult` with ``routing_method`` ``\"conversation_continue\"``
        when *pinned_role* is used without an explicit override.
    """
    stripped = message.strip()
    m = _EXPLICIT_OVERRIDE.match(stripped)
    if m:
        role = m.group(1).strip().lower()
        rest = m.group(2).strip()
        if role in KNOWN_ROLES:
            return RouteResult(
                agent_role=role,
                routing_method="explicit_override",
                original_message=rest if rest else stripped,
            )
        stripped = rest if rest else stripped
    return RouteResult(
        agent_role=pinned_role,
        routing_method="conversation_continue",
        original_message=stripped,
    )
