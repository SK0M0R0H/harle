"""Tests for server app startup wiring."""

from __future__ import annotations

from fastapi import APIRouter

from harle.config import Settings
from harle.main import create_app


class _FakeDatabase:
    def __init__(self, url: str) -> None:
        self.url = url


class _FakeSearchEngine:
    def __init__(self, dataset_path: str, db: object) -> None:
        self.dataset_path = dataset_path
        self.db = db


class _FakeDatasetReader:
    def __init__(self, dataset_path: str) -> None:
        self.dataset_path = dataset_path


def test_create_app_runs_startup_initialization_when_db_and_dataset_configured(monkeypatch) -> None:
    settings = Settings(DATABASE_URL="postgresql://example", HARLE_DATASET_PATH="/tmp/vault")
    ensure_calls: list[tuple[object, str]] = []

    monkeypatch.setattr("harle.main.load_settings", lambda: settings)
    monkeypatch.setattr("harle.main.configure_tracing", lambda **kwargs: None)
    monkeypatch.setattr("harle.db.connection.Database", _FakeDatabase)
    monkeypatch.setattr("harle.dataset.reader.DatasetReader", _FakeDatasetReader)
    monkeypatch.setattr("harle.search.engine.SearchEngine", _FakeSearchEngine)

    def _ensure_initialized(db: object, dataset_path: str) -> dict[str, object]:
        ensure_calls.append((db, dataset_path))
        return {
            "tables_created": True,
            "files_seeded": 0,
            "files_indexed": 0,
            "total_files": 10,
            "dataset_path": dataset_path,
            "already_initialized": True,
        }

    monkeypatch.setattr("harle.bootstrap.ensure_initialized", _ensure_initialized)
    monkeypatch.setattr("harle.tools.build_tool_registry", lambda **kwargs: object())
    monkeypatch.setattr("harle.main.build_orchestrator", lambda **kwargs: object())
    monkeypatch.setattr("harle.main.build_router", lambda **kwargs: APIRouter())

    app = create_app()

    assert app.title == "Harle"
    assert len(ensure_calls) == 1
    assert ensure_calls[0][1] == "/tmp/vault"
