"""TracerProvider configuration — wired once at application startup.

Registers custom span exporters with the OTel SDK.  Phase 1 includes
only the vault exporter; DB and CLI exporters are added in Phase 2.
"""

from __future__ import annotations

import logging

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from harle.debug.levels import TraceLevel

logger = logging.getLogger(__name__)


def configure_tracing(
    *,
    vault_path: str | None = None,
    vault_enabled: bool = True,
    min_storage_level: str = "TRACE",
) -> None:
    """Set up the global ``TracerProvider`` with Harle exporters.

    Called once during ``create_app()`` in :mod:`harle.main`.  The
    provider is set globally via ``trace.set_tracer_provider`` so
    every ``dtrace`` call automatically inherits it.

    Args:
        vault_path: Absolute path to the vault root.  When ``None``
            the vault exporter is skipped.
        vault_enabled: Master switch for the vault exporter.
        min_storage_level: Minimum trace level written to vault/DB.
    """
    provider = TracerProvider()
    storage_level = TraceLevel.from_name(min_storage_level)

    if vault_enabled and vault_path:
        from harle.debug.exporters.vault import VaultExporter

        exporter = VaultExporter(
            vault_path=vault_path,
            min_level=storage_level,
        )
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("Debug tracing: vault exporter enabled (path=%s, min_level=%s)", vault_path, min_storage_level)

    trace.set_tracer_provider(provider)
    logger.info("Debug tracing configured.")
