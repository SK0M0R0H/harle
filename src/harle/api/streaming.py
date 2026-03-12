"""SSE streaming helpers for debug-mode endpoints.

When ``?debug=true`` is passed to ``/run`` or ``/chat``, the response
is an SSE stream.  Debug spans arrive as ``event: debug`` and the
final result is emitted as ``event: result``.
"""

from __future__ import annotations

import json
import logging
from queue import Empty, Queue
from typing import TYPE_CHECKING, Any, Generator

if TYPE_CHECKING:
    from harle.api.models import RunResponse

logger = logging.getLogger(__name__)


def drain_debug_events(queue: Queue[dict[str, Any]]) -> Generator[dict[str, str], None, None]:
    """Yield all debug events currently in the queue.

    Returns SSE-formatted dicts with ``event`` and ``data`` keys.
    Non-blocking: stops when the queue is empty.
    """
    while True:
        try:
            evt = queue.get_nowait()
        except Empty:
            break
        yield {
            "event": "debug",
            "data": json.dumps(evt),
        }


def result_event(response: RunResponse) -> dict[str, str]:
    """Format a RunResponse as an SSE ``result`` event."""
    return {
        "event": "result",
        "data": response.model_dump_json(),
    }
