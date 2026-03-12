"""Unit tests for harle.debug — trace levels, dtrace API, setup, vault exporter."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from opentelemetry.sdk.trace.export import SpanExportResult

from harle.debug import dtrace
from harle.debug.levels import TraceLevel
from harle.debug.setup import configure_tracing
from harle.debug.exporters.vault import (
    VaultExporter,
    _build_tree,
    _extract_run_id,
    _filter_by_level,
    _find_root,
    _group_by_trace,
    _render_attrs,
    _span_duration_ms,
    _span_start_time,
)


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
# dtrace API (trace.py) — NoOp mode (no TracerProvider) and with provider
# ---------------------------------------------------------------------------


class TestDtraceNoOp:
    """Tests for dtrace API when no TracerProvider is set (NoOp spans)."""

    def test_step_does_not_raise(self) -> None:
        dtrace.step("test step", module="test")

    def test_detail_does_not_raise(self) -> None:
        dtrace.detail("test detail", module="test", key="value")

    def test_trace_entry_does_not_raise(self) -> None:
        dtrace.trace_entry("test trace", module="test")

    def test_internal_does_not_raise(self) -> None:
        dtrace.internal("test internal", module="test")

    def test_span_context_manager_does_not_raise(self) -> None:
        with dtrace.span("test_span", level=dtrace.STEP, module="test"):
            dtrace.detail("inside", count=3)

    def test_span_fn_sync_returns_value(self) -> None:
        @dtrace.span_fn(level=dtrace.STEP, module="test")
        def fn() -> int:
            return 42

        assert fn() == 42

    def test_span_fn_async_returns_value(self) -> None:
        @dtrace.span_fn(level=dtrace.STEP, module="test")
        async def fn() -> int:
            return 99

        assert asyncio.run(fn()) == 99


class TestDtraceWithProvider:
    """Tests for dtrace API with a real TracerProvider and capturing exporter."""

    @pytest.fixture(autouse=True)
    def _configure_tracing_with_vault(self, tmp_path: Path) -> None:
        """Set up tracing so spans are captured and written to tmp_path."""
        configure_tracing(
            vault_path=str(tmp_path),
            vault_enabled=True,
            min_storage_level="TRACE",
        )

    def test_span_and_step_produce_vault_file(self, tmp_path: Path) -> None:
        with dtrace.span(
            "handle_request",
            level=dtrace.STEP,
            module="orchestrator",
            run_id="run_unittest1",
        ):
            dtrace.step("Context assembled", module="orchestrator", tokens=100)
            dtrace.detail("Search query", module="search", query="test")

        from opentelemetry import trace

        provider = trace.get_tracer_provider()
        provider.force_flush()

        debug_files = list(tmp_path.rglob("*_debug.md"))
        assert len(debug_files) == 1
        content = debug_files[0].read_text(encoding="utf-8")
        assert "run_id: run_unittest1" in content
        assert "handle_request" in content
        assert "Context assembled" in content
        assert "Search query" in content
        assert "[STEP]" in content
        assert "[DETAIL]" in content


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

    def test_invalid_min_storage_level_raises(self) -> None:
        with pytest.raises(KeyError):
            configure_tracing(
                vault_path=None,
                vault_enabled=False,
                min_storage_level="INVALID",
            )


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

        debug_files = list(tmp_path.rglob("*_debug.md"))
        assert len(debug_files) == 1
        content = debug_files[0].read_text(encoding="utf-8")
        assert "run_id: run_vault_test" in content
        assert "handle_request" in content
        assert "child_span" in content
        assert "tokens: 100" in content or "100" in content

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
        assert not list(tmp_path.rglob("*_debug.md"))


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
        groups = _group_by_trace(exporter.spans)
        assert len(groups) == 1
        assert len(list(groups.values())[0]) == 1

    def test_filter_by_level(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("step_span") as s:
            s.set_attribute("harle.level", "STEP")
        with tracer.start_as_current_span("internal_span") as s:
            s.set_attribute("harle.level", "INTERNAL")
        provider.force_flush()
        filtered = _filter_by_level(exporter.spans, TraceLevel.DETAIL)
        names = [sp.name for sp in filtered]
        assert "step_span" in names
        assert "internal_span" not in names

    def test_find_root_returns_span_with_no_parent(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root"):
            with tracer.start_as_current_span("child"):
                pass
        provider.force_flush()
        root = _find_root(exporter.spans)
        assert root is not None
        assert root.parent is None
        assert root.name == "root"

    def test_extract_run_id_from_attribute(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("handle_request") as s:
            s.set_attribute("run_id", "run_abc123")
        provider.force_flush()
        root = _find_root(exporter.spans)
        assert root is not None
        assert _extract_run_id(root) == "run_abc123"

    def test_extract_run_id_falls_back_to_name(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("run_xyz789"):
            pass
        provider.force_flush()
        root = _find_root(exporter.spans)
        assert root is not None
        assert _extract_run_id(root) == "run_xyz789"

    def test_span_start_time_from_timestamp(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("t"):
            pass
        provider.force_flush()
        span = exporter.spans[0]
        ts = _span_start_time(span)
        assert ts.tzinfo is not None

    def test_span_duration_ms(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("t"):
            pass
        provider.force_flush()
        span = exporter.spans[0]
        duration = _span_duration_ms(span)
        assert isinstance(duration, int)
        assert duration >= 0

    def test_build_tree_parent_child(self) -> None:
        tracer, exporter, provider = _make_tracer_and_capture_spans()
        with tracer.start_as_current_span("root"):
            with tracer.start_as_current_span("child"):
                pass
        provider.force_flush()
        tree = _build_tree(exporter.spans)
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
