"""Integration tests for multi-component Harle flows."""

from __future__ import annotations

from pathlib import Path
from textwrap import dedent

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

from harle.api.models import RunRequest
from harle.api.routes import build_router
from harle.context.assembler import ContextAssembler
from harle.dataset.reader import DatasetReader
from harle.db.connection import Database
from harle.db.models import Conversation, Message
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService
from harle.search.types import SearchQuery, SearchResult


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


class _StaticSearchEngine:
    """Search engine stub returning deterministic dataset results."""

    def search(self, query: SearchQuery) -> list[SearchResult]:
        return [
            SearchResult(
                file_path="knowledge/work/roadmap.md",
                title="Roadmap",
                score=9.2,
                context=query.context,
                tags=["planning"],
                snippet="Milestones and delivery plan.",
            )
        ]


def _write_vault_file(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dedent(content), encoding="utf-8")


def _make_chat_db() -> Database:
    """Create an in-memory DB with only chat tables."""
    db = Database.__new__(Database)
    db.engine = create_engine(
        "sqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    db._session_factory = sessionmaker(bind=db.engine, expire_on_commit=False)
    Conversation.__table__.create(db.engine, checkfirst=True)
    Message.__table__.create(db.engine, checkfirst=True)
    return db


@pytest.mark.integration
class TestApiPipelines:
    def test_run_endpoint_pipeline_returns_completed(self) -> None:
        app = FastAPI()
        app.include_router(build_router(orchestrator=OrchestratorService(llm_provider=EchoProvider())))
        client = TestClient(app)

        response = client.post("/run", json={"message": "Find stalled tasks", "context": "work"})

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["run_id"].startswith("run_")
        assert "Find stalled tasks" in data["result"]

    def test_chat_endpoint_persists_multi_turn_conversation(self) -> None:
        db = _make_chat_db()
        app = FastAPI()
        app.include_router(
            build_router(
                orchestrator=OrchestratorService(llm_provider=EchoProvider(), db=db),
                db=db,
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

        with db.session() as session:
            messages = session.query(Message).filter_by(conversation_id=conv_id).all()
        assert len(messages) == 4
        assert [m.role for m in messages] == ["user", "assistant", "user", "assistant"]

    def test_context_assembly_is_wired_into_orchestrator_run(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
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
