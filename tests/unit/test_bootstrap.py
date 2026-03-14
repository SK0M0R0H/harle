"""Tests for bootstrap initialisation gating logic."""

from __future__ import annotations

from harle import bootstrap


class _FakeReader:
    def __init__(self, dataset_path: str) -> None:
        self.dataset_path = dataset_path

    def list_files(self) -> list[str]:
        return ["a.md", "b.md"]


def test_ensure_initialized_skips_seed_and_index_when_already_ready(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(bootstrap, "create_tables", lambda db: calls.append("create_tables"))
    monkeypatch.setattr(bootstrap, "_dataset_seed_ready", lambda path: True)
    monkeypatch.setattr(bootstrap, "_file_index_populated", lambda db: True)

    def _seed_dataset(path: str) -> int:
        calls.append("seed_dataset")
        return 1

    def _run_initial_index(db: object, path: str) -> int:
        calls.append("run_initial_index")
        return 2

    monkeypatch.setattr(bootstrap, "seed_dataset", _seed_dataset)
    monkeypatch.setattr(bootstrap, "run_initial_index", _run_initial_index)
    monkeypatch.setattr(bootstrap, "DatasetReader", _FakeReader)

    result = bootstrap.ensure_initialized(db=object(), dataset_path="/tmp/vault")

    assert calls == ["create_tables"]
    assert result["files_seeded"] == 0
    assert result["files_indexed"] == 0
    assert result["total_files"] == 2
    assert result["already_initialized"] is True


def test_ensure_initialized_runs_seed_and_index_when_not_ready(monkeypatch) -> None:
    calls: list[str] = []

    monkeypatch.setattr(bootstrap, "create_tables", lambda db: calls.append("create_tables"))
    monkeypatch.setattr(bootstrap, "_dataset_seed_ready", lambda path: False)
    monkeypatch.setattr(bootstrap, "_file_index_populated", lambda db: False)

    def _seed_dataset(path: str) -> int:
        calls.append("seed_dataset")
        return 3

    def _run_initial_index(db: object, path: str) -> int:
        calls.append("run_initial_index")
        return 5

    monkeypatch.setattr(bootstrap, "seed_dataset", _seed_dataset)
    monkeypatch.setattr(bootstrap, "run_initial_index", _run_initial_index)
    monkeypatch.setattr(bootstrap, "DatasetReader", _FakeReader)

    result = bootstrap.ensure_initialized(db=object(), dataset_path="/tmp/vault")

    assert calls == ["create_tables", "seed_dataset", "run_initial_index"]
    assert result["files_seeded"] == 3
    assert result["files_indexed"] == 5
    assert result["total_files"] == 2
    assert result["already_initialized"] is False
