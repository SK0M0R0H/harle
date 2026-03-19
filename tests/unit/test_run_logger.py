"""Unit tests for harle.logging.run_logger and harle.dataset.writer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from harle.dataset.writer import write_log_file
from harle.logging.run_logger import build_result_body, log_run_to_vault


class TestWriteLogFile:
    """Tests for write_log_file."""

    def test_write_log_file_creates_parent_dirs(self, tmp_path: Path) -> None:
        rel = "logs/2026/02/run_abc_result.md"
        write_log_file(tmp_path, rel, "# Result\n\nBody.")
        path = tmp_path / "logs" / "2026" / "02" / "run_abc_result.md"
        assert path.exists()
        assert path.read_text(encoding="utf-8") == "# Result\n\nBody."

    def test_write_log_file_overwrites_existing(self, tmp_path: Path) -> None:
        rel = "logs/run.md"
        write_log_file(tmp_path, rel, "First")
        write_log_file(tmp_path, rel, "Second")
        assert (tmp_path / "logs" / "run.md").read_text(encoding="utf-8") == "Second"


class TestBuildResultBody:
    """Tests for build_result_body."""

    def test_completed_uses_result_text(self) -> None:
        assert build_result_body(
            status="completed", result_text="Done.", summary="S"
        ) == "Done."

    def test_completed_uses_summary_when_no_result_text(self) -> None:
        assert build_result_body(
            status="completed", result_text=None, summary="Summary"
        ) == "Summary"

    def test_completed_empty_when_neither(self) -> None:
        assert build_result_body(
            status="completed", result_text=None, summary=None
        ) == ""

    def test_failed_uses_summary(self) -> None:
        assert build_result_body(
            status="failed", summary="Error: connection refused"
        ) == "Error: connection refused"

    def test_failed_default_when_no_summary(self) -> None:
        assert build_result_body(status="failed", summary=None) == "Run failed before completion"

    def test_timeout_with_duration_ms(self) -> None:
        assert build_result_body(
            status="timeout",
            summary="Partial",
            duration_ms=5000,
        ) == "Partial (elapsed: 5000 ms)"

    def test_timeout_without_duration_ms(self) -> None:
        assert build_result_body(
            status="timeout", summary=None
        ) == "Run timed out before completion"

    def test_timeout_with_summary_no_duration(self) -> None:
        assert build_result_body(
            status="timeout", summary="Still running", duration_ms=None
        ) == "Still running"

    def test_aborted_uses_summary(self) -> None:
        assert build_result_body(
            status="aborted", summary="User closed tab"
        ) == "User closed tab"

    def test_aborted_default_when_no_summary(self) -> None:
        assert build_result_body(status="aborted", summary=None) == (
            "Client disconnected before response completed"
        )

    def test_unknown_status_uses_summary(self) -> None:
        assert build_result_body(
            status="cancelled", summary="Cancelled"
        ) == "Cancelled"

    def test_unknown_status_uses_result_text_as_fallback(self) -> None:
        assert build_result_body(
            status="unknown", result_text="Some text", summary=None
        ) == "Some text"

    def test_unknown_status_empty_fallback(self) -> None:
        assert build_result_body(
            status="other", result_text=None, summary=None
        ) == ""


class TestLogRunToVault:
    """Tests for log_run_to_vault."""

    def test_writes_result_file_with_frontmatter(self, tmp_path: Path) -> None:
        ts = datetime(2026, 2, 19, 14, 30, 0, tzinfo=timezone.utc)
        result_path, context_path = log_run_to_vault(
            tmp_path,
            run_id="run_abc123",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="The agent did something.",
            store_context=False,
        )
        assert result_path == "logs/2026/02/run_abc123_result.md"
        assert context_path is None
        path = tmp_path / "logs" / "2026" / "02" / "run_abc123_result.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert 'run_id: "run_abc123"' in content
        assert 'agent: "secretary"' in content
        assert 'status: "completed"' in content
        assert 'context_scope: "work"' in content
        assert "# Result" in content
        assert "The agent did something." in content

    def test_writes_context_file_when_store_context_true(self, tmp_path: Path) -> None:
        ts = datetime(2026, 2, 19, 14, 30, 0, tzinfo=timezone.utc)
        result_path, context_path = log_run_to_vault(
            tmp_path,
            run_id="run_xyz",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="personal",
            result_body="Result text.",
            context_body="System prompt content.",
            store_context=True,
        )
        assert result_path == "logs/2026/02/run_xyz_result.md"
        assert context_path == "logs/2026/02/run_xyz_context.md"
        ctx_path = tmp_path / "logs" / "2026" / "02" / "run_xyz_context.md"
        assert ctx_path.exists()
        assert "System prompt content." in ctx_path.read_text(encoding="utf-8")
        assert "# Assembled context" in ctx_path.read_text(encoding="utf-8")

    def test_does_not_write_context_when_store_context_false(self, tmp_path: Path) -> None:
        ts = datetime(2026, 2, 19, 14, 30, 0, tzinfo=timezone.utc)
        result_path, context_path = log_run_to_vault(
            tmp_path,
            run_id="run_no_ctx",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="Ok",
            context_body="Should not be written",
            store_context=False,
        )
        assert result_path is not None
        assert context_path is None
        ctx_path = tmp_path / "logs" / "2026" / "02" / "run_no_ctx_context.md"
        assert not ctx_path.exists()

    def test_returns_none_when_dataset_path_does_not_exist(self) -> None:
        result_path, context_path = log_run_to_vault(
            Path("/nonexistent/dataset"),
            run_id="run_any",
            timestamp=datetime.now(timezone.utc),
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="Body",
        )
        assert result_path is None
        assert context_path is None

    def test_naive_datetime_appends_z_in_frontmatter(self, tmp_path: Path) -> None:
        ts = datetime(2026, 3, 10, 12, 0, 0)
        assert ts.tzinfo is None
        result_path, _ = log_run_to_vault(
            tmp_path,
            run_id="run_naive",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="Ok",
        )
        assert result_path is not None
        content = (tmp_path / "logs" / "2026" / "03" / "run_naive_result.md").read_text(
            encoding="utf-8"
        )
        assert "2026-03-10T12:00:00Z" in content

    def test_store_context_true_without_context_body_does_not_write_context(
        self, tmp_path: Path
    ) -> None:
        ts = datetime(2026, 2, 19, 14, 30, 0, tzinfo=timezone.utc)
        result_path, context_path = log_run_to_vault(
            tmp_path,
            run_id="run_no_body",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="Result",
            context_body=None,
            store_context=True,
        )
        assert result_path == "logs/2026/02/run_no_body_result.md"
        assert context_path is None
        assert not (tmp_path / "logs" / "2026" / "02" / "run_no_body_context.md").exists()

    def test_relative_dataset_path_resolved(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        ts = datetime(2026, 2, 19, 14, 30, 0, tzinfo=timezone.utc)
        result_path, _ = log_run_to_vault(
            Path("."),
            run_id="run_rel",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="Ok",
        )
        assert result_path == "logs/2026/02/run_rel_result.md"
        assert (tmp_path / "logs" / "2026" / "02" / "run_rel_result.md").exists()
