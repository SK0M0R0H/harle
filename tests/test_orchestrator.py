"""Tests for harle.orchestrator.service — OrchestratorService, build_orchestrator."""

from __future__ import annotations

import os
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from harle.api.models import RunRequest
from harle.config import Settings
from harle.context.assembler import ContextAssembler, ContextPackage
from harle.db.connection import Database
from harle.db.models import Conversation, Message
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService, build_orchestrator


class TestOrchestratorService:
    def test_run_returns_response(self) -> None:
        svc = OrchestratorService(llm_provider=EchoProvider())
        req = RunRequest(message="hello", context="personal")
        resp = svc.run(request=req)

        assert resp.status == "completed"
        assert resp.run_id.startswith("run_")
        assert "hello" in resp.result
        assert resp.context == "personal"

    def test_run_preserves_conversation_id(self) -> None:
        svc = OrchestratorService(llm_provider=EchoProvider())
        req = RunRequest(message="test", context="work", conversation_id="conv-42")
        resp = svc.run(request=req)

        assert resp.conversation_id == "conv-42"

    def test_run_id_unique(self) -> None:
        svc = OrchestratorService(llm_provider=EchoProvider())
        req = RunRequest(message="test", context="personal")
        ids = {svc.run(request=req).run_id for _ in range(10)}
        assert len(ids) == 10

    def test_run_with_work_context(self) -> None:
        svc = OrchestratorService(llm_provider=EchoProvider())
        req = RunRequest(message="deploy", context="work")
        resp = svc.run(request=req)
        assert resp.context == "work"

    def test_run_without_context_assembler(self) -> None:
        """Orchestrator still works when no context assembler is set."""
        svc = OrchestratorService(llm_provider=EchoProvider(), context_assembler=None)
        req = RunRequest(message="hello", context="personal")
        resp = svc.run(request=req)

        assert resp.status == "completed"
        assert "hello" in resp.result

    def test_run_with_context_assembler_calls_assemble(self) -> None:
        """When a context assembler is provided, run() calls assemble()."""
        mock_assembler = MagicMock(spec=ContextAssembler)
        mock_assembler.assemble.return_value = ContextPackage(
            system_prompt="You are a test agent.",
            search_results=[],
            p0_files=["prompts/test.md"],
            total_tokens=50,
            budget_remaining=100_000,
        )

        svc = OrchestratorService(
            llm_provider=EchoProvider(),
            context_assembler=mock_assembler,
        )
        req = RunRequest(message="find tasks", context="work")
        resp = svc.run(request=req)

        mock_assembler.assemble.assert_called_once_with(
            message="find tasks",
            context="work",
        )
        assert resp.status == "completed"
        assert "find tasks" in resp.result

    def test_run_with_context_assembler_passes_system_prompt(self) -> None:
        """The assembled system prompt is forwarded to the LLM provider."""
        mock_assembler = MagicMock(spec=ContextAssembler)
        mock_assembler.assemble.return_value = ContextPackage(
            system_prompt="Custom system prompt from assembler.",
            search_results=[],
            p0_files=[],
            total_tokens=10,
            budget_remaining=100_000,
        )

        mock_provider = MagicMock()
        mock_provider.generate.return_value = "LLM response"

        svc = OrchestratorService(
            llm_provider=mock_provider,
            context_assembler=mock_assembler,
        )
        req = RunRequest(message="test", context="personal")
        svc.run(request=req)

        mock_provider.generate.assert_called_once()
        call_kwargs = mock_provider.generate.call_args.kwargs
        assert call_kwargs["system_prompt"] == "Custom system prompt from assembler."
        assert call_kwargs["prompt"] == "test"
        assert call_kwargs["context"] == "personal"

    def test_run_with_real_assembler_and_dataset(self, tmp_path: Path) -> None:
        """Integration: assembler loads P0 files from a real dataset."""
        prompts_dir = tmp_path / "prompts"
        prompts_dir.mkdir()
        (prompts_dir / "agent.md").write_text(
            dedent("""\
                ---
                title: Test Agent
                tags: [prompt]
                context: global
                ---
                You are a helpful test agent.
            """),
            encoding="utf-8",
        )

        from harle.dataset.reader import DatasetReader

        reader = DatasetReader(str(tmp_path))
        assembler = ContextAssembler(
            search_engine=None,
            dataset_reader=reader,
        )

        svc = OrchestratorService(
            llm_provider=EchoProvider(),
            context_assembler=assembler,
        )
        req = RunRequest(message="help me", context="work")
        resp = svc.run(request=req)

        assert resp.status == "completed"
        assert "help me" in resp.result


