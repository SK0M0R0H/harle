"""In-memory store for run log payloads consumed by the vault trace exporter.

Registers artifacts during orchestrator finalization; :class:`VaultExporter`
pops and merges them with span trees. When vault tracing is disabled, the
orchestrator writes the file directly and clears the store via pop.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass
from datetime import datetime


@dataclass
class RunArtifact:
    """Structured fields persisted into a single run log markdown file."""

    run_id: str
    timestamp: datetime
    agent: str
    status: str
    context_scope: str
    result_body: str
    context_body: str | None = None
    conversation_id: str | None = None


class RunArtifactStore:
    """Thread-safe map ``run_id`` → :class:`RunArtifact`."""

    def __init__(self) -> None:
        self._data: dict[str, RunArtifact] = {}
        self._lock = threading.Lock()

    def register(self, artifact: RunArtifact) -> None:
        with self._lock:
            self._data[artifact.run_id] = artifact

    def pop(self, run_id: str) -> RunArtifact | None:
        with self._lock:
            return self._data.pop(run_id, None)

    def clear(self) -> None:
        with self._lock:
            self._data.clear()


_store = RunArtifactStore()


def register_artifact(artifact: RunArtifact) -> None:
    """Store *artifact* for the vault exporter or finalize fallback."""
    _store.register(artifact)


def pop_artifact(run_id: str) -> RunArtifact | None:
    """Remove and return the artifact for *run_id*, if any."""
    return _store.pop(run_id)


def clear_run_artifact_store() -> None:
    """Clear all registered artifacts (intended for tests)."""
    _store.clear()
