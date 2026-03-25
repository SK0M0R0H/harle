"""Unit tests for harle.logging.run_logger and harle.dataset.writer."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from harle.dataset.writer import write_log_file
from harle.logging.artifacts import clear_run_artifact_store, peek_artifact, pop_artifact
from harle.logging.run_logger import (
    build_result_body,
    flush_registered_run_log_without_trace,
    log_run_to_vault,
)


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


def _flush_artifact(tmp_path: Path, run_id: str, result_path: str) -> None:
    assert flush_registered_run_log_without_trace(tmp_path, run_id, result_path)


def test_flush_registered_run_log_without_trace_returns_false_when_empty() -> None:
    clear_run_artifact_store()
    try:
        assert (
            flush_registered_run_log_without_trace(
                Path("/tmp"), "missing", "logs/x.md"
            )
            is False
        )
    finally:
        clear_run_artifact_store()


def test_flush_registered_write_failure_leaves_artifact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    clear_run_artifact_store()
    try:
        ts = datetime(2026, 7, 1, 12, 0, 0, tzinfo=timezone.utc)
        result_path, _ = log_run_to_vault(
            tmp_path,
            run_id="run_wfail",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="keep me",
        )
        assert result_path is not None

        def _boom(*_a: object, **_k: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("harle.dataset.writer.write_log_file", _boom)
        with pytest.raises(OSError, match="disk full"):
            flush_registered_run_log_without_trace(tmp_path, "run_wfail", result_path)

        art = peek_artifact("run_wfail")
        assert art is not None
        assert art.result_body == "keep me"
        assert not (tmp_path / result_path).exists()
    finally:
        clear_run_artifact_store()


class TestLogRunToVault:
    """Tests for log_run_to_vault (registers artifacts; flush simulates finalize fallback)."""

    def setup_method(self) -> None:
        clear_run_artifact_store()

    def teardown_method(self) -> None:
        clear_run_artifact_store()

    def test_registers_result_artifact_and_flush_writes_file(self, tmp_path: Path) -> None:
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
        assert result_path == "logs/2026/02/run_abc123.md"
        assert context_path is None
        _flush_artifact(tmp_path, "run_abc123", result_path)
        path = tmp_path / "logs" / "2026" / "02" / "run_abc123.md"
        assert path.exists()
        content = path.read_text(encoding="utf-8")
        assert 'run_id: "run_abc123"' in content
        assert 'agent: "secretary"' in content
        assert 'status: "completed"' in content
        assert 'context_scope: "work"' in content
        assert "# Result" in content
        assert "The agent did something." in content

    def test_single_file_includes_context_when_store_context_true(self, tmp_path: Path) -> None:
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
        assert result_path == "logs/2026/02/run_xyz.md"
        assert context_path is None
        _flush_artifact(tmp_path, "run_xyz", result_path)
        path = tmp_path / "logs" / "2026" / "02" / "run_xyz.md"
        assert path.exists()
        text = path.read_text(encoding="utf-8")
        assert "System prompt content." in text
        assert "# Assembled context" in text
        assert "Result text." in text

    def test_does_not_include_context_when_store_context_false(self, tmp_path: Path) -> None:
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
        _flush_artifact(tmp_path, "run_no_ctx", result_path)
        text = (tmp_path / "logs" / "2026" / "02" / "run_no_ctx.md").read_text(encoding="utf-8")
        assert "Should not be written" not in text

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
        _flush_artifact(tmp_path, "run_naive", result_path)
        content = (tmp_path / "logs" / "2026" / "03" / "run_naive.md").read_text(
            encoding="utf-8"
        )
        assert "2026-03-10T12:00:00Z" in content

    def test_store_context_true_without_context_body_does_not_include_context_section(
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
        assert result_path == "logs/2026/02/run_no_body.md"
        assert context_path is None
        _flush_artifact(tmp_path, "run_no_body", result_path)
        text = (tmp_path / "logs" / "2026" / "02" / "run_no_body.md").read_text(encoding="utf-8")
        assert "# Assembled context" not in text

    def test_conversation_id_in_frontmatter(self, tmp_path: Path) -> None:
        ts = datetime(2026, 2, 19, 14, 30, 0, tzinfo=timezone.utc)
        result_path, _ = log_run_to_vault(
            tmp_path,
            run_id="run_conv",
            timestamp=ts,
            agent="secretary",
            status="completed",
            context_scope="work",
            result_body="Hi",
            conversation_id="conv_abc",
        )
        assert result_path is not None
        _flush_artifact(tmp_path, "run_conv", result_path)
        text = (tmp_path / "logs" / "2026" / "02" / "run_conv.md").read_text(encoding="utf-8")
        assert 'conversation_id: "conv_abc"' in text

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
        assert result_path == "logs/2026/02/run_rel.md"
        _flush_artifact(tmp_path, "run_rel", result_path)
        assert (tmp_path / "logs" / "2026" / "02" / "run_rel.md").exists()
