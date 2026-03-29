"""Integration tests for Level 4 reflection (vault, DB, API wiring)."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from harle.api.models import RunRequest
from harle.api.processing_registry import build_processing_registry
from harle.api.routes import build_router
from harle.llm.providers import EchoProvider
from harle.orchestrator.reflection import ReflectionRunRecord
from harle.orchestrator.runner_execution import AgentExecutionResult
from harle.orchestrator.service import OrchestratorService
from tests.conftest import make_in_memory_chat_db


@pytest.mark.integration
class TestReflectionVaultAndPersistence:
    """Reflection metadata in vault logs and create_run."""

    def test_reflection_section_appended_to_vault(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="Final answer.",
                reflection_triggered=True,
                reflection_improved=False,
                reflection_record=ReflectionRunRecord(
                    trigger_reason="planned",
                    tool_count_at_trigger=1,
                    verdict="pass",
                    assessment="Adequate.",
                    improvements_suggested=(),
                    improvement_pass_ran=False,
                    improvement_pass_completed=False,
                    improvement_turns=None,
                    improvement_tools_called=(),
                ),
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
                vault_tracing_enabled=False,
                use_agent_runner=True,
            )
            svc.chat(request=RunRequest(message="hello", context="work"))

        result_files = list(tmp_path.glob("logs/**/*.md"))
        assert len(result_files) == 1
        content = result_files[0].read_text(encoding="utf-8")
        assert "## Reflection" in content
        assert "pass" in content

    def test_create_run_receives_reflection_flags(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        captured: dict[str, object] = {}

        def capture_create_run(_session: object, **kwargs: object) -> None:
            captured.update(kwargs)

        monkeypatch.setattr("harle.db.runs.create_run", capture_create_run)

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="ok",
                reflection_triggered=True,
                reflection_improved=True,
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
            svc.chat(request=RunRequest(message="research report", context="work"))

        assert captured.get("reflection_triggered") is True
        assert captured.get("reflection_improved") is True


@pytest.mark.integration
class TestReflectionHttpPipeline:
    """POST /chat exposes reflection fields on RunResponse."""

    def test_chat_response_includes_reflection_fields(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        def fake_run(**kwargs: object) -> AgentExecutionResult:
            return AgentExecutionResult(
                text="ok",
                reflection_triggered=True,
                reflection_improved=False,
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
            app.include_router(
                build_router(
                    orchestrator=svc,
                    processing_registry=build_processing_registry(run_timeout_seconds=60),
                    db=db,
                )
            )
            client = TestClient(app)
            r = client.post(
                "/chat",
                json={"message": "hello", "context": "personal"},
            )
        assert r.status_code == 200
        data = r.json()
        assert data.get("reflection_triggered") is True
        assert data.get("reflection_improved") is False
