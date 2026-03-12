"""Shared span-processing helpers used by multiple exporters.

Functions here operate on ``ReadableSpan`` instances from the OTel SDK
and are used by both the vault exporter and the database exporter.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from typing import Sequence

from opentelemetry.sdk.trace import ReadableSpan

from harle.debug.levels import TraceLevel


def group_by_trace(spans: Sequence[ReadableSpan]) -> dict[str, list[ReadableSpan]]:
    """Group spans by their trace ID."""
    groups: dict[str, list[ReadableSpan]] = defaultdict(list)
    for s in spans:
        ctx = s.context
        if ctx is not None:
            tid = format(ctx.trace_id, "032x")
            groups[tid].append(s)
    return groups


def filter_by_level(spans: list[ReadableSpan], min_level: TraceLevel) -> list[ReadableSpan]:
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


def find_root(spans: list[ReadableSpan]) -> ReadableSpan | None:
    """Return the root span (no parent) or the earliest span."""
    for s in spans:
        if s.parent is None:
            return s
    return min(spans, key=lambda s: s.start_time or 0) if spans else None


def extract_run_id(root: ReadableSpan) -> str:
    """Extract run_id from the root span name or attributes."""
    if root.attributes:
        rid = root.attributes.get("run_id")
        if rid:
            return str(rid)
    return root.name


def span_start_time(span: ReadableSpan) -> datetime:
    """Convert OTel nanosecond timestamp to datetime."""
    if span.start_time:
        return datetime.fromtimestamp(span.start_time / 1e9, tz=timezone.utc)
    return datetime.now(timezone.utc)


def span_duration_ms(span: ReadableSpan) -> int:
    """Compute span duration in milliseconds."""
    if span.start_time and span.end_time:
        return int((span.end_time - span.start_time) / 1e6)
    return 0


def build_tree(spans: list[ReadableSpan]) -> dict[int, list[ReadableSpan]]:
    """Build a parent-to-children mapping keyed by span ID."""
    children: dict[int, list[ReadableSpan]] = defaultdict(list)
    for s in spans:
        parent_ctx = s.parent
        if parent_ctx is not None:
            children[parent_ctx.span_id].append(s)
    for kids in children.values():
        kids.sort(key=lambda s: s.start_time or 0)
    return children
