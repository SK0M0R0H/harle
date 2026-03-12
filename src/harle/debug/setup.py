"""TracerProvider configuration — wired once at application startup.

Registers custom span exporters with the OTel SDK.

- **Vault exporter** (Phase 1): span tree → Markdown → vault logs/.
- **DB exporter** (Phase 2): span tree → JSONB → ``execution_traces`` table.
- **CLI SSE exporter** (Phase 2): span → SSE queue for real-time debug output.
"""

from __future__ import annotations

import logging
from queue import Queue
from typing import Any

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, SimpleSpanProcessor

from harle.debug.levels import TraceLevel

logger = logging.getLogger(__name__)


def configure_tracing(
    *,
    vault_path: str | None = None,
    vault_enabled: bool = True,
    db_url: str | None = None,
    db_enabled: bool = True,
    debug_mode: bool = False,
    sse_queue: Queue[dict[str, Any]] | None = None,
    debug_level: TraceLevel = TraceLevel.STEP,
    min_storage_level: str = "TRACE",
) -> None:
    """Set up the global ``TracerProvider`` with Harle exporters.

    Called once during ``create_app()`` in :mod:`harle.main`.  The
    provider is set globally via ``trace.set_tracer_provider`` so
    every ``etrace`` call automatically inherits it.

    Args:
        vault_path: Absolute path to the vault root.  When ``None``
            the vault exporter is skipped.
        vault_enabled: Master switch for the vault exporter.
        db_url: PostgreSQL connection string.  When ``None`` the DB
            exporter is skipped.
        db_enabled: Master switch for the DB exporter.
        debug_mode: When ``True`` and *sse_queue* is provided, the
            CLI SSE exporter is enabled for real-time streaming.
        sse_queue: Shared queue for SSE debug events.  Only used when
            *debug_mode* is ``True``.
        debug_level: Minimum trace level emitted to the SSE queue
            (controls CLI verbosity).
        min_storage_level: Minimum trace level written to vault/DB.
    """
    provider = TracerProvider()
    storage_level = TraceLevel.from_name(min_storage_level)

    if vault_enabled and vault_path:
        from harle.debug.exporters.vault import VaultExporter

        exporter = VaultExporter(vault_path=vault_path, min_level=storage_level)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info(
            "Debug tracing: vault exporter enabled (path=%s, min_level=%s)",
            vault_path,
            min_storage_level,
        )

    if db_enabled and db_url:
        from harle.debug.exporters.db import PostgresExporter

        exporter = PostgresExporter(database_url=db_url, min_level=storage_level)
        provider.add_span_processor(BatchSpanProcessor(exporter))
        logger.info("Debug tracing: DB exporter enabled (min_level=%s)", min_storage_level)

    if debug_mode and sse_queue is not None:
        from harle.debug.exporters.cli import CliSseExporter

        exporter = CliSseExporter(sse_queue, min_level=debug_level)
        provider.add_span_processor(SimpleSpanProcessor(exporter))
        logger.info("Debug tracing: CLI SSE exporter enabled (min_level=%s)", debug_level.name)

    trace.set_tracer_provider(provider)
    logger.info("Debug tracing configured.")
