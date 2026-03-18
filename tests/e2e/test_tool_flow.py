"""E2E tests: run completion (emulated mode; no real tool calls)."""

from __future__ import annotations

import pytest
import httpx


@pytest.mark.e2e
def test_run_completes_with_result(e2e_base_url: str) -> None:
    """POST /run completes and returns a result (pipeline runs; EchoProvider returns echo)."""
    r = httpx.post(
        f"{e2e_base_url}/run",
        json={"message": "Search for roadmap and milestones", "context": "work"},
        timeout=60.0,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "completed"
    assert data["run_id"].startswith("run_")
    assert len(data["result"]) > 0
