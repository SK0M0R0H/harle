"""Vault exporter — write span trees as Markdown to the vault logs/ directory.

Receives completed spans from the OTel ``BatchSpanProcessor``,
reconstructs the parent-child tree, and writes a human-readable
``<run_id>_debug.md`` file alongside the Run Logger's output.

The file is written once when all spans for a trace are flushed
(at the end of a request or when the batch processor flushes).
"""

from __future__ import annotations

import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from harle.dataset.writer import log_dir_for, write_log_file
from harle.debug.levels import TraceLevel

logger = logging.getLogger(__name__)


class VaultExporter(SpanExporter):
    """Write debug traces as Markdown files to ``vault/logs/YYYY/MM/``.

    Each trace (identified by ``trace_id``) produces one file.  Spans
    are filtered by ``min_level`` before rendering.
    """

    def __init__(self, vault_path: str, *, min_level: TraceLevel = TraceLevel.TRACE) -> None:
        self._vault_path = Path(vault_path)
        self._min_level = min_level

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Receive a batch of completed spans and write trace files."""
        if not spans:
            return SpanExportResult.SUCCESS

        traces = _group_by_trace(spans)
        for trace_id, trace_spans in traces.items():
            try:
                self._write_trace(trace_id, trace_spans)
            except Exception:
                logger.exception("Failed to write debug trace %s", trace_id)

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def _write_trace(self, trace_id: str, spans: list[ReadableSpan]) -> None:
        """Build tree, render Markdown, write to vault."""
        if not self._vault_path.exists():
            logger.warning("Vault path does not exist: %s; skipping debug trace", self._vault_path)
            return

        filtered = _filter_by_level(spans, self._min_level)
        if not filtered:
            return

        root = _find_root(filtered)
        if root is None:
            return

        run_id = _extract_run_id(root)
        timestamp = _span_start_time(root)

        tree = _build_tree(filtered)
        duration_ms = _span_duration_ms(root)

        content = _render_markdown(
            run_id=run_id,
            timestamp=timestamp,
            total_spans=len(filtered),
            duration_ms=duration_ms,
            root=root,
            tree=tree,
        )

        log_dir = log_dir_for(timestamp)
        rel_path = f"{log_dir}/{run_id}_debug.md"
        write_log_file(self._vault_path, rel_path, content)


def _group_by_trace(spans: Sequence[ReadableSpan]) -> dict[str, list[ReadableSpan]]:
    """Group spans by their trace ID."""
    groups: dict[str, list[ReadableSpan]] = defaultdict(list)
    for s in spans:
        ctx = s.context
        if ctx is not None:
            tid = format(ctx.trace_id, "032x")
            groups[tid].append(s)
    return groups


def _filter_by_level(spans: list[ReadableSpan], min_level: TraceLevel) -> list[ReadableSpan]:
    """Keep spans whose ``harle.level`` is at or above *min_level*."""
    result = []
    for s in spans:
        level_name = s.attributes.get("harle.level", "STEP") if s.attributes else "STEP"
        try:
            level = TraceLevel[str(level_name)]
        except KeyError:
            level = TraceLevel.STEP
        if level <= min_level:
            result.append(s)
    return result


def _find_root(spans: list[ReadableSpan]) -> ReadableSpan | None:
    """Return the root span (no parent) or the earliest span."""
    for s in spans:
        if s.parent is None:
            return s
    return min(spans, key=lambda s: s.start_time or 0) if spans else None


def _extract_run_id(root: ReadableSpan) -> str:
    """Extract run_id from the root span name or attributes."""
    if root.attributes:
        rid = root.attributes.get("run_id")
        if rid:
            return str(rid)
    return root.name


def _span_start_time(span: ReadableSpan) -> datetime:
    """Convert OTel nanosecond timestamp to datetime."""
    if span.start_time:
        return datetime.fromtimestamp(span.start_time / 1e9, tz=timezone.utc)
    return datetime.now(timezone.utc)


def _span_duration_ms(span: ReadableSpan) -> int:
    """Compute span duration in milliseconds."""
    if span.start_time and span.end_time:
        return int((span.end_time - span.start_time) / 1e6)
    return 0


def _build_tree(spans: list[ReadableSpan]) -> dict[int, list[ReadableSpan]]:
    """Build a parent→children mapping keyed by span ID."""
    children: dict[int, list[ReadableSpan]] = defaultdict(list)
    for s in spans:
        parent_ctx = s.parent
        if parent_ctx is not None:
            children[parent_ctx.span_id].append(s)
    for kids in children.values():
        kids.sort(key=lambda s: s.start_time or 0)
    return children


def _render_markdown(
    *,
    run_id: str,
    timestamp: datetime,
    total_spans: int,
    duration_ms: int,
    root: ReadableSpan,
    tree: dict[int, list[ReadableSpan]],
) -> str:
    """Render the span tree as a human-readable Markdown document."""
    ts_str = timestamp.strftime("%Y-%m-%dT%H:%M:%SZ")
    lines = [
        "---",
        f"run_id: {run_id}",
        f"timestamp: {ts_str}",
        f"total_spans: {total_spans}",
        f"duration_ms: {duration_ms}",
        "---",
        "",
        f"# Debug Trace — {run_id}",
        "",
    ]

    _render_span(root, tree, lines, depth=0)
    lines.append("")
    return "\n".join(lines)


def _render_span(
    span: ReadableSpan,
    tree: dict[int, list[ReadableSpan]],
    lines: list[str],
    depth: int,
) -> None:
    """Recursively render a span and its children."""
    level_name = _get_level_name(span)
    duration = _span_duration_ms(span)
    name = span.name

    duration_suffix = f" ({duration}ms)" if duration > 0 else ""

    if depth == 0:
        lines.append(f"## [{level_name}] {name}{duration_suffix}")
        lines.append("")
    elif depth == 1:
        lines.append(f"### [{level_name}] {name}{duration_suffix}")
    else:
        indent = "  " * (depth - 2)
        lines.append(f"{indent}- [{level_name}] {name}{duration_suffix}")

    attrs = _render_attrs(span)
    if attrs:
        attr_indent = "  " * max(0, depth - 1)
        for attr_line in attrs:
            if depth <= 1:
                lines.append(f"- {attr_line}")
            else:
                lines.append(f"{attr_indent}  - {attr_line}")

    ctx = span.context
    if ctx is not None:
        children = tree.get(ctx.span_id, [])
        for child in children:
            _render_span(child, tree, lines, depth + 1)


def _get_level_name(span: ReadableSpan) -> str:
    """Extract the ``harle.level`` attribute, defaulting to ``STEP``."""
    if span.attributes:
        return str(span.attributes.get("harle.level", "STEP"))
    return "STEP"


def _render_attrs(span: ReadableSpan) -> list[str]:
    """Render non-internal span attributes as key: value strings."""
    if not span.attributes:
        return []
    skip = {"harle.level", "harle.module", "run_id"}
    result = []
    for key, value in span.attributes.items():
        if key in skip:
            continue
        result.append(f"{key}: {value}")
    return result
