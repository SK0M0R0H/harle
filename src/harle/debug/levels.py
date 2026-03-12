"""Trace-level enum for Harle debug logging.

Maps importance levels to span attributes. OpenTelemetry spans have no
built-in "level" concept — Harle adds ``harle.level`` as a custom
attribute and filters at export time, not at collection time.
"""

from __future__ import annotations

from enum import IntEnum


class TraceLevel(IntEnum):
    """Importance tiers for debug trace entries.

    Lower numeric value = higher importance.  Exporters filter spans
    whose level exceeds the configured threshold.
    """

    STEP = 1      # Major stages (e.g. "Context assembly", "Agent execution") — chapter headings of a run
    DETAIL = 2     # Decisions, parameters, intermediate results (e.g. token budget, rule matched)
    TRACE = 3      # Fine-grained internals for deep debugging (e.g. HTTP calls, query parsing)
    INTERNAL = 4   # Very low-level, rarely needed outside development (e.g. cache hits, validation)

    @classmethod
    def from_name(cls, name: str) -> TraceLevel:
        """Resolve a level by case-insensitive name.

        Raises ``KeyError`` when *name* is not a valid level.
        """
        return cls[name.upper()]
