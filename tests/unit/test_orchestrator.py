"""Tests for harle.orchestrator.service — OrchestratorService, build_orchestrator."""

from __future__ import annotations

import os
import sys
import threading
import time
import types
from pathlib import Path
from textwrap import dedent
from unittest.mock import MagicMock, patch

import pytest

from harle.api.models import RunRequest
from harle.config import Settings
from harle.context.assembler import ContextAssembler, ContextPackage
from harle.db.connection import Database
from tests.conftest import make_in_memory_chat_db
from harle.llm.providers import EchoProvider
from harle.orchestrator.reflection import ReflectionRunRecord
from harle.orchestrator.runner_execution import AgentExecutionResult
from harle.orchestrator.service import (
    OrchestratorService,
    RunTimeoutError,
    build_orchestrator,
    _run_with_timeout,
)


class TestOrchestratorService:
    @pytest.fixture(autouse=True)
    def _patch_create_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "harle.db.runs.create_run",
            lambda *args, **kwargs: None,
        )

    def test_chat_returns_response(self) -> None:
        db = make_in_memory_chat_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="hello", context="personal")
        resp = svc.chat(request=req)

        assert resp.status == "completed"
        assert resp.run_id.startswith("run_")
        assert "hello" in resp.result
        assert resp.context == "personal"

    def test_chat_preserves_conversation_id_for_existing_conversation(self) -> None:
        db = make_in_memory_chat_db()
        from harle.db.conversations import create_conversation

        with db.session() as session:
            create_conversation(
                session,
                conversation_id="conv-42",
                context_scope="work",
                agent_role="researcher",
            )
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="test", context="work", conversation_id="conv-42")
        resp = svc.chat(request=req)

        assert resp.conversation_id == "conv-42"

    def test_chat_run_id_unique(self) -> None:
        db = make_in_memory_chat_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="test", context="personal")
        ids = {svc.chat(request=req).run_id for _ in range(10)}
        assert len(ids) == 10

    def test_chat_with_work_context(self) -> None:
        db = make_in_memory_chat_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="deploy", context="work")
        resp = svc.chat(request=req)
        assert resp.context == "work"

    def test_chat_without_context_assembler(self) -> None:
        """Orchestrator still works when no context assembler is set."""
        db = make_in_memory_chat_db()
        svc = OrchestratorService(
            llm_provider=EchoProvider(),
            context_assembler=None,
            db=db,
        )
        req = RunRequest(message="hello", context="personal")
        resp = svc.chat(request=req)

        assert resp.status == "completed"
        assert "hello" in resp.result

    def test_chat_with_context_assembler_calls_assemble(self) -> None:
        """When a context assembler is provided, chat() calls assemble()."""
        db = make_in_memory_chat_db()
        mock_assembler = MagicMock(spec=ContextAssembler)
        mock_assembler.assemble.return_value = ContextPackage(
            system_prompt="You are a test agent.",
            search_results=[],
            p0_files=["prompts/test.md"],
            total_tokens=50,
            budget_remaining=100_000,
            conversation_messages_included=0,
        )

        svc = OrchestratorService(
            llm_provider=EchoProvider(),
            context_assembler=mock_assembler,
            db=db,
        )
        req = RunRequest(message="find tasks", context="work")
        resp = svc.chat(request=req)

        mock_assembler.assemble.assert_called_once_with(
            message="find tasks",
            context="work",
            agent_role="researcher",
            conversation_history=None,
        )
        assert resp.status == "completed"
        assert "find tasks" in resp.result

    def test_chat_with_context_assembler_passes_system_prompt(self) -> None:
        """The assembled system prompt is forwarded to the LLM provider."""
        db = make_in_memory_chat_db()
        mock_assembler = MagicMock(spec=ContextAssembler)
        mock_assembler.assemble.return_value = ContextPackage(
            system_prompt="Custom system prompt from assembler.",
            search_results=[],
            p0_files=[],
            total_tokens=10,
            budget_remaining=100_000,
            conversation_messages_included=0,
        )

        mock_provider = MagicMock()
        mock_provider.generate.return_value = "LLM response"

        svc = OrchestratorService(
            llm_provider=mock_provider,
            context_assembler=mock_assembler,
            db=db,
        )
        req = RunRequest(message="test", context="personal")
        svc.chat(request=req)

        mock_provider.generate.assert_called_once()
        call_kwargs = mock_provider.generate.call_args.kwargs
        assert call_kwargs["system_prompt"] == "Custom system prompt from assembler."
        assert call_kwargs["prompt"] == "test"
        assert call_kwargs["context"] == "personal"

    def test_chat_with_real_assembler_and_dataset(self, tmp_path: Path) -> None:
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

        db = make_in_memory_chat_db()
        svc = OrchestratorService(
            llm_provider=EchoProvider(),
            context_assembler=assembler,
            db=db,
        )
        req = RunRequest(message="help me", context="work")
        resp = svc.chat(request=req)

        assert resp.status == "completed"
        assert "help me" in resp.result

    def test_chat_response_includes_optional_fields(self) -> None:
        """RunResponse includes tools_called and turns_used (None for echo)."""
        db = make_in_memory_chat_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="hello", context="personal")
        resp = svc.chat(request=req)

        assert resp.tools_called is None
        assert resp.turns_used is None

    def test_use_agent_runner_false_by_default(self) -> None:
        """Without explicit flag, legacy provider path is used."""
        svc = OrchestratorService(llm_provider=EchoProvider())
        assert svc.use_agent_runner is False