class TestBuildOrchestrator:
    def test_no_api_key_gives_echo(self) -> None:
        settings = Settings()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings)
        assert isinstance(svc.llm_provider, EchoProvider)

    def test_non_openai_provider_gives_echo(self) -> None:
        settings = Settings(HARLE_LLM_PROVIDER="local")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            svc = build_orchestrator(settings=settings)
        assert isinstance(svc.llm_provider, EchoProvider)

    def test_openai_with_key_gives_openai_provider(self) -> None:
        from harle.llm.providers import OpenAIProvider

        settings = Settings(HARLE_LLM_PROVIDER="openai")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            svc = build_orchestrator(settings=settings)
        assert isinstance(svc.llm_provider, OpenAIProvider)

    def test_build_with_context_assembler(self) -> None:
        """build_orchestrator passes context_assembler to the service."""
        mock_assembler = MagicMock(spec=ContextAssembler)
        settings = Settings()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(
                settings=settings,
                context_assembler=mock_assembler,
            )
        assert svc.context_assembler is mock_assembler

    def test_build_without_context_assembler(self) -> None:
        """Default build has no context assembler (backward compat)."""
        settings = Settings()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings)
        assert svc.context_assembler is None

    def test_build_with_db(self) -> None:
        """build_orchestrator passes db to the service."""
        mock_db = MagicMock(spec=Database)
        settings = Settings()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings, db=mock_db)
        assert svc.db is mock_db

    def test_build_without_db(self) -> None:
        """Default build has no db (backward compat)."""
        settings = Settings()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings)
        assert svc.db is None


# ══════════════════════════════════════════════════════════════════════
# OrchestratorService.chat — multi-turn conversations
# ══════════════════════════════════════════════════════════════════════


def _make_test_db() -> Database:
    """Create an in-memory SQLite database with conversation tables only."""
    db = Database.__new__(Database)
    db.engine = create_engine("sqlite:///:memory:", echo=False)
    db._session_factory = sessionmaker(bind=db.engine, expire_on_commit=False)
    Conversation.__table__.create(db.engine, checkfirst=True)
    Message.__table__.create(db.engine, checkfirst=True)
    return db


class TestOrchestratorChat:
    """Tests for the chat() method with conversation management."""

    def test_chat_requires_db(self) -> None:
        svc = OrchestratorService(llm_provider=EchoProvider(), db=None)
        req = RunRequest(message="hello", context="personal")
        with pytest.raises(RuntimeError, match="Database is required"):
            svc.chat(request=req)

    def test_chat_creates_new_conversation(self) -> None:
        db = _make_test_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="hello", context="work")
        resp = svc.chat(request=req)

        assert resp.status == "completed"
        assert resp.conversation_id is not None
        assert resp.conversation_id.startswith("conv_")
        assert resp.context == "work"

    def test_chat_stores_messages(self) -> None:
        db = _make_test_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="test message", context="personal")
        resp = svc.chat(request=req)

        with db.session() as session:
            from harle.db.conversations import get_messages

            msgs = get_messages(session, resp.conversation_id)

        assert len(msgs) == 2
        assert msgs[0].role == "user"
        assert msgs[0].content == "test message"
        assert msgs[1].role == "assistant"
        assert "test message" in msgs[1].content

    def test_chat_continues_existing_conversation(self) -> None:
        db = _make_test_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)

        resp1 = svc.chat(request=RunRequest(message="first", context="work"))
        conv_id = resp1.conversation_id

        resp2 = svc.chat(
            request=RunRequest(
                message="second",
                context="work",
                conversation_id=conv_id,
            )
        )
        assert resp2.conversation_id == conv_id

        with db.session() as session:
            from harle.db.conversations import get_messages

            msgs = get_messages(session, conv_id)

        assert len(msgs) == 4
        assert msgs[0].role == "user"
        assert msgs[0].content == "first"
        assert msgs[2].role == "user"
        assert msgs[2].content == "second"

    def test_chat_nonexistent_conversation_raises(self) -> None:
        db = _make_test_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(
            message="hello",
            context="work",
            conversation_id="conv_doesnotexist",
        )
        with pytest.raises(ValueError, match="not found"):
            svc.chat(request=req)

    def test_chat_with_context_assembler(self) -> None:
        """chat() passes conversation history to the context assembler."""
        db = _make_test_db()
        mock_assembler = MagicMock(spec=ContextAssembler)
        mock_assembler.assemble.return_value = ContextPackage(
            system_prompt="System prompt.",
            search_results=[],
            p0_files=[],
            total_tokens=10,
            budget_remaining=100_000,
            conversation_messages_included=0,
        )

        svc = OrchestratorService(
            llm_provider=EchoProvider(),
            context_assembler=mock_assembler,
            db=db,
        )

        resp1 = svc.chat(request=RunRequest(message="first", context="work"))

        mock_assembler.assemble.assert_called_once()
        first_call_kwargs = mock_assembler.assemble.call_args.kwargs
        assert first_call_kwargs["conversation_history"] is None

        svc.chat(
            request=RunRequest(
                message="second",
                context="work",
                conversation_id=resp1.conversation_id,
            )
        )

        second_call_kwargs = mock_assembler.assemble.call_args.kwargs
        assert second_call_kwargs["conversation_history"] is not None
        assert len(second_call_kwargs["conversation_history"]) == 2

    def test_chat_run_id_unique(self) -> None:
        db = _make_test_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        ids = {
            svc.chat(request=RunRequest(message="hi", context="work")).run_id
            for _ in range(5)
        }
        assert len(ids) == 5
