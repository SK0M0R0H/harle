"""Tests for harle.orchestrator.service — OrchestratorService, build_orchestrator."""

from __future__ import annotations

import os
from unittest.mock import patch

from harle.api.models import RunRequest
from harle.config import Settings
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
