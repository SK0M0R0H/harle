"""In-memory registry of in-flight /chat requests for CLI processing pings."""

from __future__ import annotations

import hashlib
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

# Reject absurd header/path sizes before hashing (hashing bounds CPU for huge strings).
MAX_REQUEST_ID_BYTES = 4096


class DuplicateActiveProcessingError(Exception):
    """Another in-flight /chat already holds this request id (same SHA-256 key)."""


def _registry_key(raw_request_id: str) -> str:
    """Stable internal key: SHA-256 hex of UTF-8 bytes (bounded lookup size, no huge dict keys)."""
    return hashlib.sha256(raw_request_id.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class ProcessingEntry:
    """A single active processing slot."""

    status: str  # "processing"
    started_at: datetime


class ProcessingRegistry:
    """Thread-safe map (hashed request id) -> processing entry with lazy TTL eviction."""

    def __init__(self, ttl_seconds: int) -> None:
        self._entries: dict[str, ProcessingEntry] = {}
        self._lock = threading.Lock()
        self._ttl_seconds = max(1, ttl_seconds)

    def _evict_expired(self, now: datetime) -> None:
        cutoff = now - timedelta(seconds=self._ttl_seconds)
        stale = [rid for rid, e in self._entries.items() if e.started_at < cutoff]
        for rid in stale:
            del self._entries[rid]

    @staticmethod
    def _validate_size(raw_request_id: str) -> None:
        if len(raw_request_id.encode("utf-8")) > MAX_REQUEST_ID_BYTES:
            msg = f"X-Request-ID exceeds maximum length ({MAX_REQUEST_ID_BYTES} bytes)."
            raise ValueError(msg)

    def register(self, raw_request_id: str) -> None:
        """Record that *raw_request_id* is being processed (lazy TTL cleanup).

        Raises:
            ValueError: if the id is too large.
            DuplicateActiveProcessingError: if the same id (hash) is already active.
        """
        self._validate_size(raw_request_id)
        k = _registry_key(raw_request_id)
        now = datetime.now(timezone.utc)
        with self._lock:
            self._evict_expired(now)
            if k in self._entries:
                raise DuplicateActiveProcessingError
            self._entries[k] = ProcessingEntry(
                status="processing",
                started_at=now,
            )

    def deregister(self, raw_request_id: str) -> None:
        """Remove *raw_request_id* when the chat handler finishes."""
        try:
            self._validate_size(raw_request_id)
        except ValueError:
            return
        k = _registry_key(raw_request_id)
        with self._lock:
            self._entries.pop(k, None)

    def get_status(self, raw_request_id: str) -> ProcessingEntry | None:
        """Return the entry for *raw_request_id*, or None if absent (evicts TTL lazily)."""
        try:
            self._validate_size(raw_request_id)
        except ValueError:
            return None
        k = _registry_key(raw_request_id)
        now = datetime.now(timezone.utc)
        with self._lock:
            self._evict_expired(now)
            return self._entries.get(k)


def build_processing_registry(*, run_timeout_seconds: int | None) -> ProcessingRegistry:
    """Create a registry whose entry TTL matches ``2 * run_timeout_seconds`` (or 600s if disabled)."""
    if run_timeout_seconds is None or run_timeout_seconds <= 0:
        ttl_seconds = 600
    else:
        ttl_seconds = 2 * int(run_timeout_seconds)
    return ProcessingRegistry(ttl_seconds=ttl_seconds)
