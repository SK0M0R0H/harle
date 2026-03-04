"""Unit tests for harle.db.runs — create_run, get_run, list_runs."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest

from harle.db.models import Run
from harle.db.runs import create_run, get_run, list_runs


class TestCreateRun:
    """Tests for create_run."""

    def test_create_run_minimal(self) -> None:
        session = MagicMock()
        run = create_run(
            session,
            run_id="run_abc123",
            timestamp=datetime.now(timezone.utc),
            user_request="Find tasks",
            context_scope="work",
            agent="secretary",
            status="completed",
        )
        session.add.assert_called_once()
        added = session.add.call_args[0][0]
        assert isinstance(added, Run)
        assert added.run_id == "run_abc123"
        assert added.user_request == "Find tasks"
        assert added.context_scope == "work"
        assert added.agent == "secretary"
        assert added.status == "completed"
        assert added.files_used is None
        assert added.result_path is None
        assert added.context_path is None

    def test_create_run_with_paths_and_files(self) -> None:
        session = MagicMock()
        ts = datetime.now(timezone.utc)
        run = create_run(
            session,
            run_id="run_xyz",
            timestamp=ts,
            user_request="Hello",
            context_scope="personal",
            agent="secretary",
            status="completed",
            files_used=["prompts/secretary.md", "knowledge/note.md"],
            result_path="logs/2026/02/run_xyz_result.md",
            context_path="logs/2026/02/run_xyz_context.md",
            result_summary="Short summary.",
            duration_ms=1500,
        )
        added = session.add.call_args[0][0]
        assert added.files_used == ["prompts/secretary.md", "knowledge/note.md"]
        assert added.result_path == "logs/2026/02/run_xyz_result.md"
        assert added.context_path == "logs/2026/02/run_xyz_context.md"
        assert added.result_summary == "Short summary."
        assert added.duration_ms == 1500


class TestGetRun:
    """Tests for get_run."""

    def test_get_run_returns_none_when_missing(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalar_one_or_none.return_value = None
        out = get_run(session, "run_nonexistent")
        assert out is None

    def test_get_run_returns_run_when_found(self) -> None:
        session = MagicMock()
        run = Run(
            run_id="run_found",
            timestamp=datetime.now(timezone.utc),
            user_request="Test",
            context_scope="work",
            agent="secretary",
            status="completed",
        )
        session.execute.return_value.scalar_one_or_none.return_value = run
        out = get_run(session, "run_found")
        assert out is run
        assert out.run_id == "run_found"


class TestListRuns:
    """Tests for list_runs."""

    def test_list_runs_returns_sequence(self) -> None:
        session = MagicMock()
        session.execute.return_value.scalars.return_value.all.return_value = []
        out = list_runs(session, limit=10)
        assert out == []

    def test_list_runs_with_filters(self) -> None:
        session = MagicMock()
        run = Run(
            run_id="run_1",
            timestamp=datetime.now(timezone.utc),
            user_request="Req",
            context_scope="work",
            agent="secretary",
            status="completed",
        )
        session.execute.return_value.scalars.return_value.all.return_value = [run]
        out = list_runs(
            session,
            limit=5,
            offset=0,
            agent="secretary",
            status="completed",
        )
        assert len(out) == 1
        assert out[0].run_id == "run_1"
