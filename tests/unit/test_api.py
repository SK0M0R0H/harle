"""Tests for harle.api.routes — endpoint behavior and wiring."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from harle.api.routes import build_router
from harle.config import Settings
from harle.db.conversations import create_conversation
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService
from harle.search.types import SearchResult

from tests.conftest import make_in_memory_chat_db


def _make_client(
    *,
    db: object | None = None,
    search_engine: object | None = None,
    settings: Settings | None = None,
    import_registry: object | None = None,
    connections: object | None = None,
    tool_registry: object | None = None,
    orchestrator: OrchestratorService | None = None,
) -> TestClient:
    if orchestrator is None:
        orchestrator = OrchestratorService(llm_provider=EchoProvider())
    router = build_router(
        orchestrator=orchestrator,
        db=db,  # type: ignore[arg-type]
        search_engine=search_engine,  # type: ignore[arg-type]
        settings=settings,
        import_registry=import_registry,
        connections=connections,
        tool_registry=tool_registry,
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


class TestHealthConnectionsEndpoint:
    """Tests for GET /health/connections."""

    def test_returns_empty_when_no_connections(self, client: TestClient) -> None:
        resp = client.get("/health/connections")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connections"] == []
        assert data["all_healthy"] is True

    def test_returns_statuses_when_connections_configured(self) -> None:
        from harle.connections.base import ConnectionStatus

        mock_reg = MagicMock()
        mock_reg.health_check_all = AsyncMock(
            return_value={
                "notion": ConnectionStatus(
                    healthy=True, service_name="Notion", message="", latency_ms=12.0
                ),
                "tavily": ConnectionStatus(
                    healthy=False, service_name="Tavily", message="API key missing", latency_ms=None
                ),
            }
        )
        client = _make_client(connections=mock_reg)
        resp = client.get("/health/connections")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["connections"]) == 2
        names = {c["name"] for c in data["connections"]}
        assert names == {"notion", "tavily"}
        assert data["all_healthy"] is False


class TestHealthToolsEndpoint:
    """Tests for GET /health/tools."""

    def test_returns_empty_when_no_tool_registry(self, client: TestClient) -> None:
        resp = client.get("/health/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tools"] == []
        assert data["all_healthy"] is True

    def test_returns_statuses_when_tool_registry_configured(self) -> None:
        mock_reg = MagicMock()
        mock_reg.health_check_all = AsyncMock(
            return_value={"web_search": True, "codebase": False}
        )
        client = _make_client(tool_registry=mock_reg)
        resp = client.get("/health/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["tools"]) == 2
        assert data["all_healthy"] is False


class TestHealthAllEndpoint:
    """Tests for GET /health/all."""

    def test_returns_empty_when_nothing_configured(self, client: TestClient) -> None:
        resp = client.get("/health/all")
        assert resp.status_code == 200
        data = resp.json()
        assert data["connections"] == []
        assert data["tools"] == []
        assert data["all_healthy"] is True

    def test_aggregates_connections_and_tools(self) -> None:
        from harle.connections.base import ConnectionStatus

        conn_reg = MagicMock()
        conn_reg.health_check_all = AsyncMock(
            return_value={"notion": ConnectionStatus(healthy=True, service_name="Notion", message="", latency_ms=5.0)}
        )
        tool_reg = MagicMock()
        tool_reg.health_check_all = AsyncMock(return_value={"tools": True})
        client = _make_client(connections=conn_reg, tool_registry=tool_reg)
        resp = client.get("/health/all")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["connections"]) == 1
        assert data["connections"][0]["name"] == "notion"
        assert len(data["tools"]) == 1
        assert data["tools"][0]["name"] == "tools"
        assert data["all_healthy"] is True


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

    def test_success_when_engine_returns_object_with_file_results(self) -> None:
        """Covers route branch when search returns Phase 2 SearchResponse with file_results."""
        mock_engine = MagicMock()
        mock_response = MagicMock()
        mock_response.file_results = [
            SearchResult(
                file_path="docs/readme.md",
                title="Readme",
                score=8.0,
                context="work",
                tags=[],
                snippet="readme snippet",
            )
        ]
        mock_engine.search.return_value = mock_response
        client = _make_client(search_engine=mock_engine)
        resp = client.get("/search", params={"q": "readme"})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["total"] == 1
        assert payload["results"][0]["file_path"] == "docs/readme.md"
        assert payload["results"][0]["snippet"] == "readme snippet"


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
            "reflection_triggered",
            "reflection_improved",
            "handoffs",
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
                self.reflection_triggered = None
                self.reflection_improved = None
                self.handoffs = None

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


class TestImportEndpoint:
    """Tests for POST /import."""

    def test_503_when_no_import_registry(self, client: TestClient) -> None:
        resp = client.post("/import", json={"source": "notion", "config": {}, "dry_run": True})
        assert resp.status_code == 503
        assert "import registry" in resp.json()["detail"].lower()

    def test_503_when_dataset_path_missing(self, client: TestClient) -> None:
        from harle.vault_imports import build_import_registry

        reg = build_import_registry()
        client_with_reg = _make_client(
            import_registry=reg,
            settings=Settings(),
        )
        resp = client_with_reg.post(
            "/import",
            json={"source": "dummy", "config": {}, "dry_run": True},
        )
        assert resp.status_code == 503
        assert "HARLE_DATASET_PATH" in resp.json()["detail"] or "Dataset path" in resp.json()["detail"]

    def test_success_dry_run_returns_preview(self, tmp_path) -> None:
        from harle.vault_imports import build_import_registry

        reg = build_import_registry()
        client_with_both = _make_client(
            import_registry=reg,
            settings=Settings(HARLE_DATASET_PATH=str(tmp_path)),
        )
        resp = client_with_both.post(
            "/import",
            json={"source": "dummy", "config": {}, "dry_run": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "dry_run"
        assert data["source"] == "dummy"
        assert data["items_found"] == 2
        assert data["items_imported"] == 0
        assert "created_paths" in data
        assert "errors" in data

    def test_success_import_writes_files(self, tmp_path) -> None:
        from harle.vault_imports import build_import_registry

        vault = tmp_path
        reg = build_import_registry()
        client_with_both = _make_client(
            import_registry=reg,
            settings=Settings(HARLE_DATASET_PATH=str(vault)),
        )
        resp = client_with_both.post(
            "/import",
            json={"source": "dummy", "config": {}, "dry_run": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert data["source"] == "dummy"
        assert data["items_imported"] == 2
        assert len(data["created_paths"]) == 2
        for p in data["created_paths"]:
            assert (vault / p).exists()

    def test_404_when_import_source_not_found(self, tmp_path) -> None:
        from harle.vault_imports.registry import ImportRegistry, ImportSourceNotFound

        mock_reg = MagicMock(spec=ImportRegistry)
        mock_reg.run_import = AsyncMock(
            side_effect=ImportSourceNotFound("Source 'unknown' is not registered.")
        )
        client = _make_client(
            import_registry=mock_reg,
            settings=Settings(HARLE_DATASET_PATH=str(tmp_path)),
        )
        resp = client.post(
            "/import",
            json={"source": "unknown", "config": {}, "dry_run": False},
        )
        assert resp.status_code == 404
        assert "not registered" in resp.json()["detail"].lower() or "unknown" in resp.json()["detail"].lower()

    def test_500_when_import_raises(self, tmp_path) -> None:
        from harle.vault_imports.registry import ImportRegistry

        mock_reg = MagicMock(spec=ImportRegistry)
        mock_reg.run_import = AsyncMock(side_effect=Exception("Connection refused"))
        client = _make_client(
            import_registry=mock_reg,
            settings=Settings(HARLE_DATASET_PATH=str(tmp_path)),
        )
        resp = client.post(
            "/import",
            json={"source": "notion", "config": {}, "dry_run": False},
        )
        assert resp.status_code == 500
        assert "Connection refused" in resp.json()["detail"] or "refused" in resp.json()["detail"].lower()

    def test_import_status_completed_with_errors_when_errors_and_some_imported(
        self, tmp_path
    ) -> None:
        from harle.vault_imports.base import ImportResult
        from harle.vault_imports.registry import ImportRegistry

        mock_reg = MagicMock(spec=ImportRegistry)
        mock_reg.run_import = AsyncMock(
            return_value=ImportResult(
                source_name="notion",
                items_found=3,
                items_imported=2,
                items_skipped=0,
                items_failed=1,
                errors=["One item failed"],
                created_paths=["a.md", "b.md"],
                updated_paths=[],
            )
        )
        client = _make_client(
            import_registry=mock_reg,
            settings=Settings(HARLE_DATASET_PATH=str(tmp_path)),
        )
        resp = client.post(
            "/import",
            json={"source": "notion", "config": {}, "dry_run": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed_with_errors"
        assert data["items_imported"] == 2
        assert data["items_failed"] == 1
        assert "One item failed" in data["errors"][0]


class TestChatEndpoint:
    """Tests for POST /chat."""

    def test_503_when_no_db(self, client: TestClient) -> None:
        resp = client.post("/chat", json={"message": "hi"})
        assert resp.status_code == 503
        assert "DATABASE_URL" in resp.json()["detail"]

    def test_valid_request(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("harle.db.runs.create_run", lambda *a, **k: None)
        db = make_in_memory_chat_db()
        client = _make_client(
            db=db,
            orchestrator=OrchestratorService(llm_provider=EchoProvider(), db=db),
        )
        resp = client.post("/chat", json={"message": "hello"})
        assert resp.status_code == 200
        payload = resp.json()
        assert payload["status"] == "completed"
        assert payload["run_id"].startswith("run_")
        assert "hello" in payload["result"]
        assert payload.get("conversation_id")

    @pytest.mark.parametrize(
        "body",
        [
            {"message": ""},
            {},
            {"message": "hi", "context": "invalid"},
        ],
    )
    def test_invalid_request_rejected(self, client: TestClient, body: dict) -> None:
        resp = client.post("/chat", json=body)
        assert resp.status_code == 422

    def test_conversation_id_roundtrip(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("harle.db.runs.create_run", lambda *a, **k: None)
        db = make_in_memory_chat_db()
        with db.session() as session:
            create_conversation(
                session,
                conversation_id="conv-abc",
                context_scope="work",
                agent_role="researcher",
            )
        client = _make_client(
            db=db,
            orchestrator=OrchestratorService(llm_provider=EchoProvider(), db=db),
        )
        resp = client.post(
            "/chat",
            json={"message": "hi", "conversation_id": "conv-abc"},
        )
        assert resp.status_code == 200
        assert resp.json()["conversation_id"] == "conv-abc"

    def test_504_when_chat_timeout(self) -> None:
        from harle.orchestrator.service import OrchestratorService, RunTimeoutError

        class TimeoutOrchestrator(OrchestratorService):
            def chat(self, request):  # type: ignore[no-untyped-def]
                raise RunTimeoutError("Chat timed out")

        mock_db = MagicMock()
        mock_db.session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_db.session.return_value.__exit__ = MagicMock(return_value=False)
        svc = TimeoutOrchestrator(llm_provider=EchoProvider())
        client = _make_client(orchestrator=svc, db=mock_db)
        resp = client.post("/chat", json={"message": "hi"})
        assert resp.status_code == 504
        assert "timeout" in resp.json()["detail"].lower()

    def test_404_when_conversation_not_found(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from harle.orchestrator.service import OrchestratorService

        class ValueErrorOrchestrator(OrchestratorService):
            def chat(self, request):  # type: ignore[no-untyped-def]
                raise ValueError("Conversation conv-xyz not found")

        mock_db = MagicMock()
        mock_db.session.return_value.__enter__ = MagicMock(return_value=MagicMock())
        mock_db.session.return_value.__exit__ = MagicMock(return_value=False)
        svc = ValueErrorOrchestrator(llm_provider=EchoProvider())
        client = _make_client(orchestrator=svc, db=mock_db)
        resp = client.post("/chat", json={"message": "hi", "conversation_id": "conv-xyz"})
        assert resp.status_code == 404
        assert "conv-xyz" in resp.json()["detail"] or "not found" in resp.json()["detail"].lower()

    def test_debug_true_returns_sse_stream(self) -> None:
        from harle.api.models import RunRequest, RunResponse
        from harle.orchestrator.service import OrchestratorService

        class ChatEchoOrchestrator(OrchestratorService):
            def chat(self, *, request: RunRequest) -> RunResponse:
                return RunResponse(
                    run_id="run_debug",
                    status="completed",
                    result=request.message,
                    context=request.context,
                )

        client = _make_client(
            db=MagicMock(),
            orchestrator=ChatEchoOrchestrator(llm_provider=EchoProvider()),
        )
        resp = client.post("/chat", json={"message": "hi"}, params={"debug": "true"})
        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers.get("content-type", "")
