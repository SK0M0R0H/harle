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


def _span_name_usable_as_run_id_fallback(name: str) -> bool:
    """True if *name* looks like an opaque id, not a structured span label.

    Span names often use ``Category: detail`` (tools, modules, steps). Those
    contain ``:`` and must not be used as ``run_id`` in YAML frontmatter or
    filenames without quoting — and they are not Harle ``run_*`` ids anyway.
    """
    n = (name or "").strip()
    if not n:
        return False
    # Any colon makes the string a label, not a safe bare run_id fallback.
    if ":" in n:
        return False
    return True


def extract_run_id(spans: Sequence[ReadableSpan]) -> str:
    """Extract run_id from any span attributes, then from a sensible root name.

    Batches may lack ``run_id`` on the root while using labeled span names
    (e.g. ``Tool: …``, ``Step: …``); we scan *all* spans for ``run_id`` first,
    and only fall back to the root name when it has no ``:`` (not a label).
    """
    if not spans:
        return "unknown_trace"
    for s in spans:
        if s.attributes:
            rid = s.attributes.get("run_id")
            if rid is not None and str(rid).strip():
                return str(rid)
    root = find_root(list(spans))
    if root is not None:
        name = root.name or ""
        if _span_name_usable_as_run_id_fallback(name):
            return name.strip()
    return "unknown_trace"


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
