"""E2E tests: vault (dataset) tool — /search and /health/tools (local, no API key)."""

from __future__ import annotations

import pytest
import httpx


@pytest.mark.e2e
def test_search_returns_vault_results(e2e_base_url: str) -> None:
    """GET /search with query matching e2e_vault content returns 200 and results from the vault."""
    r = httpx.get(
        f"{e2e_base_url}/search",
        params={"q": "roadmap", "context": "work"},
        timeout=10.0,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["query"] == "roadmap"
    assert data["total"] >= 1
    assert len(data["results"]) >= 1
    # At least one result should reference our fixture (roadmap.md or milestones)
    titles = [res.get("title") for res in data["results"]]
    snippets = [res.get("snippet") or "" for res in data["results"]]
    assert "Roadmap" in titles or any(
        "roadmap" in (s or "").lower() or "milestones" in (s or "").lower() for s in snippets
    )


@pytest.mark.e2e
def test_search_returns_chunk_metadata_for_workflow_section(e2e_base_url: str) -> None:
    """Chunked workflow in e2e_vault returns chunk_index and heading_path for a section-only term."""
    r = httpx.get(
        f"{e2e_base_url}/search",
        params={"q": "unique_e2e_token_chunk_beta_only", "context": "work"},
        timeout=10.0,
    )
    assert r.status_code == 200
    data = r.json()
    assert data["total"] >= 1
    matches = [
        res
        for res in data["results"]
        if "e2e-chunk-demo" in (res.get("file_path") or "")
    ]
    assert matches, f"expected workflows/e2e-chunk-demo in results, got {data['results']}"
    hit = matches[0]
    assert hit.get("chunk_index") is not None
    assert "Beta" in (hit.get("heading_path") or "")


@pytest.mark.e2e
def test_health_tools_lists_vault(e2e_base_url: str) -> None:
    """GET /health/tools returns 200 and lists at least one tool (vault/dataset when configured)."""
    r = httpx.get(f"{e2e_base_url}/health/tools", timeout=10.0)
    assert r.status_code == 200
    data = r.json()
    assert "tools" in data
    # With HARLE_DATASET_PATH set, vault/dataset tool is registered
    tool_names = [t["name"] for t in data["tools"]]
    assert len(tool_names) >= 1
