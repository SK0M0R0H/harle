"""Integration tests for execution tracing (vault and DB exporters).

Verifies that a full /run request produces a trace file in the vault
and a row in the execution_traces table when tracing is configured.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry import trace
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from opentelemetry.sdk.trace import TracerProvider as SDKTracerProvider

from harle.api.routes import build_router
from harle.debug.setup import configure_tracing
from harle.db.models import ExecutionTrace
from harle.llm.providers import EchoProvider
from harle.orchestrator.service import OrchestratorService


def _tracer_provider_already_set() -> bool:
    """True if a real SDK TracerProvider was already set (e.g. by another test in the same run)."""
    provider = trace.get_tracer_provider()
    return isinstance(provider, SDKTracerProvider)


@pytest.mark.integration
class TestExecutionTracingIntegration:
    """End-to-end: /run with tracing enabled writes to vault and DB."""

    def test_run_produces_vault_trace_and_db_row(
        self,
        tmp_path: Path,
    ) -> None:
        """POST /run with tracing configured writes _trace.md to vault and a row to execution_traces."""
        if _tracer_provider_already_set():
            pytest.skip(
                "Global TracerProvider already set (run with pytest tests/integration for isolation)"
            )

        db_path = tmp_path / "trace.db"
        db_url = f"sqlite:///{db_path}"
        engine = create_engine(db_url, connect_args={"check_same_thread": False})
        ExecutionTrace.__table__.create(engine, checkfirst=True)
        session_factory = sessionmaker(bind=engine, expire_on_commit=False)

        configure_tracing(
            vault_path=str(tmp_path),
            vault_enabled=True,
            db_url=db_url,
            db_enabled=True,
            debug_mode=False,
        )

        app = FastAPI()
        app.include_router(
            build_router(orchestrator=OrchestratorService(llm_provider=EchoProvider()))
        )
        client = TestClient(app)

        response = client.post("/run", json={"message": "Trace me", "context": "work"})
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        run_id = data["run_id"]
        assert run_id.startswith("run_")

        provider = trace.get_tracer_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(1000)

        trace_files = list(tmp_path.rglob("*_trace.md"))
        assert len(trace_files) >= 1, f"Expected at least one _trace.md under {tmp_path}"
        trace_file = next(f for f in trace_files if run_id in f.name)
        content = trace_file.read_text(encoding="utf-8")
        assert "handle_request" in content
        assert run_id in content

        with session_factory() as session:
            from harle.db.execution_traces import get_execution_trace

            row = get_execution_trace(session, run_id)
        assert row is not None
        assert row.run_id == run_id
        assert row.total_spans >= 1
        assert "name" in row.trace_json
        assert row.trace_json["name"] == "handle_request"
