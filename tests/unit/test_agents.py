"""Unit tests for :mod:`harle.orchestrator.agents`."""

from __future__ import annotations

from harle.orchestrator.agents import (
    HANDOFF_GRAPH,
    KNOWN_ROLES,
    ROLE_TOOL_MODULES,
    HandoffRecord,
    final_agent_from_handoffs,
    tool_names_for_role,
)


def test_known_roles_include_five_roles() -> None:
    assert set(KNOWN_ROLES) == {
        "assistant",
        "researcher",
        "secretary",
        "specialist",
        "writer",
    }


def test_handoff_graph_is_complete() -> None:
    """Every role can hand off to every other role (no self-edges)."""
    for role in KNOWN_ROLES:
        assert set(HANDOFF_GRAPH[role]) == set(KNOWN_ROLES) - {role}


def test_role_tool_modules_keys_match_known_roles() -> None:
    assert set(ROLE_TOOL_MODULES.keys()) == set(KNOWN_ROLES)


def test_tool_names_for_role_empty_registry() -> None:
    assert tool_names_for_role(None, "researcher") == []


def test_final_agent_no_handoffs() -> None:
    assert final_agent_from_handoffs("researcher", []) == "researcher"


def test_final_agent_after_handoffs() -> None:
    hs = [
        HandoffRecord("researcher", "secretary", "need trello"),
        HandoffRecord("secretary", "writer", "draft"),
    ]
    assert final_agent_from_handoffs("researcher", hs) == "writer"
