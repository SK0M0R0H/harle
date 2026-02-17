"""Tests for harle.api.routes — FastAPI endpoints via TestClient."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import pytest

from harle.api.routes import build_router
from harle.config import Settings
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService


@pytest.fixture()
def client() -> TestClient:
    """Create a test client with echo provider and no data layer."""
    svc = OrchestratorService(llm_provider=EchoProvider())
    router = build_router(orchestrator=svc, db=None, search_engine=None, settings=None)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def client_with_settings() -> TestClient:
    """Test client with settings but no DB (for testing 503 on /init, /reindex)."""
    svc = OrchestratorService(llm_provider=EchoProvider())
    settings = Settings()
    router = build_router(orchestrator=svc, db=None, search_engine=None, settings=settings)
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


# ---------------------------------------------------------------------------
# GET /health
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# POST /run
# ---------------------------------------------------------------------------

class TestRunEndpoint:
    def test_valid_request(self, client: TestClient) -> None:
        resp = client.post("/run", json={"message": "hello"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "hello" in data["result"]
        assert data["run_id"].startswith("run_")

    def test_with_context(self, client: TestClient) -> None:
        resp = client.post("/run", json={"message": "test", "context": "work"})
        assert resp.status_code == 200
        assert resp.json()["context"] == "work"

    def test_empty_message_rejected(self, client: TestClient) -> None:
        resp = client.post("/run", json={"message": ""})
        assert resp.status_code == 422

    def test_missing_message_rejected(self, client: TestClient) -> None:
        resp = client.post("/run", json={})
        assert resp.status_code == 422

    def test_invalid_context_rejected(self, client: TestClient) -> None:
        resp = client.post("/run", json={"message": "hi", "context": "invalid"})
        assert resp.status_code == 422

    def test_conversation_id_roundtrip(self, client: TestClient) -> None:
        resp = client.post(
            "/run",
            json={"message": "hi", "conversation_id": "conv-abc"},
        )
        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "conv-abc"


# ---------------------------------------------------------------------------
# POST /init — 503 when DB not configured
# ---------------------------------------------------------------------------

class TestInitEndpoint:
    def test_503_when_no_db(self, client: TestClient) -> None:
        resp = client.post("/init")
        assert resp.status_code == 503

    def test_503_mentions_database(self, client: TestClient) -> None:
        resp = client.post("/init")
        assert "DATABASE_URL" in resp.json()["detail"]


# ---------------------------------------------------------------------------
# POST /reindex — 503 when DB not configured
# ---------------------------------------------------------------------------

class TestReindexEndpoint:
    def test_503_when_no_db(self, client: TestClient) -> None:
        resp = client.post("/reindex")
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# GET /search — 503 when search engine not configured
# ---------------------------------------------------------------------------

class TestSearchEndpoint:
    def test_503_when_no_engine(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "test"})
        assert resp.status_code == 503

    def test_missing_query_rejected(self, client: TestClient) -> None:
        resp = client.get("/search")
        assert resp.status_code == 422