class TestRunWithTimeout:
    """Unit tests for _run_with_timeout (main-thread SIGALRM and worker-thread executor)."""

    def test_returns_result_when_within_limit(self) -> None:
        result = _run_with_timeout(10, lambda: 42)
        assert result == 42

    def test_none_seconds_disables_timeout(self) -> None:
        """When seconds is None, slow thunk completes without timeout."""
        result = _run_with_timeout(None, lambda: (time.sleep(0.2), 1)[1])
        assert result == 1

    def test_zero_seconds_disables_timeout(self) -> None:
        result = _run_with_timeout(0, lambda: 99)
        assert result == 99

    def test_main_thread_raises_run_timeout_error_when_exceeded(self) -> None:
        """On main thread, SIGALRM path raises RunTimeoutError when thunk exceeds limit."""
        with pytest.raises(RunTimeoutError, match="timed out"):
            _run_with_timeout(1, lambda: time.sleep(2))

    def test_worker_thread_raises_run_timeout_error_when_exceeded(self) -> None:
        """On a worker thread, executor path raises RunTimeoutError when thunk exceeds limit."""
        exc_holder: list[Exception] = []

        def run_in_worker() -> None:
            try:
                _run_with_timeout(1, lambda: time.sleep(2))
            except RunTimeoutError as e:
                exc_holder.append(e)

        t = threading.Thread(target=run_in_worker)
        t.start()
        t.join(timeout=5)
        assert t.is_alive() is False
        assert len(exc_holder) == 1
        assert "timed out" in str(exc_holder[0])


class TestOrchestratorRunTimeout:
    """OrchestratorService.chat() applies run_timeout_seconds and raises RunTimeoutError."""

    @pytest.fixture(autouse=True)
    def _patch_create_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "harle.db.runs.create_run",
            lambda *args, **kwargs: None,
        )

    def test_chat_raises_run_timeout_error_when_provider_slow(self) -> None:
        """chat() with a slow provider and run_timeout_seconds raises RunTimeoutError."""
        slow_provider = MagicMock()
        slow_provider.generate.side_effect = lambda **kwargs: (
            time.sleep(2),
            "too late",
        )[1]

        db = make_in_memory_chat_db()
        svc = OrchestratorService(
            llm_provider=slow_provider,
            run_timeout_seconds=1,
            db=db,
        )
        req = RunRequest(message="hello", context="personal")

        with pytest.raises(RunTimeoutError, match="timed out"):
            svc.chat(request=req)

    def test_chat_raises_run_timeout_error_from_worker_thread(self) -> None:
        """chat() invoked from a worker thread still enforces timeout via executor path."""
        slow_provider = MagicMock()
        slow_provider.generate.side_effect = lambda **kwargs: (
            time.sleep(2),
            "too late",
        )[1]

        db = make_in_memory_chat_db()
        svc = OrchestratorService(
            llm_provider=slow_provider,
            run_timeout_seconds=1,
            db=db,
        )
        req = RunRequest(message="hello", context="personal")
        exc_holder: list[Exception] = []

        def run_in_worker() -> None:
            try:
                svc.chat(request=req)
            except RunTimeoutError as e:
                exc_holder.append(e)

        t = threading.Thread(target=run_in_worker)
        t.start()
        t.join(timeout=5)
        assert t.is_alive() is False
        assert len(exc_holder) == 1
        assert "timed out" in str(exc_holder[0])


