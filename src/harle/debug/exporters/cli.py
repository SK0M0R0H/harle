"""CLI SSE exporter — push debug spans to an event queue for real-time streaming.

Used with ``SimpleSpanProcessor`` so each span is exported immediately
when it closes.  The exporter serialises the span to a compact dict
and puts it onto a :class:`queue.Queue` that the API SSE endpoint
reads from.

Only spans at or above *min_level* are emitted — this matches the
CLI's ``--debug`` / ``-dd`` / ``-ddd`` verbosity flags.
"""

from __future__ import annotations

import json
import logging
from queue import Queue
from typing import Any, Sequence

from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult

from harle.debug.exporters._spans import span_duration_ms
from harle.debug.levels import TraceLevel

logger = logging.getLogger(__name__)


class CliSseExporter(SpanExporter):
    """Push debug span events to a queue for SSE streaming to the CLI.

    Each exported span becomes one ``event: debug`` SSE event.
    The queue is shared with the API response handler which
    interleaves debug events with ``event: token`` events.
    """

    def __init__(
        self,
        sse_queue: Queue[dict[str, Any]],
        *,
        min_level: TraceLevel = TraceLevel.STEP,
    ) -> None:
        self._queue = sse_queue
        self._min_level = min_level

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Push each qualifying span onto the SSE queue."""
        for span in spans:
            level = self._get_level(span)
            if level > self._min_level:
                continue

            event = {
                "type": "debug",
                "level": level.name,
                "name": span.name,
                "duration_ms": span_duration_ms(span),
                "module": self._get_module(span),
            }

            attrs = self._get_attrs(span)
            if attrs:
                event["attributes"] = attrs

            self._queue.put(event)

        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True

    @staticmethod
    def _get_level(span: ReadableSpan) -> TraceLevel:
        if span.attributes:
            name = str(span.attributes.get("harle.level", "STEP"))
            try:
                return TraceLevel[name]
            except KeyError:
                pass
        return TraceLevel.STEP

    @staticmethod
    def _get_module(span: ReadableSpan) -> str:
        if span.attributes:
            return str(span.attributes.get("harle.module", ""))
        return ""

    @staticmethod
    def _get_attrs(span: ReadableSpan) -> dict[str, Any]:
        """Extract non-internal attributes (JSON-serializable for SSE)."""
        if not span.attributes:
            return {}
        skip = {"harle.level", "harle.module", "run_id"}
        result = {}
        for k, v in span.attributes.items():
            if k in skip:
                continue
            result[k] = CliSseExporter._json_safe(v)
        return result

    @staticmethod
    def _json_safe(value: Any) -> Any:
        """Coerce to JSON-serializable type for SSE payload."""
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (list, tuple)):
            return [CliSseExporter._json_safe(x) for x in value]
        if isinstance(value, dict):
            return {str(k): CliSseExporter._json_safe(v) for k, v in value.items()}
        try:
            return json.loads(json.dumps(value, default=str, ensure_ascii=False))
        except (TypeError, ValueError):
            return str(value)
