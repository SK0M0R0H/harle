"""Integration tests for Level 3 plan-then-execute (orchestrator, vault, API).

Exercises wiring between chat, ``run_agent_execution`` / Agents SDK stubs,
vault result logs, and ``create_run`` metadata without calling the live OpenAI API.
"""

from __future__ import annotations

import sys
import types
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harle.api.models import RunRequest
from harle.api.routes import build_router
from harle.db.connection import Database
from harle.llm.providers import EchoProvider
from harle.orchestrator.runner_execution import AgentExecutionResult
from harle.orchestrator.service import OrchestratorService
from tests.conftest import make_in_memory_chat_db


@pytest.mark.integration
class TestPlanThenExecuteVaultAndPersistence:
    """Orchestrator + vault logs + DB run metadata for planned runs."""

    def test_planned_run_writes_plan_section_to_vault_result(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Completed run with plan metadata appends ``## Plan`` to the vault result file."""
        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="Done.\n\nREVISED PLAN:\n1. [output] Skip web search",
                plan_text=(
                    "1. [search] Look in dataset\n"
                    "2. [web_search] External context\n"
                    "3. [output] Summarize"
                ),
                plan_revisions=["1. [output] Skip web search"],
                routing_method="planned",
                tools_called=["dataset_search"],
                turns_used=2,
            )

        db = make_in_memory_chat_db()
        with patch(
            "harle.orchestrator.runner_execution.run_agent_execution",
            side_effect=fake_run,
        ):
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                dataset_path=str(tmp_path),
                use_agent_runner=True,
                planning_enabled=True,
            )
            resp = svc.chat(
                request=RunRequest(
                    message=(
                        "Research and compare approach A vs B in detail using "
                        "dataset and web sources."
                    ),
                    context="work",
                ),
            )

        assert resp.status == "completed"
        result_files = list(tmp_path.glob("logs/**/*_result.md"))
        assert len(result_files) == 1
        content = result_files[0].read_text(encoding="utf-8")
        assert "## Plan" in content
        assert "Initial plan" in content
        assert "Revision 1" in content
        assert "[search]" in content

    def test_planned_run_writes_planning_tool_outputs_to_vault(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """When execution reports planning tool context, vault includes it under Plan."""
        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        tool_section = (
            "## Planning phase — tool results\n\n"
            "The planning agent already ran these tools.\n\n"
            "### dataset_search\n\n"
            '{"hits": [{"id": "doc-1"}]}\n'
        )

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="Done.",
                plan_text="1. [search] x\n2. [output] y",
                planning_tool_context=tool_section,
                routing_method="planned",
                tools_called=["dataset_search"],
                turns_used=2,
            )

        db = make_in_memory_chat_db()
        with patch(
            "harle.orchestrator.runner_execution.run_agent_execution",
            side_effect=fake_run,
        ):
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                dataset_path=str(tmp_path),
                use_agent_runner=True,
                planning_enabled=True,
            )
            resp = svc.chat(
                request=RunRequest(
                    message=(
                        "Research and compare approach A vs B in detail using "
                        "dataset and web sources."
                    ),
                    context="work",
                ),
            )

        assert resp.status == "completed"
        result_files = list(tmp_path.glob("logs/**/*_result.md"))
        assert len(result_files) == 1
        content = result_files[0].read_text(encoding="utf-8")
        assert "### Planning tool outputs" in content
        assert "doc-1" in content

    def test_create_run_receives_routing_method_planned(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``runs.routing_method`` is ``planned`` when execution reports a plan."""
        captured: dict[str, object] = {}

        def capture_create_run(
            session: object,
            **kwargs: object,
        ) -> None:
            captured.clear()
            captured.update(kwargs)

        monkeypatch.setattr("harle.db.runs.create_run", capture_create_run)

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="Answer only.",
                plan_text="1. [search] x\n2. [output] y",
                routing_method="planned",
                tools_called=[],
                turns_used=1,
            )

        db = make_in_memory_chat_db()
        with patch(
            "harle.orchestrator.runner_execution.run_agent_execution",
            side_effect=fake_run,
        ):
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                dataset_path=str(tmp_path),
                use_agent_runner=True,
            )
            svc.chat(
                request=RunRequest(
                    message="Analyze and report on several sources in depth.",
                    context="work",
                ),
            )

        assert captured.get("routing_method") == "planned"


@pytest.mark.integration
class TestPlanThenExecuteHttpPipeline:
    """FastAPI ``POST /chat`` with agent runner and planning stubs."""

    def test_post_chat_planned_run_returns_assistant_text(
        self,
        chat_db: Database,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """HTTP layer returns the execution result from a mocked planned run."""
        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="Structured report body.",
                plan_text="1. [output] Report",
                routing_method="planned",
                turns_used=1,
            )

        with patch(
            "harle.orchestrator.runner_execution.run_agent_execution",
            side_effect=fake_run,
        ):
            app = FastAPI()
            app.include_router(
                build_router(
                    orchestrator=OrchestratorService(
                        llm_provider=EchoProvider(),
                        db=chat_db,
                        dataset_path=str(tmp_path),
                        use_agent_runner=True,
                    ),
                    db=chat_db,
                )
            )
            client = TestClient(app)
            response = client.post(
                "/chat",
                json={
                    "message": (
                        "Prepare a multi-section research report comparing "
                        "privacy techniques with citations."
                    ),
                    "context": "work",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"] == "Structured report body."


@pytest.mark.integration
class TestPlanThenExecuteAgentsSdkStub:
    """Two ``Runner.run_sync`` calls (planner then researcher) for complex messages."""

    def test_complex_message_runs_planner_then_researcher(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Complex user text triggers planning phase then execution phase (stub SDK)."""
        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        calls: list[dict[str, object]] = []

        class _FakeAgent:
            def __init__(self, **kwargs: object) -> None:
                self._kwargs = kwargs

            @property
            def name(self) -> str:
                return str(self._kwargs.get("name", ""))

            @property
            def instructions(self) -> str:
                return str(self._kwargs.get("instructions", ""))

        class _FakeRunner:
            @staticmethod
            def run_sync(
                agent: object,
                user_message: str,
                max_turns: int = 10,
            ) -> object:
                plan_body = (
                    "1. [search] Dataset sweep\n"
                    "2. [web_search] External refs\n"
                    "3. [output] Final write-up"
                )
                planner_tool_items: list[object] = []
                if getattr(agent, "name", None) == "planner":
                    final = plan_body
                    planner_tool_items = [
                        SimpleNamespace(
                            type="tool_call_item",
                            raw_item=SimpleNamespace(name="dataset_search"),
                        ),
                        SimpleNamespace(
                            type="tool_call_output_item",
                            output={"hits": [{"id": "planner-seen-id"}]},
                            raw_item=None,
                        ),
                    ]
                else:
                    final = "Summary.\n\nREVISED PLAN:\n1. [output] Shorter path"

                calls.append(
                    {
                        "agent_name": getattr(agent, "name", None),
                        "max_turns": max_turns,
                        "instructions": getattr(agent, "instructions", ""),
                    }
                )

                class _Result:
                    final_output = final
                    new_items = planner_tool_items
                    raw_responses = [object()]

                return _Result()

        fake_agents = types.SimpleNamespace(
            Agent=_FakeAgent,
            Runner=_FakeRunner,
            MaxTurnsExceeded=RuntimeError,
        )

        db = make_in_memory_chat_db()
        svc = OrchestratorService(
            llm_provider=EchoProvider(),
            db=db,
            use_agent_runner=True,
            planning_enabled=True,
            planning_max_turns=5,
            max_iterations=10,
            reflection_enabled=False,
        )

        # Heuristic classifier needs score >= 4 (e.g. length > 150 + research keyword).
        complex_message = (
            "Research privacy tradeoffs for our L2 stack, compare ZK and FHE, "
            "first gather dataset notes then web sources, then deliver a sourced "
            "report with next steps and citations. "
            + "Add benchmarks and assumptions. " * 6
        )

        with patch.dict(sys.modules, {"agents": fake_agents}):
            resp = svc.chat(
                request=RunRequest(
                    message=complex_message,
                    context="work",
                ),
            )

        assert resp.status == "completed"
        assert len(calls) == 2
        assert calls[0]["agent_name"] == "planner"
        assert calls[0]["max_turns"] == 5
        assert calls[1]["agent_name"] == "researcher"
        assert calls[1]["max_turns"] == 10
        exec_instructions = str(calls[1]["instructions"])
        assert "## Execution Plan" in exec_instructions
        assert "## Planning phase — tool results" in exec_instructions
        assert "dataset_search" in exec_instructions
        assert "planner-seen-id" in exec_instructions
        assert "REVISED PLAN" in (resp.result or "")
        # Planner phase tools are merged into tools_called for the run record
        assert resp.tools_called == ["dataset_search"]
