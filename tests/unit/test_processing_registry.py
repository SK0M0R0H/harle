"""Unit tests for harle.api.processing_registry."""

from __future__ import annotations

import time

import pytest

from harle.api.processing_registry import (
    MAX_REQUEST_ID_BYTES,
    DuplicateActiveProcessingError,
    ProcessingRegistry,
    build_processing_registry,
    _registry_key,
)


def test_registry_key_stable_and_bounded_length() -> None:
    long_id = "x" * 2000
    k = _registry_key(long_id)
    assert len(k) == 64
    assert k == _registry_key(long_id)
    assert k != _registry_key(long_id + "!")


def test_register_rejects_oversized_id() -> None:
    reg = ProcessingRegistry(ttl_seconds=60)
    huge = "a" * (MAX_REQUEST_ID_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds maximum"):
        reg.register(huge)


def test_duplicate_active_raises() -> None:
    reg = ProcessingRegistry(ttl_seconds=600)
    reg.register("req-1")
    with pytest.raises(DuplicateActiveProcessingError):
        reg.register("req-1")
    reg.deregister("req-1")
    reg.register("req-1")


def test_get_status_evicts_expired_entries() -> None:
    reg = ProcessingRegistry(ttl_seconds=1)
    reg.register("stale")
    time.sleep(1.15)
    # Lookup triggers lazy eviction; entry is older than TTL.
    assert reg.get_status("stale") is None


def test_get_status_on_other_id_triggers_eviction_for_stale() -> None:
    reg = ProcessingRegistry(ttl_seconds=1)
    reg.register("a")
    time.sleep(1.15)
    assert reg.get_status("b") is None
    assert reg.get_status("a") is None


def test_build_processing_registry_disabled_timeout_uses_600_ttl() -> None:
    r = build_processing_registry(run_timeout_seconds=None)
    assert r._ttl_seconds == 600


def test_build_processing_registry_positive_timeout_doubles() -> None:
    r = build_processing_registry(run_timeout_seconds=30)
    assert r._ttl_seconds == 60