class TestOrchestratorAgentRunnerTrello:
    @pytest.fixture(autouse=True)
    def _patch_create_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "harle.db.runs.create_run",
            lambda *args, **kwargs: None,
        )

    def test_chat_with_trello_tools_exposes_and_tracks_tool_calls(self) -> None:
        from harle.tools.registry import ToolRegistry
        from harle.tools.trello.module import TrelloModule

        registry = ToolRegistry()
        trello_module = TrelloModule()
        registry.register_module(trello_module, skill_names=["read_sequence"])

        captured: dict[str, object] = {}

        class _FakeAgent:
            def __init__(self, **kwargs):
                captured["agent_kwargs"] = kwargs

        class _FakeRunner:
            @staticmethod
            def run_sync(agent, user_message, max_turns=10):
                captured["agent"] = agent
                captured["user_message"] = user_message
                captured["max_turns"] = max_turns

                class _RawItem:
                    name = "trello_list_boards"

                class _ToolCallItem:
                    type = "tool_call_item"
                    raw_item = _RawItem()

                class _MessageOutputItem:
                    type = "message_output_item"

                class _Result:
                    final_output = "Found boards and analyzed them."
                    new_items = [_ToolCallItem(), _MessageOutputItem()]
                    raw_responses = [object()]

                return _Result()

        fake_agents_module = types.SimpleNamespace(
            Agent=_FakeAgent,
            Runner=_FakeRunner,
            MaxTurnsExceeded=RuntimeError,
        )

        db = make_in_memory_chat_db()
        svc = OrchestratorService(
            llm_provider=EchoProvider(),
            tool_registry=registry,
            use_agent_runner=True,
            max_iterations=4,
            db=db,
            planning_enabled=False,
            reflection_enabled=False,
        )

        with patch.dict(sys.modules, {"agents": fake_agents_module}):
            resp = svc.chat(request=RunRequest(
                message="List Trello boards and summarize priorities",
                context="work",
            ))

        assert resp.status == "completed"
        assert resp.tools_called == ["trello_list_boards"]
        assert resp.turns_used == 1
        assert captured["max_turns"] == 4

        agent_kwargs = captured["agent_kwargs"]
        assert "tools" in agent_kwargs
        assert len(agent_kwargs["tools"]) >= 2

        instructions = str(agent_kwargs["instructions"])
        assert "Tool Skill: read_sequence" in instructions
        assert "trello_list_boards" in registry.list_all_tools()



class TestBuildOrchestrator:
    def test_no_api_key_gives_echo(self) -> None:
        settings = Settings()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings)
        assert isinstance(svc.llm_provider, EchoProvider)
        assert svc.use_agent_runner is False

    def test_non_openai_provider_gives_echo(self) -> None:
        settings = Settings(HARLE_LLM_PROVIDER="local")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            svc = build_orchestrator(settings=settings)
        assert isinstance(svc.llm_provider, EchoProvider)
        assert svc.use_agent_runner is False

    def test_openai_with_key_gives_openai_provider(self) -> None:
        from harle.llm.providers import OpenAIProvider

        settings = Settings(HARLE_LLM_PROVIDER="openai")
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-test"}, clear=False):
            svc = build_orchestrator(settings=settings)
        assert isinstance(svc.llm_provider, OpenAIProvider)
        assert svc.use_agent_runner is True

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

    def test_build_with_tool_registry(self) -> None:
        """build_orchestrator passes tool_registry to the service."""
        from harle.tools.registry import ToolRegistry

        registry = ToolRegistry()
        settings = Settings()
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings, tool_registry=registry)
        assert svc.tool_registry is registry

    def test_build_max_iterations_from_settings(self) -> None:
        """build_orchestrator reads max_iterations from settings."""
        settings = Settings(HARLE_MAX_ITERATIONS=15)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings)
        assert svc.max_iterations == 15

    def test_build_model_from_settings(self) -> None:
        """build_orchestrator reads model from settings."""
        settings = Settings(HARLE_LLM_MODEL="gpt-4o")
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings)
        assert svc.model == "gpt-4o"

    def test_build_planning_settings_from_settings(self) -> None:
        """build_orchestrator wires Level 3 planning fields from Settings."""
        settings = Settings(
            HARLE_PLANNING_ENABLED=False,
            HARLE_PLANNING_MODEL="gpt-4o",
            HARLE_PLANNING_MAX_TURNS=7,
            HARLE_PLANNED_MAX_TURNS=12,
        )
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("OPENAI_API_KEY", None)
            svc = build_orchestrator(settings=settings)
        assert svc.planning_enabled is False
        assert svc.planning_model == "gpt-4o"
        assert svc.planning_max_turns == 7
        assert svc.planned_max_turns == 12


