"""Unit tests for harle.logging.run_logger and harle.dataset.writer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from harle.dataset.writer import write_log_file
from harle.logging.run_logger import log_run_to_vault


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
        assert "run_id: run_abc123" in content
        assert "agent: secretary" in content
        assert "status: completed" in content
        assert "context_scope: work" in content
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
