"""Helpers for tests that need OpenTelemetry + vault trace export.

Call :func:`reset_tracer_provider_and_configure` before code that emits spans,
then :func:`flush_otel` before asserting on vault files or DB trace rows.

Tests that only need Result/context markdown without a trace should set
``vault_tracing_enabled=False`` on :class:`~harle.orchestrator.service.OrchestratorService`
instead of using this module.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    import pytest


def reset_tracer_provider_and_configure(
    monkeypatch: pytest.MonkeyPatch,
    *,
    vault_path: str | None,
    vault_enabled: bool = True,
    db_url: str | None = None,
    db_enabled: bool = False,
    min_storage_level: str = "TRACE",
) -> None:
    """Replace the global TracerProvider and wire Harle exporters (typical: vault only).

    Also rebinds ``harle.debug.trace``'s tracer so :mod:`etrace` uses the new provider.
    """
    from opentelemetry import trace as trace_api
    from opentelemetry.util._once import Once

    from harle.debug.setup import configure_tracing

    monkeypatch.setattr(trace_api, "_TRACER_PROVIDER", None)
    monkeypatch.setattr(trace_api, "_TRACER_PROVIDER_SET_ONCE", Once())
    configure_tracing(
        vault_path=vault_path,
        vault_enabled=vault_enabled,
        db_url=db_url,
        db_enabled=db_enabled,
        min_storage_level=min_storage_level,
    )
    refresh_harle_etrace_tracer()


def refresh_harle_etrace_tracer() -> None:
    """Point ``harle.debug.trace`` at ``get_tracer(\"harle\")`` after provider changes."""
    from opentelemetry import trace as trace_api

    import harle.debug.trace as etrace_impl

    etrace_impl._tracer = trace_api.get_tracer("harle")


def flush_otel(timeout_millis: int = 30_000) -> None:
    """Flush span processors so VaultExporter runs before assertions."""
    from opentelemetry import trace

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(timeout_millis)
