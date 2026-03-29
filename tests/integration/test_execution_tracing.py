"""Integration tests for execution tracing (vault and DB exporters).

Verifies that a full /chat request produces a trace file in the vault
and a row in the execution_traces table when tracing is configured.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from harle.api.processing_registry import build_processing_registry
from harle.api.routes import build_router
from harle.db.connection import Database
from harle.db.models import Conversation, ExecutionTrace, Message
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService

from tests.tracing_harness import flush_otel, reset_tracer_provider_and_configure


@pytest.mark.integration
class TestExecutionTracingIntegration:
    """End-to-end: /chat with tracing enabled writes to vault and DB."""

    def test_chat_produces_vault_trace_and_db_row(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """POST /chat with tracing configured writes merged run log to vault and a DB row."""
        db_path = tmp_path / "trace.db"
        db_url = f"sqlite:///{db_path}"
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        ExecutionTrace.__table__.create(engine, checkfirst=True)
        Conversation.__table__.create(engine, checkfirst=True)
        Message.__table__.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        monkeypatch.setattr("harle.db.runs.create_run", lambda *args, **kwargs: None)

        db = Database.__new__(Database)
        db.engine = engine
        db._session_factory = session_factory

        reset_tracer_provider_and_configure(
            monkeypatch,
            vault_path=str(tmp_path),
            vault_enabled=True,
            db_url=db_url,
            db_enabled=True,
        )

        app = FastAPI()
        app.include_router(
            build_router(
                orchestrator=OrchestratorService(
                    llm_provider=EchoProvider(),
                    db=db,
                    dataset_path=str(tmp_path),
                ),
                processing_registry=build_processing_registry(run_timeout_seconds=60),
                db=db,
            )
        )
        client = TestClient(app)

        response = client.post("/chat", json={"message": "Trace me", "context": "work"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        run_id = data["run_id"]
        assert run_id.startswith("run_")

        flush_otel(1000)

        log_files = [f for f in tmp_path.rglob("*.md") if run_id in f.name]
        assert len(log_files) >= 1, f"Expected at least one run log .md under {tmp_path}"
        trace_file = log_files[0]
        content = trace_file.read_text(encoding="utf-8")
        assert "handle_chat" in content
        assert run_id in content
        assert "# Result" in content
        assert "# Execution Trace" in content

        with session_factory() as session:
            from harle.db.execution_traces import get_execution_trace

            row = get_execution_trace(session, run_id)
        assert row is not None
        assert row.run_id == run_id
        assert row.total_spans >= 1
        assert "name" in row.trace_json
        assert row.trace_json["name"] == "handle_chat"