class TestOrchestratorPlanning:
    """Level 3 planning path with mocked runner_execution."""

    @pytest.fixture(autouse=True)
    def _patch_create_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "harle.db.runs.create_run",
            lambda *args, **kwargs: None,
        )

    def test_agent_runner_delegates_to_run_agent_execution(self) -> None:
        with patch("harle.orchestrator.runner_execution.run_agent_execution") as r:
            r.return_value = AgentExecutionResult(
                text="done",
                tools_called=["dataset_search"],
                turns_used=2,
                routing_method="direct",
            )
            db = make_in_memory_chat_db()
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                use_agent_runner=True,
            )
            resp = svc.chat(request=RunRequest(message="hello", context="personal"))
            r.assert_called_once()
            assert resp.result == "done"
            assert resp.tools_called == ["dataset_search"]
            assert resp.turns_used == 2

    def test_planning_disabled_passes_flag(self) -> None:
        with patch("harle.orchestrator.runner_execution.run_agent_execution") as r:
            r.return_value = AgentExecutionResult(text="ok")
            db = make_in_memory_chat_db()
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                use_agent_runner=True,
                planning_enabled=False,
            )
            svc.chat(request=RunRequest(message="hello", context="work"))
            assert r.call_args.kwargs["planning_enabled"] is False

    def test_planned_run_returns_routing_and_plan_metadata(self) -> None:
        with patch("harle.orchestrator.runner_execution.run_agent_execution") as r:
            r.return_value = AgentExecutionResult(
                text="Answer with REVISED PLAN:\n1. [output] x",
                plan_text="1. [search] a\n2. [output] b",
                plan_revisions=["1. [output] x"],
                routing_method="planned",
            )
            db = make_in_memory_chat_db()
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                use_agent_runner=True,
            )
            resp = svc.chat(
                request=RunRequest(message="research and compare X vs Y", context="work"),
            )
            assert resp.status == "completed"
            assert "REVISED PLAN" in resp.result or "Answer" in resp.result


class TestOrchestratorReflection:
    """Level 4 reflection metadata with mocked runner_execution."""

    @pytest.fixture(autouse=True)
    def _patch_create_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "harle.db.runs.create_run",
            lambda *args, **kwargs: None,
        )

    def test_chat_returns_reflection_fields(self) -> None:
        with patch("harle.orchestrator.runner_execution.run_agent_execution") as r:
            r.return_value = AgentExecutionResult(
                text="done",
                reflection_triggered=True,
                reflection_improved=True,
                reflection_record=ReflectionRunRecord(
                    trigger_reason="planned",
                    tool_count_at_trigger=0,
                    verdict="improve",
                    assessment="ok",
                    improvements_suggested=("add detail",),
                    improvement_pass_ran=True,
                    improvement_pass_completed=True,
                    improvement_turns=2,
                    improvement_tools_called=("dataset_search",),
                ),
            )
            db = make_in_memory_chat_db()
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                use_agent_runner=True,
            )
            resp = svc.chat(request=RunRequest(message="hello", context="personal"))
            assert resp.reflection_triggered is True
            assert resp.reflection_improved is True


# ══════════════════════════════════════════════════════════════════════
# OrchestratorService.chat — multi-turn conversations
# ══════════════════════════════════════════════════════════════════════


class TestOrchestratorChat:
    """Tests for the chat() method with conversation management."""

    @pytest.fixture(autouse=True)
    def _patch_create_run(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Avoid persisting to runs table; SQLite test DB has no runs table (ARRAY)."""
        monkeypatch.setattr(
            "harle.db.runs.create_run",
            lambda *args, **kwargs: None,
        )

    def test_chat_requires_db(self) -> None:
        svc = OrchestratorService(llm_provider=EchoProvider(), db=None)
        req = RunRequest(message="hello", context="personal")
        with pytest.raises(RuntimeError, match="Database is required"):
            svc.chat(request=req)

    def test_chat_creates_new_conversation(self) -> None:
        db = make_in_memory_chat_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="hello", context="work")
        resp = svc.chat(request=req)

        assert resp.status == "completed"
        assert resp.conversation_id is not None
        assert resp.conversation_id.startswith("conv_")
        assert resp.context == "work"

    def test_chat_stores_messages(self) -> None:
        db = make_in_memory_chat_db()
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
        db = make_in_memory_chat_db()
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
        db = make_in_memory_chat_db()
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
        db = make_in_memory_chat_db()
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
        db = make_in_memory_chat_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        ids = {
            svc.chat(request=RunRequest(message="hi", context="work")).run_id
            for _ in range(5)
        }
        assert len(ids) == 5

    def test_chat_response_includes_optional_fields(self) -> None:
        """Chat response includes tools_called and turns_used."""
        db = make_in_memory_chat_db()
        svc = OrchestratorService(llm_provider=EchoProvider(), db=db)
        req = RunRequest(message="hello", context="personal")
        resp = svc.chat(request=req)
        assert resp.tools_called is None
        assert resp.turns_used is None
