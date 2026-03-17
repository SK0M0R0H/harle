"""Integration tests for multi-component Harle flows."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harle.api.models import RunRequest
from harle.api.routes import build_router
from harle.context.assembler import ContextAssembler
from harle.dataset.reader import DatasetReader
from harle.db.connection import Database
from harle.db.models import Message
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService
from harle.search.types import QueryMetadata, SearchQuery, SearchResponse, SearchResult


class _StaticSearchEngine:
    """Search engine stub returning deterministic dataset results."""

    def search(self, query: SearchQuery) -> SearchResponse:
        return SearchResponse(
            file_results=[
                SearchResult(
                    file_path="knowledge/work/roadmap.md",
                    title="Roadmap",
                    score=9.2,
                    context=query.context,
                    tags=["planning"],
                    snippet="Milestones and delivery plan.",
                )
            ],
            memory_results=[],
            prior_runs=[],
            query_metadata=QueryMetadata(
                original_query=query.query,
                expanded_terms=[],
                tags_matched=[],
                candidates_count=1,
                search_time_ms=0.0,
                phase="keyword",
            ),
        )


class _CapturingProvider:
    """Deterministic provider that records the latest system prompt."""

    def __init__(self) -> None:
        self.last_system_prompt: str | None = None

    def generate(
        self,
        *,
        prompt: str,
        context: str,
        conversation_id: str | None,
        system_prompt: str | None = None,
    ) -> str:
        self.last_system_prompt = system_prompt
        return f"ok::{context}::{prompt}"


def _write_vault_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content), encoding="utf-8")


@pytest.mark.integration
class TestApiPipelines:
    """HTTP API flows: /run, /chat, /health, /search, /run/{run_id}."""

    def test_run_endpoint_pipeline_returns_completed(self) -> None:
        """POST /run with valid payload returns 200, completed status, and echo in result."""
        app = FastAPI()
        app.include_router(build_router(orchestrator=OrchestratorService(llm_provider=EchoProvider())))
        client = TestClient(app)

        response = client.post("/run", json={"message": "Find stalled tasks", "context": "work"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["run_id"].startswith("run_")
        assert data["context"] == "work"
        assert "Find stalled tasks" in data["result"]

    def test_run_validates_request(self) -> None:
        """POST /run returns 422 for empty message or invalid context."""
        app = FastAPI()
        app.include_router(build_router(orchestrator=OrchestratorService(llm_provider=EchoProvider())))
        client = TestClient(app)

        empty_message = client.post("/run", json={"message": "", "context": "work"})
        assert empty_message.status_code == 422

        invalid_context = client.post(
            "/run", json={"message": "Hello", "context": "invalid_scope"}
        )
        assert invalid_context.status_code == 422

    def test_chat_endpoint_persists_multi_turn_conversation(
        self, chat_db: Database
    ) -> None:
        """POST /chat creates a conversation and persists user/assistant messages across turns."""
        app = FastAPI()
        app.include_router(
            build_router(
                orchestrator=OrchestratorService(llm_provider=EchoProvider(), db=chat_db),
                db=chat_db,
            )
        )
        client = TestClient(app)

        first = client.post("/chat", json={"message": "Hello", "context": "personal"})
        assert first.status_code == 200
        conv_id = first.json()["conversation_id"]
        assert conv_id

        second = client.post(
            "/chat",
            json={"message": "What did I just ask?", "context": "personal", "conversation_id": conv_id},
        )
        assert second.status_code == 200
        assert second.json()["conversation_id"] == conv_id

        with chat_db.session() as session:
            messages = session.query(Message).filter_by(conversation_id=conv_id).all()
        assert len(messages) == 4
        assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]

    def test_chat_requires_database(self) -> None:
        """POST /chat returns 503 when database is not configured."""
        app = FastAPI()
        app.include_router(build_router(orchestrator=OrchestratorService(llm_provider=EchoProvider())))
        client = TestClient(app)

        response = client.post("/chat", json={"message": "Hi", "context": "personal"})
        assert response.status_code == 503
        assert "Database" in response.json()["detail"]

    def test_health_returns_ok(self) -> None:
        """GET /health returns 200 and status ok."""
        app = FastAPI()
        app.include_router(build_router(orchestrator=OrchestratorService(llm_provider=EchoProvider())))
        client = TestClient(app)

        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"

    def test_search_requires_search_engine(self) -> None:
        """GET /search returns 503 when search is not configured."""
        app = FastAPI()
        app.include_router(build_router(orchestrator=OrchestratorService(llm_provider=EchoProvider())))
        client = TestClient(app)

        response = client.get("/search", params={"q": "roadmap"})
        assert response.status_code == 503
        assert "Search" in response.json()["detail"]

    def test_search_returns_results_when_configured(self) -> None:
        """GET /search returns 200 and results when search engine is wired."""
        app = FastAPI()
        app.include_router(
            build_router(
                orchestrator=OrchestratorService(llm_provider=EchoProvider()),
                search_engine=_StaticSearchEngine(),
            )
        )
        client = TestClient(app)

        response = client.get("/search", params={"q": "roadmap", "context": "work"})
        assert response.status_code == 200
        data = response.json()
        assert data["query"] == "roadmap"
        assert data["context"] == "work"
        assert data["total"] == 1
        assert len(data["results"]) == 1
        assert data["results"][0]["file_path"] == "knowledge/work/roadmap.md"
        assert data["results"][0]["title"] == "Roadmap"

    def test_get_run_requires_database(self) -> None:
        """GET /run/{run_id} returns 503 when database is not configured."""
        app = FastAPI()
        app.include_router(build_router(orchestrator=OrchestratorService(llm_provider=EchoProvider())))
        client = TestClient(app)

        response = client.get("/run/run_abc123")
        assert response.status_code == 503
        assert "Database" in response.json()["detail"]

    def test_context_assembly_is_wired_into_orchestrator_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Orchestrator run uses context assembler: role, policies, and dataset files in system prompt."""
        _write_vault_file(
            tmp_path / "prompts/researcher.md",
            """
            ---
            title: Researcher Prompt
            context: global
            ---
            You are the researcher role.
            """,
        )
        _write_vault_file(
            tmp_path / "policies/style.md",
            """
            ---
            title: Style Policy
            context: global
            ---
            Keep responses concise.
            """,
        )
        _write_vault_file(
            tmp_path / "knowledge/work/roadmap.md",
            """
            ---
            title: Delivery Roadmap
            context: work
            ---
            Q2 milestone is integration testing.
            """,
        )

        monkeypatch.setattr("harle.context.assembler.count_tokens", lambda text: max(1, len(text.split())))

        provider = _CapturingProvider()
        assembler = ContextAssembler(
            search_engine=_StaticSearchEngine(),
            dataset_reader=DatasetReader(str(tmp_path)),
        )
        orchestrator = OrchestratorService(llm_provider=provider, context_assembler=assembler)

        response = orchestrator.run(request=RunRequest(message="What is the roadmap?", context="work"))

        assert response.status == "completed"
        assert response.result == "ok::work::What is the roadmap?"
        assert provider.last_system_prompt is not None
        assert "## Active Role" in provider.last_system_prompt
        assert "## Active Policies" in provider.last_system_prompt
        assert "## Relevant Dataset Files" in provider.last_system_prompt
        assert "Q2 milestone is integration testing." in provider.last_system_prompt

    def test_import_endpoint_full_pipeline_writes_vault(self, tmp_path: Path) -> None:
        """POST /import with dummy source runs full pipeline and writes files to vault."""
        from harle.config import Settings
        from harle.vault_imports import build_import_registry

        registry = build_import_registry()
        app = FastAPI()
        app.include_router(
            build_router(
                orchestrator=OrchestratorService(llm_provider=EchoProvider()),
                import_registry=registry,
                settings=Settings(HARLE_DATASET_PATH=str(tmp_path)),
            )
        )
        client = TestClient(app)

        response = client.post(
            "/import",
            json={"source": "dummy", "config": {"context": "personal"}, "dry_run": False},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["source"] == "dummy"
        assert data["items_found"] == 2
        assert data["items_imported"] == 2
        assert len(data["created_paths"]) == 2
        for rel_path in data["created_paths"]:
            assert (tmp_path / rel_path).exists()
            content = (tmp_path / rel_path).read_text()
            assert "import_source: dummy" in content or "dummy" in content


@pytest.mark.integration
class TestSearchPhase2Pipeline:
    """Full Phase 2 search pipeline: expand -> Whoosh -> rank -> SearchResponse."""

    def test_phase2_pipeline_on_fixture_dataset(self, tmp_path: Path) -> None:
        """Expand, build Whoosh, search, rank on a tiny fixture dataset."""
        from types import SimpleNamespace

        from harle.search.query_expander import expand
        from harle.search.ranker import rank
        from harle.search.types import SearchQuery
        from harle.search import whoosh_index

        (tmp_path / "knowledge" / "work").mkdir(parents=True)
        (tmp_path / "policies").mkdir(parents=True)
        (tmp_path / "knowledge" / "work" / "fixture.md").write_text(
            "---\ntitle: Fixture Doc\ntags: [trello, tasks]\ncontext: work\n---\n\n"
            "Stalled tasks in Trello and how to triage them.",
            encoding="utf-8",
        )
        (tmp_path / "policies" / "global.md").write_text(
            "---\ntitle: Global Policy\ntags: []\ncontext: global\n---\n\nPolicy text.",
            encoding="utf-8",
        )

        reader = DatasetReader(str(tmp_path))
        whoosh_index.build_from_scratch(reader, tmp_path / "whoosh_idx")
        assert whoosh_index.exists_in(str(tmp_path / "whoosh_idx"))

        config = SimpleNamespace(
            add_role_terms=False,
            match_tag_vocabulary=True,
            use_stemming=True,
        )
        tag_vocabulary = {"trello", "tasks", "work"}
        query = SearchQuery(query="stalled tasks Trello", context="work", max_results=10)
        expanded = expand(query, tag_vocabulary, config)
        assert expanded.whoosh_terms
        assert "trello" in expanded.tag_filters or "tasks" in expanded.tag_filters

        candidate_paths = {"knowledge/work/fixture.md", "policies/global.md"}
        whoosh_results = whoosh_index.search(
            tmp_path / "whoosh_idx",
            expanded.whoosh_terms,
            candidate_paths,
            limit=10,
        )
        assert len(whoosh_results) >= 1
        assert whoosh_results[0][0] == "knowledge/work/fixture.md"

        path_to_metadata = {}
        for f in reader.read_all():
            path_to_metadata[f.relative_path] = SimpleNamespace(
                file_path=f.relative_path,
                title=f.title or f.relative_path,
                tags=f.tags or [],
                context=f.context,
                token_count=None,
                summary=None,
                last_modified=None,
            )
        ranked = rank(
            whoosh_results,
            path_to_metadata,
            tag_filters=expanded.tag_filters or [],
        )
        assert len(ranked) >= 1
        assert ranked[0].file_path == "knowledge/work/fixture.md"
        assert ranked[0].score > 0
        assert ranked[0].title == "Fixture Doc"
