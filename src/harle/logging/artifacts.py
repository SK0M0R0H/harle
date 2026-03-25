"""In-memory store for run log payloads consumed by the vault trace exporter.

Registers artifacts during orchestrator finalization; :class:`VaultExporter`
merges them with span trees after a successful vault write (see
:func:`peek_artifact` / :func:`pop_artifact`). When vault tracing is disabled, :func:`harle.logging.run_logger.flush_registered_run_log_without_trace`
writes the file and pops only after a successful ``write_log_file`` (same as the vault exporter).
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

    def peek(self, run_id: str) -> RunArtifact | None:
        with self._lock:
            return self._data.get(run_id)

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


def peek_artifact(run_id: str) -> RunArtifact | None:
    """Return the artifact for *run_id* without removing it (for pre-write reads)."""
    return _store.peek(run_id)


def pop_artifact(run_id: str) -> RunArtifact | None:
    """Remove and return the artifact for *run_id*, if any."""
    return _store.pop(run_id)


def clear_run_artifact_store() -> None:
    """Clear all registered artifacts (intended for tests)."""
    _store.clear()
