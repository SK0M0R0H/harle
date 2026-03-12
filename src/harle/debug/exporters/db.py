"""PostgreSQL exporter — write span trees as JSONB to the debug_traces table.

Receives completed spans from the OTel ``BatchSpanProcessor``,
reconstructs the span tree, serialises it to JSON, and inserts one
row per trace into the ``debug_traces`` table.
"""

from __future__ import annotations

import logging
from typing import Any, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from harle.debug.exporters._spans import (
    build_tree,
    extract_run_id,
    filter_by_level,
    find_root,
    group_by_trace,
    span_duration_ms,
    span_start_time,
)
from harle.debug.levels import TraceLevel

logger = logging.getLogger(__name__)


class PostgresExporter(SpanExporter):
    """Write debug traces as JSONB rows to the ``debug_traces`` table.

    Each trace (identified by ``trace_id``) produces one row.  Spans
    are filtered by ``min_level`` before serialisation.
    """

    def __init__(self, database_url: str, *, min_level: TraceLevel = TraceLevel.TRACE) -> None:
        self._database_url = database_url
        self._min_level = min_level
        self._engine = None

    def _get_engine(self):
        if self._engine is None:
            from sqlalchemy import create_engine
            self._engine = create_engine(self._database_url, pool_pre_ping=True)
        return self._engine

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Receive a batch of completed spans and write trace rows."""
        if not spans:
            return SpanExportResult.SUCCESS

        traces = group_by_trace(spans)
        for trace_id, trace_spans in traces.items():
            try:
                self._write_trace(trace_spans)
            except Exception:
                logger.exception("Failed to write debug trace to DB for trace %s", trace_id)

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        if self._engine is not None:
            self._engine.dispose()
            self._engine = None

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def _write_trace(self, spans: list[ReadableSpan]) -> None:
        """Build tree, serialise to JSON, insert into DB."""
        filtered = filter_by_level(spans, self._min_level)
        if not filtered:
            return

        root = find_root(filtered)
        if root is None:
            return

        run_id = extract_run_id(root)
        duration = span_duration_ms(root)
        tree = build_tree(filtered)
        trace_json = _serialise_tree(root, tree)

        from sqlalchemy.orm import Session, sessionmaker
        from harle.db.debug_traces import create_debug_trace

        engine = self._get_engine()
        session_factory = sessionmaker(bind=engine)
        session: Session = session_factory()
        try:
            create_debug_trace(
                session,
                run_id=run_id,
                trace_json=trace_json,
                total_spans=len(filtered),
                duration_ms=duration,
            )
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()


def _serialise_tree(root: ReadableSpan, tree: dict[int, list[ReadableSpan]]) -> dict[str, Any]:
    """Recursively convert a span tree to a JSON-compatible dict."""
    return _serialise_span(root, tree)


def _serialise_span(span: ReadableSpan, tree: dict[int, list[ReadableSpan]]) -> dict[str, Any]:
    """Convert a single span and its children to a dict."""
    result: dict[str, Any] = {
        "name": span.name,
        "level": _get_level(span),
        "duration_ms": span_duration_ms(span),
        "start_time": span_start_time(span).isoformat(),
    }

    attrs = _get_attrs(span)
    if attrs:
        result["attributes"] = attrs

    ctx = span.context
    if ctx is not None:
        children = tree.get(ctx.span_id, [])
        if children:
            result["children"] = [_serialise_span(c, tree) for c in children]

    return result


def _get_level(span: ReadableSpan) -> str:
    if span.attributes:
        return str(span.attributes.get("harle.level", "STEP"))
    return "STEP"


def _get_attrs(span: ReadableSpan) -> dict[str, Any]:
    """Extract non-internal attributes from a span."""
    if not span.attributes:
        return {}
    skip = {"harle.level", "harle.module", "run_id"}
    return {k: v for k, v in span.attributes.items() if k not in skip}
