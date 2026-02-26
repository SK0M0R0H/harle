"""Tests for harle.api.routes — endpoint behavior and wiring."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from harle.api.routes import build_router
from harle.config import Settings
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService
from harle.search.types import SearchResult


def _make_client(
    *,
    db: object | None = None,
    search_engine: object | None = None,
    settings: Settings | None = None,
) -> TestClient:
    svc = OrchestratorService(llm_provider=EchoProvider())
    router = build_router(
        orchestrator=svc,
        db=db,  # type: ignore[arg-type]
        search_engine=search_engine,  # type: ignore[arg-type]
        settings=settings,
    )
    app = FastAPI()
    app.include_router(router)
    return TestClient(app)


@pytest.fixture()
def client() -> TestClient:
    return _make_client()


@pytest.fixture()
def client_with_settings() -> TestClient:
    return _make_client(settings=Settings())


@pytest.fixture()
def client_with_db_and_settings_no_dataset() -> TestClient:
    return _make_client(db=object(), settings=Settings())


class TestHealthEndpoint:
    def test_returns_ok(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}


class TestRunEndpoint:
    def test_valid_request(self, client: TestClient) -> None:
        resp = client.post("/run", json={"message": "hello"})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "completed"
        assert payload["run_id"].startswith("run_")
        assert "hello" in payload["result"]

    @pytest.mark.parametrize(
        "body",
        [
            {"message": ""},
            {},
            {"message": "hi", "context": "invalid"},
        ],
    )
    def test_invalid_request_rejected(self, client: TestClient, body: dict[str, str]) -> None:
        resp = client.post("/run", json=body)
        assert resp.status_code == 422

    def test_conversation_id_roundtrip(self, client: TestClient) -> None:
        resp = client.post("/run", json={"message": "hi", "conversation_id": "conv-abc"})
        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "conv-abc"


class TestInitEndpoint:
    def test_503_when_no_db(self, client: TestClient) -> None:
        resp = client.post("/init")
        assert resp.status_code == 503
        assert "DATABASE_URL" in resp.json()["detail"]

    def test_503_when_dataset_path_missing(
        self,
        client_with_db_and_settings_no_dataset: TestClient,
    ) -> None:
        resp = client_with_db_and_settings_no_dataset.post("/init")
        assert resp.status_code == 503
        assert "HARLE_DATASET_PATH" in resp.json()["detail"]

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_db = object()
        client = _make_client(db=mock_db, settings=Settings(HARLE_DATASET_PATH="/tmp/vault"))

        def _fake_init_system(db: object, dataset_path: str) -> dict[str, object]:
            assert db is mock_db
            assert dataset_path == "/tmp/vault"
            return {
                "tables_created": True,
                "files_seeded": 2,
                "files_indexed": 3,
                "total_files": 3,
                "dataset_path": "/tmp/vault",
            }

        monkeypatch.setattr("harle.bootstrap.init_system", _fake_init_system)
        resp = client.post("/init")
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "initialized",
            "tables_created": True,
            "files_seeded": 2,
            "files_indexed": 3,
            "total_files": 3,
            "dataset_path": "/tmp/vault",
        }


class TestReindexEndpoint:
    def test_503_when_no_db(self, client: TestClient) -> None:
        resp = client.post("/reindex")
        assert resp.status_code == 503

    def test_503_when_dataset_path_missing(
        self,
        client_with_db_and_settings_no_dataset: TestClient,
    ) -> None:
        resp = client_with_db_and_settings_no_dataset.post("/reindex")
        assert resp.status_code == 503
        assert "HARLE_DATASET_PATH" in resp.json()["detail"]

    def test_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_db = object()
        client = _make_client(db=mock_db, settings=Settings(HARLE_DATASET_PATH="/tmp/vault"))

        def _fake_reindex(db: object, dataset_path: str) -> dict[str, object]:
            assert db is mock_db
            assert dataset_path == "/tmp/vault"
            return {
                "files_indexed": 5,
                "total_files": 8,
                "dataset_path": "/tmp/vault",
            }

        monkeypatch.setattr("harle.bootstrap.reindex_dataset", _fake_reindex)
        resp = client.post("/reindex")
        assert resp.status_code == 200
        assert resp.json() == {
            "status": "reindexed",
            "files_indexed": 5,
            "total_files": 8,
            "dataset_path": "/tmp/vault",
        }


class TestSearchEndpoint:
    def test_503_when_no_engine(self, client: TestClient) -> None:
        resp = client.get("/search", params={"q": "test"})
        assert resp.status_code == 503

    def test_missing_query_rejected(self, client: TestClient) -> None:
        resp = client.get("/search")
        assert resp.status_code == 422

    def test_success_and_query_mapping(self) -> None:
        mock_engine = MagicMock()
        mock_engine.search.return_value = [
            SearchResult(
                file_path="knowledge/work/note.md",
                title="Work Note",
                score=6.5,
                context="work",
                tags=["python"],
                snippet="relevant snippet",
            )
        ]
        client = _make_client(search_engine=mock_engine)

        resp = client.get("/search", params={"q": "deploy", "context": "work", "max_results": 7})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["query"] == "deploy"
        assert payload["context"] == "work"
        assert payload["total"] == 1
        assert payload["results"][0]["file_path"] == "knowledge/work/note.md"
        assert payload["results"][0]["snippet"] == "relevant snippet"

        query = mock_engine.search.call_args.args[0]
        assert query.query == "deploy"
        assert query.context == "work"
        assert query.max_results == 7


class TestGetRunEndpoint:
    """Tests for GET /run/{run_id}."""

    def test_503_when_no_db(self, client: TestClient) -> None:
        resp = client.get("/run/run_abc123")
        assert resp.status_code == 503
        assert "DATABASE_URL" in resp.json()["detail"]

    def test_404_when_run_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        mock_session = MagicMock()
        mock_db = MagicMock()
        mock_db.session.return_value.__enter__ = MagicMock(return_value=mock_session)
        mock_db.session.return_value.__exit__ = MagicMock(return_value=False)
        client = _make_client(db=mock_db)
        monkeypatch.setattr("harle.db.runs.get_run", lambda session, run_id: None)
        resp = client.get("/run/run_nonexistent")
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"].lower()

    def test_run_materialized_before_session_close(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        guarded_fields = {
            "run_id",
            "timestamp",
            "user_request",
            "context_scope",
            "agent",
            "status",
            "routing_method",
            "files_used",
            "tools_called",
            "result_summary",
            "result_path",
            "context_path",
            "conversation_id",
            "duration_ms",
        }

        class _Run:
            def __init__(self) -> None:
                self.detached = False
                self.run_id = "run_guarded"
                self.timestamp = datetime(2026, 2, 26, tzinfo=timezone.utc)
                self.user_request = "hello"
                self.context_scope = "work"
                self.agent = "researcher"
                self.status = "completed"
                self.routing_method = None
                self.files_used = None
                self.tools_called = None
                self.result_summary = "ok"
                self.result_path = None
                self.context_path = None
                self.conversation_id = None
                self.duration_ms = 12

            def __getattribute__(self, name: str) -> object:
                if (
                    name in guarded_fields
                    and object.__getattribute__(self, "detached")
                ):
                    raise RuntimeError("Detached instance access")
                return object.__getattribute__(self, name)

        run = _Run()

        class _DbStub:
            @contextmanager
            def session(self):  # type: ignore[no-untyped-def]
                try:
                    yield object()
                finally:
                    run.detached = True

        monkeypatch.setattr("harle.db.runs.get_run", lambda session, run_id: run)
        client = _make_client(db=_DbStub())

        resp = client.get("/run/run_guarded")
        assert resp.status_code == 200
        assert resp.json()["run_id"] == "run_guarded"
