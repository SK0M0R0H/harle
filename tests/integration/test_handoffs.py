"""Integration tests for Level 5 multi-agent handoffs (vault, DB, API wiring)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harle.api.models import RunRequest
from harle.api.routes import build_router
from harle.llm.providers import EchoProvider
from harle.orchestrator.agents import HandoffRecord
from harle.orchestrator.runner_execution import AgentExecutionResult
from harle.orchestrator.service import OrchestratorService
from tests.conftest import make_in_memory_chat_db


@pytest.mark.integration
class TestHandoffsVaultAndPersistence:
    """Handoff metadata in vault logs and ``create_run``."""

    def test_handoffs_section_appended_to_vault(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="Done after handoff.",
                handoffs=[
                    HandoffRecord(
                        source_agent="researcher",
                        target_agent="secretary",
                        reason="User asked to organize tasks.",
                    )
                ],
                final_agent="secretary",
                routing_method="keyword_match",
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
            svc.chat(request=RunRequest(message="hello", context="work"))

        result_files = list(tmp_path.glob("logs/**/*_result.md"))
        assert len(result_files) == 1
        content = result_files[0].read_text(encoding="utf-8")
        assert "## Handoffs" in content
        assert "researcher" in content
        assert "secretary" in content

    def test_create_run_receives_handoffs(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def capture_create_run(_session: object, **kwargs: object) -> None:
            captured.update(kwargs)

        monkeypatch.setattr("harle.db.runs.create_run", capture_create_run)

        ho = [
            HandoffRecord(
                source_agent="writer",
                target_agent="researcher",
                reason="Need sources.",
            )
        ]

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="ok",
                handoffs=ho,
                final_agent="researcher",
            )

        db = make_in_memory_chat_db()
        with patch(
            "harle.orchestrator.runner_execution.run_agent_execution",
            side_effect=fake_run,
        ):
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                use_agent_runner=True,
            )
            svc.chat(request=RunRequest(message="draft email", context="work"))

        stored = captured.get("handoffs")
        assert isinstance(stored, list)
        assert len(stored) == 1
        assert stored[0]["source_agent"] == "writer"
        assert stored[0]["target_agent"] == "researcher"
        assert "sources" in stored[0]["reason"]


@pytest.mark.integration
class TestHandoffsHttpPipeline:
    """POST /chat exposes handoff fields on RunResponse."""

    def test_chat_response_includes_handoffs(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="ok",
                handoffs=[
                    HandoffRecord(
                        source_agent="researcher",
                        target_agent="writer",
                        reason="Polish the summary.",
                    )
                ],
                final_agent="writer",
            )

        db = make_in_memory_chat_db()
        with patch(
            "harle.orchestrator.runner_execution.run_agent_execution",
            side_effect=fake_run,
        ):
            svc = OrchestratorService(
                llm_provider=EchoProvider(),
                db=db,
                use_agent_runner=True,
            )
            app = FastAPI()
            app.include_router(build_router(orchestrator=svc, db=db))
            client = TestClient(app)
            r = client.post(
                "/chat",
                json={"message": "summarize this", "context": "work"},
            )

        assert r.status_code == 200
        body = r.json()
        assert body.get("handoffs") is not None
        assert len(body["handoffs"]) == 1
        assert body["handoffs"][0]["target_agent"] == "writer"
