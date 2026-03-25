"""Unit tests for harle.debug — trace levels, etrace API, setup, vault/DB/CLI exporters, SSE."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool
from opentelemetry.sdk.trace.export import SpanExportResult

from harle.debug import etrace
from harle.debug.levels import TraceLevel
from harle.debug.setup import configure_tracing
from harle.debug.exporters._spans import (
    _span_name_usable_as_run_id_fallback,
    build_tree,
    extract_run_id,
    filter_by_level,
    find_root,
    group_by_trace,
    span_duration_ms,
    span_start_time,
)
from harle.debug.exporters.vault import VaultExporter, _render_attrs
from harle.db.models import ExecutionTrace
from harle.logging.artifacts import (
    RunArtifact,
    clear_run_artifact_store,
    peek_artifact,
    register_artifact,
)

from tests.tracing_harness import flush_otel, reset_tracer_provider_and_configure


# ---------------------------------------------------------------------------
# TraceLevel (levels.py)
# ---------------------------------------------------------------------------


class TestTraceLevel:
    """Tests for TraceLevel enum."""

    def test_level_values(self) -> None:
        assert TraceLevel.STEP == 1
        assert TraceLevel.DETAIL == 2
        assert TraceLevel.TRACE == 3
        assert TraceLevel.INTERNAL == 4

    def test_from_name_uppercase(self) -> None:
        assert TraceLevel.from_name("STEP") == TraceLevel.STEP
        assert TraceLevel.from_name("DETAIL") == TraceLevel.DETAIL
        assert TraceLevel.from_name("TRACE") == TraceLevel.TRACE
        assert TraceLevel.from_name("INTERNAL") == TraceLevel.INTERNAL

    def test_from_name_lowercase(self) -> None:
        assert TraceLevel.from_name("step") == TraceLevel.STEP
        assert TraceLevel.from_name("trace") == TraceLevel.TRACE

    def test_from_name_mixed_case(self) -> None:
        assert TraceLevel.from_name("Step") == TraceLevel.STEP

    def test_from_name_invalid_raises(self) -> None:
        with pytest.raises(KeyError):
            TraceLevel.from_name("INVALID")
        with pytest.raises(KeyError):
            TraceLevel.from_name("")


# ---------------------------------------------------------------------------
# etrace API (trace.py) — NoOp mode (no TracerProvider) and with provider
# ---------------------------------------------------------------------------


class TestDtraceNoOp:
    """Tests for etrace API when no TracerProvider is set (NoOp spans)."""

    def test_step_does_not_raise(self) -> None:
        etrace.step("test step", module="test")

    def test_detail_does_not_raise(self) -> None:
        etrace.detail("test detail", module="test", key="value")

    def test_trace_entry_does_not_raise(self) -> None:
        etrace.trace_entry("test trace", module="test")

    def test_internal_does_not_raise(self) -> None:
        etrace.internal("test internal", module="test")

    def test_span_context_manager_does_not_raise(self) -> None:
        with etrace.span("test_span", level=etrace.STEP, module="test"):
            etrace.detail("inside", count=3)

    def test_span_fn_sync_returns_value(self) -> None:
        @etrace.span_fn(level=etrace.STEP, module="test")
        def fn() -> int:
            return 42

        assert fn() == 42

    def test_span_fn_async_returns_value(self) -> None:
        @etrace.span_fn(level=etrace.STEP, module="test")
        async def fn() -> int:
            return 99

        assert asyncio.run(fn()) == 99


class TestDtraceWithProvider:
    """Tests for etrace API with a real TracerProvider and capturing exporter."""

    @pytest.fixture(autouse=True)
    def _configure_tracing_with_vault(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """Set up tracing so spans are captured and written to tmp_path."""
        reset_tracer_provider_and_configure(
            monkeypatch,
            vault_path=str(tmp_path),
            vault_enabled=True,
            db_enabled=False,
            min_storage_level="TRACE",
        )

    def test_span_and_step_produce_vault_file(self, tmp_path: Path) -> None:
        with etrace.span(
            "handle_request",
            level=etrace.STEP,
            module="orchestrator",
            run_id="run_unittest1",
        ):
            etrace.step("Context assembled", module="orchestrator", tokens=100)
            etrace.detail("Search query", module="search", query="test")

        flush_otel()

        debug_files = list(tmp_path.rglob("*.md"))
        assert len(debug_files) == 1
        content = debug_files[0].read_text(encoding="utf-8")
        assert 'run_id: "run_unittest1"' in content
        assert "handle_request" in content
        assert "Context assembled" in content
        assert "Search query" in content
        assert "[STEP]" in content
        assert "[DETAIL]" in content
        assert "# Execution Trace" in content


# ---------------------------------------------------------------------------
# configure_tracing (setup.py)
# ---------------------------------------------------------------------------


class TestConfigureTracing:
    """Tests for configure_tracing."""

    def test_accepts_vault_path_none(self) -> None:
        configure_tracing(vault_path=None, vault_enabled=True)
        from opentelemetry import trace

        assert trace.get_tracer_provider() is not None

    def test_accepts_vault_disabled(self) -> None:
        configure_tracing(vault_path="/some/path", vault_enabled=False)
        from opentelemetry import trace

        assert trace.get_tracer_provider() is not None

    def test_accepts_min_storage_level(self) -> None:
        configure_tracing(
            vault_path=None,
            vault_enabled=False,
            min_storage_level="DETAIL",
        )
        from opentelemetry import trace

        assert trace.get_tracer_provider() is not None

    def test_invalid_min_storage_level_uses_default(self) -> None:
        """Invalid min_storage_level is logged and TRACE is used; no exception."""
        configure_tracing(
            vault_path=None,
            vault_enabled=False,
            min_storage_level="INVALID",
        )
        from opentelemetry import trace

        assert trace.get_tracer_provider() is not None


# ---------------------------------------------------------------------------
# VaultExporter and vault helpers — use real ReadableSpan from SDK
# ---------------------------------------------------------------------------


def _make_tracer_and_capture_spans():
    """Create a TracerProvider that captures spans; return (tracer, exporter, provider).

    Does NOT set the global TracerProvider, so spans created with the returned
    tracer are processed only by the collecting exporter. Use the returned
    tracer to create spans, then exporter.spans to get ReadableSpan instances.
    """
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExportResult, SpanExporter

    class CollectingExporter(SpanExporter):
        def __init__(self) -> None:
            self.spans: list = []

        def export(self, spans) -> SpanExportResult:
            self.spans.extend(spans)
            return SpanExportResult.SUCCESS

        def shutdown(self) -> None:
            pass

        def force_flush(self, timeout_millis: int = 30000) -> bool:
            return True

    provider = TracerProvider()
    exporter = CollectingExporter()
    provider.add_span_processor(SimpleSpanProcessor(exporter))
    tracer = provider.get_tracer("test-debug")
    return tracer, exporter, provider


class TestVaultExporterIntegration:
    """Tests for VaultExporter using real spans from the SDK."""

    def setup_method(self) -> None:
        clear_run_artifact_store()

    def teardown_method(self) -> None:
        clear_run_artifact_store()

    def test_export_writes_debug_md_file(self, tmp_path: Path) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("handle_request") as root:
            root.set_attribute("harle.level", "STEP")
            root.set_attribute("run_id", "run_vault_test")
            root.set_attribute("harle.module", "orchestrator")
            with tracer.start_as_current_span("child_span") as child:
                child.set_attribute("harle.level", "DETAIL")
                child.set_attribute("tokens", 100)

        provider.force_flush()

        vault = VaultExporter(str(tmp_path), min_level=TraceLevel.TRACE)
        result = vault.export(exporter.spans)
        assert result == SpanExportResult.SUCCESS

        debug_files = list(tmp_path.rglob("*.md"))
        assert len(debug_files) == 1
        content = debug_files[0].read_text(encoding="utf-8")
        assert 'run_id: "run_vault_test"' in content
        assert "handle_request" in content
        assert "child_span" in content
        assert "tokens: 100" in content or "100" in content
        assert "# Execution Trace" in content

    def test_export_merges_registered_run_artifact(self, tmp_path: Path) -> None:
        from datetime import datetime, timezone

        ts = datetime(2026, 5, 1, 10, 0, 0, tzinfo=timezone.utc)
        register_artifact(
            RunArtifact(
                run_id="run_merged",
                timestamp=ts,
                agent="secretary",
                status="completed",
                context_scope="work",
                result_body="User-visible result.",
                context_body="CTX",
                conversation_id="conv_z",
            )
        )
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("handle_chat") as root:
            root.set_attribute("harle.level", "STEP")
            root.set_attribute("run_id", "run_merged")
            root.set_attribute("harle.module", "orchestrator")

        provider.force_flush()

        vault = VaultExporter(str(tmp_path), min_level=TraceLevel.TRACE)
        assert vault.export(exporter.spans) == SpanExportResult.SUCCESS

        paths = list(tmp_path.rglob("run_merged.md"))
        assert len(paths) == 1
        content = paths[0].read_text(encoding="utf-8")
        assert 'run_id: "run_merged"' in content
        assert 'agent: "secretary"' in content
        assert 'conversation_id: "conv_z"' in content
        assert "User-visible result." in content
        assert "# Assembled context" in content
        assert "CTX" in content
        assert "# Execution Trace" in content
        assert "handle_chat" in content
        assert "total_spans" in content

    def test_export_merged_uses_artifact_timestamp_for_log_subdir(self, tmp_path: Path) -> None:
        """``result_path`` uses finalize/artifact time; file must land in that YYYY/MM."""
        from datetime import datetime, timezone

        artifact_ts = datetime(2035, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
        register_artifact(
            RunArtifact(
                run_id="run_month_align",
                timestamp=artifact_ts,
                agent="secretary",
                status="completed",
                context_scope="work",
                result_body="ok",
            )
        )
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("handle_chat") as root:
            root.set_attribute("harle.level", "STEP")
            root.set_attribute("run_id", "run_month_align")
        provider.force_flush()

        vault = VaultExporter(str(tmp_path), min_level=TraceLevel.TRACE)
        assert vault.export(exporter.spans) == SpanExportResult.SUCCESS

        expected = tmp_path / "logs" / "2035" / "01" / "run_month_align.md"
        matches = list(tmp_path.rglob("run_month_align.md"))
        assert matches == [expected]

    def test_export_write_failure_leaves_artifact_in_store(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Merged write uses peek-then-pop-after-success so I/O errors can retry."""
        from datetime import datetime, timezone

        register_artifact(
            RunArtifact(
                run_id="run_io_fail",
                timestamp=datetime(2026, 6, 1, 0, 0, 0, tzinfo=timezone.utc),
                agent="secretary",
                status="completed",
                context_scope="work",
                result_body="must survive",
            )
        )
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("handle_chat") as root:
            root.set_attribute("harle.level", "STEP")
            root.set_attribute("run_id", "run_io_fail")
        provider.force_flush()

        def _boom(*_a: object, **_k: object) -> None:
            raise OSError("disk full")

        monkeypatch.setattr("harle.debug.exporters.vault.write_log_file", _boom)
        vault = VaultExporter(str(tmp_path), min_level=TraceLevel.TRACE)
        assert vault.export(exporter.spans) == SpanExportResult.SUCCESS

        art = peek_artifact("run_io_fail")
        assert art is not None
        assert art.result_body == "must survive"
        assert not list(tmp_path.rglob("run_io_fail.md"))

    def test_export_empty_spans_returns_success(self, tmp_path: Path) -> None:
        vault = VaultExporter(str(tmp_path), min_level=TraceLevel.TRACE)
        result = vault.export([])
        assert result == SpanExportResult.SUCCESS
        assert not list(tmp_path.rglob("*.md"))

    def test_export_skips_when_vault_path_does_not_exist(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root") as span:
            span.set_attribute("harle.level", "STEP")
            span.set_attribute("run_id", "run_orphan")

        provider.force_flush()

        vault = VaultExporter("/nonexistent/vault/path", min_level=TraceLevel.STEP)
        result = vault.export(exporter.spans)
        assert result == SpanExportResult.SUCCESS
        assert not Path("/nonexistent/vault/path").exists()

    def test_export_filters_by_min_level(self, tmp_path: Path) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root") as span:
            span.set_attribute("harle.level", "INTERNAL")
            span.set_attribute("run_id", "run_internal_only")

        provider.force_flush()

        vault = VaultExporter(str(tmp_path), min_level=TraceLevel.TRACE)
        vault.export(exporter.spans)
        assert not list(tmp_path.rglob("*.md"))

    @pytest.mark.parametrize(
        "run_id_value",
        [
            "Tool: notion_search",  # colon
            "task#123",            # hash (YAML comment char)
            "[step] optional",     # brackets
            "say \"hello\"",       # double quotes
            "it's fine",           # single quote / apostrophe
            "50%",                 # percent
            "key: value",         # colon + space
        ],
    )
    def test_export_run_id_edge_cases_writes_valid_yaml_frontmatter(
        self, tmp_path: Path, run_id_value: str
    ) -> None:
        """run_id with colons, quotes, #, etc. must be emitted as valid YAML."""
        from harle.dataset.frontmatter import parse_frontmatter

        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("handle_request") as root:
            root.set_attribute("harle.level", "STEP")
            root.set_attribute("run_id", run_id_value)
            root.set_attribute("harle.module", "orchestrator")

        provider.force_flush()

        vault = VaultExporter(str(tmp_path), min_level=TraceLevel.TRACE)
        result = vault.export(exporter.spans)
        assert result == SpanExportResult.SUCCESS

        debug_files = list(tmp_path.rglob("*.md"))
        assert len(debug_files) == 1
        content = debug_files[0].read_text(encoding="utf-8")
        meta, _ = parse_frontmatter(content, source_path="trace.md")
        assert meta.get("run_id") == run_id_value


# ---------------------------------------------------------------------------
# Vault module-level helpers (tested via real ReadableSpan from SDK)
# ---------------------------------------------------------------------------


class TestVaultHelpers:
    """Tests for vault exporter helper functions using real spans."""

    def test_group_by_trace(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("a"):
            pass
        provider.force_flush()
        groups = group_by_trace(exporter.spans)
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 1

    def test_filter_by_level(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("step_span") as s:
            s.set_attribute("harle.level", "STEP")
        with tracer.start_as_current_span("internal_span") as s:
            s.set_attribute("harle.level", "INTERNAL")
        provider.force_flush()
        filtered = filter_by_level(exporter.spans, TraceLevel.DETAIL)
        names = [sp.name for sp in filtered]
        assert "step_span" in names
        assert "internal_span" not in names

    def test_find_root_returns_span_with_no_parent(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root"):
            with tracer.start_as_current_span("child"):
                pass
        provider.force_flush()
        root = find_root(exporter.spans)
        assert root is not None
        assert root.parent is None
        assert root.name == "root"

    def test_extract_run_id_from_attribute(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("handle_request") as s:
            s.set_attribute("run_id", "run_abc123")
        provider.force_flush()
        root = find_root(exporter.spans)
        assert root is not None
        assert extract_run_id(exporter.spans) == "run_abc123"

    def test_extract_run_id_falls_back_to_name(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("run_xyz789"):
            pass
        provider.force_flush()
        root = find_root(exporter.spans)
        assert root is not None
        assert extract_run_id(exporter.spans) == "run_xyz789"

    def test_extract_run_id_prefers_attribute_on_any_span_when_root_is_tool(
        self,
    ) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("Tool: trello_list_boards") as tool:
            with tracer.start_as_current_span("child") as child:
                child.set_attribute("run_id", "run_from_child")
        provider.force_flush()
        assert extract_run_id(exporter.spans) == "run_from_child"

    def test_extract_run_id_unknown_when_only_labeled_root_name(self) -> None:
        """Span names with ':' are labels, not run ids — do not use as fallback."""
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("Module: some_step"):
            pass
        provider.force_flush()
        assert extract_run_id(exporter.spans) == "unknown_trace"

    def test_extract_run_id_empty_spans(self) -> None:
        assert extract_run_id([]) == "unknown_trace"

    def test_filter_by_level_defaults_when_attributes_none(self) -> None:
        span = MagicMock()
        span.attributes = None
        assert filter_by_level([span], TraceLevel.DETAIL) == [span]

    def test_filter_by_level_invalid_level_name_falls_back_to_step(self) -> None:
        span = MagicMock()
        span.attributes = {"harle.level": "NOT_A_REAL_LEVEL"}
        assert filter_by_level([span], TraceLevel.DETAIL) == [span]

    def test_find_root_uses_earliest_when_all_have_parent(self) -> None:
        parent_ctx = MagicMock()
        c1 = MagicMock()
        c1.parent = parent_ctx
        c1.start_time = 200
        c2 = MagicMock()
        c2.parent = parent_ctx
        c2.start_time = 100
        assert find_root([c1, c2]) is c2

    def test_span_start_time_from_timestamp(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("t"):
            pass
        provider.force_flush()
        span = exporter.spans[0]
        ts = span_start_time(span)
        assert ts.tzinfo is not None

    def test_span_start_time_falsy_timestamp_uses_now(self) -> None:
        span = MagicMock()
        span.start_time = 0
        ts = span_start_time(span)
        assert ts.tzinfo is not None

    def test_span_duration_ms(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("t"):
            pass
        provider.force_flush()
        span = exporter.spans[0]
        duration = span_duration_ms(span)
        assert isinstance(duration, int)
        assert duration >= 0

    def test_span_duration_ms_without_end_time(self) -> None:
        span = MagicMock()
        span.start_time = 100
        span.end_time = None
        assert span_duration_ms(span) == 0

    def test_span_name_usable_rejects_blank_and_colon(self) -> None:
        assert _span_name_usable_as_run_id_fallback("") is False
        assert _span_name_usable_as_run_id_fallback("   ") is False
        assert _span_name_usable_as_run_id_fallback("a: b") is False

    def test_build_tree_parent_child(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root"):
            with tracer.start_as_current_span("child"):
                pass
        provider.force_flush()
        tree = build_tree(exporter.spans)
        assert len(tree) >= 1
        total_children = sum(len(v) for v in tree.values())
        assert total_children == 1

    def test_render_attrs_skips_harle_level_and_module(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("t") as s:
            s.set_attribute("harle.level", "STEP")
            s.set_attribute("harle.module", "test")
            s.set_attribute("custom_key", "custom_value")
        provider.force_flush()
        span = exporter.spans[0]
        attrs = _render_attrs(span)
        assert any("custom_key" in a for a in attrs)
        assert not any("harle.level" in a for a in attrs)
        assert not any("harle.module" in a for a in attrs)


# ---------------------------------------------------------------------------
# VaultExporter shutdown and force_flush
# ---------------------------------------------------------------------------


class TestVaultExporterLifecycle:
    """Tests for VaultExporter lifecycle methods."""

    def test_shutdown_does_not_raise(self) -> None:
        exporter = VaultExporter("/tmp", min_level=TraceLevel.STEP)
        exporter.shutdown()

    def test_force_flush_returns_true(self) -> None:
        exporter = VaultExporter("/tmp", min_level=TraceLevel.STEP)
        assert exporter.force_flush(timeout_millis=1000) is True


# ---------------------------------------------------------------------------
# PostgresExporter — JSON serialisation (no real DB)
# ---------------------------------------------------------------------------


class TestPostgresExporterSerialisation:
    """Tests for PostgresExporter JSON tree serialisation."""

    def test_serialise_tree_produces_valid_json(self) -> None:
        from harle.debug.exporters.db import _serialise_tree

        tracer, collecting, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root") as root:
            root.set_attribute("harle.level", "STEP")
            root.set_attribute("run_id", "run_pg_test")
            with tracer.start_as_current_span("child") as child:
                child.set_attribute("harle.level", "DETAIL")
                child.set_attribute("tokens", 42)
        provider.force_flush()

        root_span = find_root(collecting.spans)
        assert root_span is not None
        tree = build_tree(collecting.spans)
        result = _serialise_tree(root_span, tree)

        assert result["name"] == "root"
        assert result["level"] == "STEP"
        assert "children" in result
        assert len(result["children"]) == 1
        assert result["children"][0]["name"] == "child"
        assert result["children"][0]["attributes"]["tokens"] == 42

    def test_empty_spans_returns_success(self) -> None:
        from harle.debug.exporters.db import PostgresExporter

        exporter = PostgresExporter("sqlite:///:memory:", min_level=TraceLevel.TRACE)
        result = exporter.export([])
        assert result == SpanExportResult.SUCCESS

    def test_force_flush_returns_true(self) -> None:
        from harle.debug.exporters.db import PostgresExporter

        exporter = PostgresExporter("sqlite:///:memory:", min_level=TraceLevel.TRACE)
        assert exporter.force_flush() is True

    def test_shutdown_disposes_engine(self) -> None:
        from harle.debug.exporters.db import PostgresExporter

        exporter = PostgresExporter("sqlite:///:memory:", min_level=TraceLevel.TRACE)
        exporter.shutdown()
        assert exporter._engine is None

    def test_get_engine_lazy_singleton(self) -> None:
        from harle.debug.exporters.db import PostgresExporter

        exporter = PostgresExporter("sqlite:///:memory:", min_level=TraceLevel.TRACE)
        assert exporter._engine is None
        e1 = exporter._get_engine()
        e2 = exporter._get_engine()
        assert e1 is e2
        exporter.shutdown()

    def test_export_writes_trace_row(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from harle.debug.exporters.db import PostgresExporter

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ExecutionTrace.__table__.create(engine)
        exporter = PostgresExporter("unused", min_level=TraceLevel.TRACE)
        monkeypatch.setattr(exporter, "_get_engine", lambda: engine)

        tracer, collecting, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root") as root:
            root.set_attribute("harle.level", "STEP")
            root.set_attribute("run_id", "run_db_test")
        provider.force_flush()

        assert exporter.export(collecting.spans) == SpanExportResult.SUCCESS
        with Session(engine) as session:
            rows = list(session.scalars(select(ExecutionTrace)).all())
        assert len(rows) == 1
        assert rows[0].run_id == "run_db_test"
        exporter.shutdown()

    def test_export_logs_and_continues_when_write_trace_fails(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        from harle.debug.exporters.db import PostgresExporter

        def boom(_spans: object) -> None:
            raise RuntimeError("write failed")

        exporter = PostgresExporter("sqlite:///:memory:", min_level=TraceLevel.TRACE)
        monkeypatch.setattr(exporter, "_write_trace", boom)
        tracer, collecting, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("a"):
            pass
        provider.force_flush()
        caplog.set_level(logging.ERROR)
        assert exporter.export(collecting.spans) == SpanExportResult.SUCCESS
        assert any("Failed to write execution trace" in r.message for r in caplog.records)

    def test_export_skips_write_when_min_level_filters_all_spans(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harle.debug.exporters.db import PostgresExporter

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ExecutionTrace.__table__.create(engine)
        exporter = PostgresExporter("unused", min_level=TraceLevel.STEP)
        monkeypatch.setattr(exporter, "_get_engine", lambda: engine)

        tracer, collecting, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("internal_only") as s:
            s.set_attribute("harle.level", "INTERNAL")
        provider.force_flush()

        assert exporter.export(collecting.spans) == SpanExportResult.SUCCESS
        with Session(engine) as session:
            assert list(session.scalars(select(ExecutionTrace)).all()) == []
        exporter.shutdown()

    def test_export_skips_insert_when_find_root_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harle.debug.exporters.db import PostgresExporter

        engine = create_engine(
            "sqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        ExecutionTrace.__table__.create(engine)
        exporter = PostgresExporter("unused", min_level=TraceLevel.TRACE)
        monkeypatch.setattr(exporter, "_get_engine", lambda: engine)
        monkeypatch.setattr("harle.debug.exporters.db.find_root", lambda _s: None)

        tracer, collecting, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root"):
            pass
        provider.force_flush()

        assert exporter.export(collecting.spans) == SpanExportResult.SUCCESS
        with Session(engine) as session:
            assert list(session.scalars(select(ExecutionTrace)).all()) == []
        exporter.shutdown()

    def test_get_level_defaults_without_attributes(self) -> None:
        from harle.debug.exporters.db import _get_level

        span = MagicMock()
        span.attributes = None
        assert _get_level(span) == "STEP"

    def test_json_safe_nested_and_fallback(self) -> None:
        from harle.debug.exporters.db import _json_safe

        assert _json_safe({"a": [1, {"b": 2}]}) == {"a": [1, {"b": 2}]}

        class Weird:
            def __str__(self) -> str:
                return "weird"

        assert _json_safe(Weird()) == "weird"


# ---------------------------------------------------------------------------
# CliSseExporter
# ---------------------------------------------------------------------------


class TestCliSseExporter:
    """Tests for the CLI SSE exporter."""

    def test_export_puts_events_on_queue(self) -> None:
        from queue import Queue
        from harle.debug.exporters.cli import CliSseExporter

        q: Queue = Queue()
        exporter = CliSseExporter(q, min_level=TraceLevel.STEP)

        tracer, collecting, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("step1") as s:
            s.set_attribute("harle.level", "STEP")
            s.set_attribute("harle.module", "orchestrator")
        provider.force_flush()

        result = exporter.export(collecting.spans)
        assert result == SpanExportResult.SUCCESS
        assert not q.empty()

        event = q.get_nowait()
        assert event["type"] == "debug"
        assert event["level"] == "STEP"
        assert event["name"] == "step1"

    def test_export_filters_below_min_level(self) -> None:
        from queue import Queue
        from harle.debug.exporters.cli import CliSseExporter

        q: Queue = Queue()
        exporter = CliSseExporter(q, min_level=TraceLevel.STEP)

        tracer, collecting, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("detail1") as s:
            s.set_attribute("harle.level", "DETAIL")
        provider.force_flush()

        exporter.export(collecting.spans)
        assert q.empty()

    def test_export_includes_attributes(self) -> None:
        from queue import Queue
        from harle.debug.exporters.cli import CliSseExporter

        q: Queue = Queue()
        exporter = CliSseExporter(q, min_level=TraceLevel.DETAIL)

        tracer, collecting, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("step2") as s:
            s.set_attribute("harle.level", "DETAIL")
            s.set_attribute("tokens", 99)
        provider.force_flush()

        exporter.export(collecting.spans)
        event = q.get_nowait()
        assert event["attributes"]["tokens"] == 99
        assert "harle.level" not in event.get("attributes", {})

    def test_force_flush_returns_true(self) -> None:
        from queue import Queue
        from harle.debug.exporters.cli import CliSseExporter

        exporter = CliSseExporter(Queue(), min_level=TraceLevel.STEP)
        assert exporter.force_flush() is True

    def test_shutdown_does_not_raise(self) -> None:
        from queue import Queue
        from harle.debug.exporters.cli import CliSseExporter

        exporter = CliSseExporter(Queue(), min_level=TraceLevel.STEP)
        exporter.shutdown()


# ---------------------------------------------------------------------------
# Debug queue module
# ---------------------------------------------------------------------------


class TestTraceQueue:
    """Tests for the shared trace queue module."""

    def test_init_and_get(self) -> None:
        from harle.debug.queue import init_trace_queue, get_trace_queue

        q = init_trace_queue()
        assert q is not None
        assert get_trace_queue() is q


# ---------------------------------------------------------------------------
# SSE streaming helpers (require pydantic)
# ---------------------------------------------------------------------------


try:
    import pydantic as _pydantic  # noqa: F401
    _has_pydantic = True
except ImportError:
    _has_pydantic = False


@pytest.mark.skipif(not _has_pydantic, reason="pydantic not installed")
class TestSseStreaming:
    """Tests for API SSE streaming helpers (requires pydantic)."""

    def test_drain_debug_events_empties_queue(self) -> None:
        from queue import Queue
        from harle.api.streaming import drain_debug_events

        q: Queue = Queue()
        q.put({"type": "debug", "level": "STEP", "name": "test"})
        q.put({"type": "debug", "level": "DETAIL", "name": "test2"})

        events = list(drain_debug_events(q))
        assert len(events) == 2
        assert all(e["event"] == "debug" for e in events)
        assert q.empty()

    def test_result_event_format(self) -> None:
        from harle.api.streaming import result_event
        from harle.api.models import RunResponse

        resp = RunResponse(
            run_id="r1", status="completed", result="ok", context="personal"
        )
        event = result_event(resp)
        assert event["event"] == "result"
        assert "r1" in event["data"]
