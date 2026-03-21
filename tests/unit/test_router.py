"""Unit tests for :mod:`harle.orchestrator.router`."""

from __future__ import annotations

import pytest

from harle.orchestrator.router import route


@pytest.mark.parametrize(
    ("message", "expected_role", "expected_method"),
    [
        ("as researcher: hello world", "researcher", "explicit_override"),
        ("as secretary: organize my day", "secretary", "explicit_override"),
        ("as assistant: general help", "assistant", "explicit_override"),
        ("as writer: draft an email", "writer", "explicit_override"),
        ("Check my Trello board for stalled cards", "secretary", "keyword_match"),
        ("Research market trends for Q2", "researcher", "keyword_match"),
        ("Improve Harle dataset quality", "specialist", "keyword_match"),
        ("Draft a summary of the meeting", "writer", "keyword_match"),
        ("Hello", "assistant", "default"),
    ],
)
def test_route(
    message: str,
    expected_role: str,
    expected_method: str,
) -> None:
    r = route(message)
    assert r.agent_role == expected_role
    assert r.routing_method == expected_method


def test_explicit_override_strips_prefix() -> None:
    r = route("as specialist: fix prompts")
    assert r.original_message == "fix prompts"


def test_unknown_explicit_role_falls_through_to_keywords() -> None:
    r = route("as unknown_role: trello tasks")
    assert r.agent_role == "secretary"
    assert "trello" in r.original_message.lower()
