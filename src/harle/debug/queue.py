"""Shared debug event queue for SSE streaming.

The queue is created once (if debug mode is active) and shared between
the :class:`~harle.debug.exporters.cli.CliSseExporter` (producer) and
the API SSE endpoints (consumer).
"""

from __future__ import annotations

from queue import Queue
from typing import Any

_debug_queue: Queue[dict[str, Any]] | None = None


def init_debug_queue() -> Queue[dict[str, Any]]:
    """Create and return the global debug event queue."""
    global _debug_queue
    _debug_queue = Queue()
    return _debug_queue


def get_debug_queue() -> Queue[dict[str, Any]] | None:
    """Return the debug queue if one has been initialised."""
    return _debug_queue
