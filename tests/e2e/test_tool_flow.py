"""E2E tests: run completion (emulated mode; no real tool calls)."""

from __future__ import annotations

import pytest
import httpx


@pytest.mark.e2e
def test_chat_completes_with_result(
    e2e_base_url: str,
    e2e_auth_headers: dict[str, str],
) -> None:
    """POST /chat completes and returns a result (pipeline runs; EchoProvider returns echo)."""
    r = httpx.post(
        f"{e2e_base_url}/chat",
        json={"message": "Search for roadmap and milestones", "context": "work"},
        headers=e2e_auth_headers,
        timeout=60.0,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["run_id"].startswith("run_")
    assert len(data["result"]) > 0
