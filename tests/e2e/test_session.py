"""E2E tests: health, /run, and /chat session lifecycle."""

from __future__ import annotations

import pytest
import httpx


@pytest.mark.e2e
def test_health_returns_ok(e2e_base_url: str) -> None:
    """GET /health returns 200 and status ok."""
    r = httpx.get(f"{e2e_base_url}/health", timeout=10.0)
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


@pytest.mark.e2e
def test_run_returns_completed(e2e_base_url: str) -> None:
    """POST /run with valid payload returns 200, completed status, and echo in result."""
    r = httpx.post(
        f"{e2e_base_url}/run",
        json={"message": "Find stalled tasks", "context": "work"},
        timeout=30.0,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["run_id"].startswith("run_")
    assert data["context"] == "work"
    assert "Find stalled tasks" in data["result"]


@pytest.mark.e2e
def test_chat_multi_turn(e2e_base_url: str) -> None:
    """POST /chat creates a conversation; second message uses same conversation_id."""
    first = httpx.post(
        f"{e2e_base_url}/chat",
        json={"message": "First", "context": "personal"},
        timeout=30.0,
    )
    assert first.status_code == 200
    conv_id = first.json()["conversation_id"]
    assert conv_id

    second = httpx.post(
        f"{e2e_base_url}/chat",
        json={
            "message": "What did I just say?",
            "context": "personal",
            "conversation_id": conv_id,
        },
        timeout=30.0,
    )
    assert second.status_code == 200
    assert second.json()["conversation_id"] == conv_id
