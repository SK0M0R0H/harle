"""Tests for :mod:`harle.api.auth` bearer middleware."""

from __future__ import annotations

import secrets

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from harle.api.auth import BearerAuthMiddleware, _is_public_health_path


def _app_with_middleware(token: str) -> FastAPI:
    app = FastAPI()

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/reindex")
    def reindex() -> dict[str, str]:
        return {"status": "reindexed"}

    app.add_middleware(BearerAuthMiddleware, token=token)
    return app


class TestHealthPathExemption:
    def test_exact_health(self) -> None:
        assert _is_public_health_path("/health") is True

    def test_health_subpaths(self) -> None:
        assert _is_public_health_path("/health/connections") is True
        assert _is_public_health_path("/health/tools") is True

    def test_non_health(self) -> None:
        assert _is_public_health_path("/chat") is False
        assert _is_public_health_path("/healthy") is False


class TestBearerAuthMiddleware:
    def test_health_ok_without_authorization(self) -> None:
        client = TestClient(_app_with_middleware("secret-token"))
        r = client.get("/health")
        assert r.status_code == 200
        assert r.json() == {"status": "ok"}

    def test_protected_missing_header_returns_401(self) -> None:
        client = TestClient(_app_with_middleware("secret-token"))
        r = client.post("/reindex")
        assert r.status_code == 401
        assert r.json()["detail"] == "Invalid or missing API token."

    def test_protected_wrong_token_returns_401(self) -> None:
        client = TestClient(_app_with_middleware("secret-token"))
        r = client.post(
            "/reindex",
            headers={"Authorization": "Bearer wrong"},
        )
        assert r.status_code == 401

    def test_protected_valid_bearer_returns_200(self) -> None:
        client = TestClient(_app_with_middleware("secret-token"))
        r = client.post(
            "/reindex",
            headers={"Authorization": "Bearer secret-token"},
        )
        assert r.status_code == 200
        assert r.json()["status"] == "reindexed"

    def test_bearer_scheme_case_insensitive(self) -> None:
        client = TestClient(_app_with_middleware("secret-token"))
        r = client.post(
            "/reindex",
            headers={"Authorization": "bearer secret-token"},
        )
        assert r.status_code == 200

    def test_uses_secrets_compare_digest(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[tuple[str, str]] = []
        real_compare = secrets.compare_digest

        def spy(a: str, b: str) -> bool:
            captured.append((a, b))
            return real_compare(a, b)

        monkeypatch.setattr("harle.api.auth.secrets.compare_digest", spy)
        client = TestClient(_app_with_middleware("same-length-ok"))
        r = client.post(
            "/reindex",
            headers={"Authorization": "Bearer same-length-ok"},
        )
        assert r.status_code == 200
        assert len(captured) == 1
        assert captured[0] == ("same-length-ok", "same-length-ok")


class TestRejectedAuthLogging:
    def test_rejection_logs_warning(self, caplog: pytest.LogCaptureFixture) -> None:
        import logging

        caplog.set_level(logging.WARNING)
        client = TestClient(_app_with_middleware("good"))
        client.post("/reindex", headers={"Authorization": "Bearer bad"})
        assert any(
            "API token rejected" in rec.message for rec in caplog.records
        ), caplog.records
