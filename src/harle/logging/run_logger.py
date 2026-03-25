"""Run Logger — stage orchestrator run artifacts for vault logs.

Registers each run's result and optional assembled context in
:class:`~harle.logging.artifacts.RunArtifactStore` for
:class:`~harle.debug.exporters.vault.VaultExporter` to merge with the
execution trace into a single ``logs/YYYY/MM/<run_id>.md`` file.

**Execution trace** (the span tree) is written only by
:class:`~harle.debug.exporters.vault.VaultExporter`. When the orchestrator
has ``vault_tracing_enabled=False``, :func:`flush_registered_run_log_without_trace`
writes Result (+ optional context) only so tests and minimal setups do not
need OpenTelemetry.

Design follows ``docs/trd/architecture/data.md`` (Logs directory)
and ``docs/trd/architecture/orchestrator.md`` (Run Logger).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from harle.dataset.frontmatter import dump_frontmatter_fields
from harle.dataset.writer import log_dir_for, safe_log_filename_stem
from harle.debug import etrace
from harle.logging.artifacts import RunArtifact, register_artifact

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def build_result_body(
    *,
    status: str,
    result_text: str | None = None,
    summary: str | None = None,
    duration_ms: int | None = None,
) -> str:
    """Build consistent result-body content for success and non-success runs."""
    if status == "completed":
        return result_text or summary or ""

    if status == "failed":
        return summary or "Run failed before completion"

    if status == "timeout":
        timeout_summary = summary or "Run timed out before completion"
        if duration_ms is not None:
            return f"{timeout_summary} (elapsed: {duration_ms} ms)"
        return timeout_summary

    if status == "aborted":
        return summary or "Client disconnected before response completed"

    return summary or result_text or ""


def format_run_log_file_content(
    artifact: RunArtifact,
    *,
    total_spans: int | None = None,
    duration_ms: int | None = None,
    execution_trace_md: str | None = None,
) -> str:
    """Render a full run log markdown document (frontmatter + body + optional trace).

    Used by :class:`~harle.debug.exporters.vault.VaultExporter` and by
    finalize fallback when vault tracing is disabled.
    """
    ts = artifact.timestamp
    ts_str = ts.isoformat(timespec="seconds")
    if ts.tzinfo is None:
        ts_str += "Z"
    else:
        ts_str = ts_str.replace("+00:00", "Z")
    data: dict[str, object] = {
        "run_id": artifact.run_id,
        "timestamp": ts_str,
        "agent": artifact.agent,
        "status": artifact.status,
        "context_scope": artifact.context_scope,
    }
    if artifact.conversation_id is not None:
        data["conversation_id"] = artifact.conversation_id
    if total_spans is not None:
        data["total_spans"] = total_spans
    if duration_ms is not None:
        data["duration_ms"] = duration_ms
    fm_yaml = dump_frontmatter_fields(data)
    parts: list[str] = [
        f"---\n{fm_yaml}\n---\n\n# Result\n\n",
        artifact.result_body,
    ]
    if artifact.context_body:
        parts.extend(["\n\n# Assembled context\n\n", artifact.context_body])
    if execution_trace_md:
        parts.extend(["\n\n---\n\n# Execution Trace\n\n", execution_trace_md])
    return "".join(parts)


def flush_registered_run_log_without_trace(
    dataset_path: str | Path,
    run_id: str,
    vault_relative_path: str,
) -> bool:
    """Pop the registered artifact and write Result (+ optional context) only.

    Does **not** add an execution trace. Use when ``vault_tracing_enabled``
    is ``False`` on :class:`~harle.orchestrator.orchestrator_service.OrchestratorService`
    so nothing is waiting on :class:`~harle.debug.exporters.vault.VaultExporter`.

    Returns:
        ``True`` if a file was written.
    """
    from harle.dataset.writer import write_log_file
    from harle.logging.artifacts import pop_artifact

    artifact = pop_artifact(run_id)
    if artifact is None:
        return False
    write_log_file(
        Path(dataset_path),
        vault_relative_path,
        format_run_log_file_content(artifact),
    )
    return True


def _handoffs_markdown(handoffs: list[dict[str, str]]) -> str:
    """Format handoff events as a Markdown section."""
    lines = [
        "| Source | Target | Reason |",
        "|--------|--------|--------|",
    ]
    for h in handoffs:
        src = h.get("source_agent", "")
        tgt = h.get("target_agent", "")
        reason = (h.get("reason") or "").replace("|", "\\|")
        lines.append(f"| {src} | {tgt} | {reason} |")
    return "## Handoffs\n\n" + "\n".join(lines) + "\n"


def log_run_to_vault(
    dataset_path: str | Path,
    run_id: str,
    timestamp: datetime,
    agent: str,
    status: str,
    context_scope: str,
    result_body: str,
    context_body: str | None = None,
    store_context: bool = False,
    handoffs: list[dict[str, str]] | None = None,
    conversation_id: str | None = None,
) -> tuple[str | None, str | None]:
    """Register run result (and optional context) for vault ``logs/YYYY/MM/``.

    Computes ``logs/YYYY/MM/<safe_stem>.md`` where *safe_stem* is derived
    from *run_id*. The file is written by :class:`~harle.debug.exporters.vault.VaultExporter`
    when vault tracing is enabled, or by :func:`finalize_orchestrator_run` when
    it is disabled.

    Args:
        dataset_path: Absolute path to the vault root.
        run_id: Unique run identifier (e.g. run_abc123def456).
        timestamp: When the run occurred (used for YYYY/MM subdirs).
        agent: Agent role (e.g. secretary).
        status: completed, failed, timeout, or aborted.
        context_scope: work or personal.
        result_body: Formatted result text (or summary) for the result section.
        context_body: Assembled prompt/context text when ``store_context``.
        store_context: Whether to include the context section in the artifact.
        handoffs: Optional list of ``{source_agent, target_agent, reason}``.
        conversation_id: Optional conversation id for session correlation.

    Returns:
        ``(result_path, context_path)``. *result_path* is the vault-relative path
        to the merged log file, or ``None`` if the dataset path does not exist.
        *context_path* is always ``None`` (context is embedded in the merged file).
    """
    root = Path(dataset_path)
    if not root.is_absolute():
        root = root.resolve()
    if not root.exists():
        logger.warning("Dataset path does not exist: %s; skipping run log files", root)
        return None, None

    log_dir = log_dir_for(timestamp)
    safe_stem = safe_log_filename_stem(run_id)
    result_rel = f"{log_dir}/{safe_stem}.md"
    body = result_body
    if handoffs:
        extra = _handoffs_markdown(handoffs)
        body = f"{body}\n\n{extra}" if body else extra

    ctx_for_artifact: str | None = None
    if store_context and context_body:
        ctx_for_artifact = context_body

    register_artifact(
        RunArtifact(
            run_id=run_id,
            timestamp=timestamp,
            agent=agent,
            status=status,
            context_scope=context_scope,
            result_body=body,
            context_body=ctx_for_artifact,
            conversation_id=conversation_id,
        )
    )

    etrace.step(
        "Run logged to vault",
        module="run_logger",
        result_path=result_rel,
    )
    etrace.detail(
        "Run artifact registered",
        module="run_logger",
        result_path=result_rel,
    )

    return result_rel, None
