"""Vault exporter — write span trees as Markdown to the vault logs/ directory.

Receives completed spans from the OTel ``BatchSpanProcessor``,
reconstructs the parent-child tree, and writes a human-readable
``<sanitized_run_id>_trace.md`` file alongside the Run Logger's output
    (the YAML ``run_id`` field keeps the full value).

The file is written once when all spans for a trace are flushed
(at the end of a request or when the batch processor flushes).
"""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from harle.dataset.frontmatter import dump_frontmatter_fields
from harle.dataset.writer import log_dir_for, write_log_file
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

_TRACE_FILENAME_MAX = 120


def _safe_trace_filename_stem(run_id: str) -> str:
    """Make *run_id* safe for log filenames (no ``/``, colons, or wide unicode)."""
    stem = re.sub(r"[^\w.\-]+", "_", run_id, flags=re.UNICODE)
    stem = stem.strip("._") or "trace"
    return stem[:_TRACE_FILENAME_MAX]


class VaultExporter(SpanExporter):
    """Write execution traces as Markdown files to ``vault/logs/YYYY/MM/``.

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

        traces = group_by_trace(spans)
        for trace_id, trace_spans in traces.items():
            try:
                self._write_trace(trace_id, trace_spans)
            except Exception:
                logger.exception("Failed to write execution trace %s", trace_id)

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    def _write_trace(self, trace_id: str, spans: list[ReadableSpan]) -> None:
        """Build tree, render Markdown, write to vault."""
        if not self._vault_path.exists():
            logger.warning("Vault path does not exist: %s; skipping execution trace", self._vault_path)
            return

        filtered = filter_by_level(spans, self._min_level)
        if not filtered:
            return

        root = find_root(filtered)
        if root is None:
            return

        run_id = extract_run_id(filtered)
        timestamp = span_start_time(root)

        tree = build_tree(filtered)
        duration_ms = span_duration_ms(root)

        content = _render_markdown(
            run_id=run_id,
            timestamp=timestamp,
            total_spans=len(filtered),
            duration_ms=duration_ms,
            root=root,
            tree=tree,
        )

        log_dir = log_dir_for(timestamp)
        safe_stem = _safe_trace_filename_stem(run_id)
        rel_path = f"{log_dir}/{safe_stem}_trace.md"
        write_log_file(self._vault_path, rel_path, content)


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
    fm = {
        "run_id": run_id,
        "timestamp": ts_str,
        "total_spans": total_spans,
        "duration_ms": duration_ms,
    }
    fm_yaml = dump_frontmatter_fields(fm)
    lines = [
        "---",
        fm_yaml,
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
    duration = span_duration_ms(span)
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
