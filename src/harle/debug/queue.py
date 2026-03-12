"""Shared execution-trace event queue for SSE streaming.

The queue is created once (if trace streaming is active) and shared between
the :class:`~harle.debug.exporters.cli.CliSseExporter` (producer) and
the API SSE endpoints (consumer).
"""

from __future__ import annotations

from queue import Queue
from typing import Any

_trace_queue: Queue[dict[str, Any]] | None = None


def init_trace_queue() -> Queue[dict[str, Any]]:
    """Create and return the global trace event queue."""
    global _trace_queue
    _trace_queue = Queue()
    return _trace_queue


def get_trace_queue() -> Queue[dict[str, Any]] | None:
    """Return the trace queue if one has been initialised."""
    return _trace_queue
