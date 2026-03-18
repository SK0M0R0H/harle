"""Run Logger — write agent run artifacts to the vault logs/ directory.

Records each run's result (and optionally the assembled context) as
Markdown files with YAML frontmatter under ``logs/YYYY/MM/``.
Design follows ``docs/trd/architecture/data.md`` (Logs directory)
and ``docs/trd/architecture/orchestrator.md`` (Run Logger).
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

import yaml

from harle.dataset.writer import log_dir_for, write_log_file
from harle.debug import etrace

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


def _frontmatter_yaml(
    run_id: str,
    timestamp: datetime,
    agent: str,
    status: str,
    context_scope: str,
) -> str:
    """Build YAML frontmatter block for log files."""
    ts_str = timestamp.isoformat(timespec="seconds")
    if timestamp.tzinfo is None:
        ts_str += "Z"
    else:
        ts_str = ts_str.replace("+00:00", "Z")
    data = {
        "run_id": run_id,
        "timestamp": ts_str,
        "agent": agent,
        "status": status,
        "context_scope": context_scope,
    }
    return yaml.dump(
        data,
        default_flow_style=False,
        allow_unicode=True,
        sort_keys=False,
    ).strip()


def _result_content(
    run_id: str,
    timestamp: datetime,
    agent: str,
    status: str,
    context_scope: str,
    result_body: str,
) -> str:
    """Build full content for a result log file (frontmatter + body)."""
    fm = _frontmatter_yaml(run_id, timestamp, agent, status, context_scope)
    return f"---\n{fm}\n---\n\n# Result\n\n{result_body}"


def _context_content(
    run_id: str,
    timestamp: datetime,
    agent: str,
    status: str,
    context_scope: str,
    context_body: str,
) -> str:
    """Build full content for a context log file (frontmatter + body)."""
    fm = _frontmatter_yaml(run_id, timestamp, agent, status, context_scope)
    return f"---\n{fm}\n---\n\n# Assembled context\n\n{context_body}"


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
) -> tuple[str | None, str | None]:
    """Write run result (and optionally context) to the vault logs/ directory.

    Creates ``logs/YYYY/MM/<run_id>_result.md`` and, when
    ``store_context`` is True and ``context_body`` is provided,
    ``logs/YYYY/MM/<run_id>_context.md``. Files use YAML frontmatter
    and Markdown body as specified in the TRD.

    Args:
        dataset_path: Absolute path to the vault root.
        run_id: Unique run identifier (e.g. run_abc123def456).
        timestamp: When the run occurred (used for YYYY/MM subdirs).
        agent: Agent role (e.g. secretary).
        status: completed, failed, timeout, or aborted.
        context_scope: work or personal.
        result_body: Formatted result text (or summary) for the result file.
        context_body: Assembled prompt/context text for the context file.
        store_context: Whether to write the context file (config-driven).

    Returns:
        A pair (result_path, context_path). result_path is the
        vault-relative path to the result file (e.g.
        logs/2026/02/run_abc123_result.md), or None if the dataset path
        does not exist. context_path is the vault-relative path to the
        context file, or None if not written. Non-success runs still
        write the optional context file when ``store_context`` is True
        and ``context_body`` is available.
    """
    root = Path(dataset_path)
    if not root.is_absolute():
        root = root.resolve()
    if not root.exists():
        logger.warning("Dataset path does not exist: %s; skipping run log files", root)
        return None, None

    log_dir = log_dir_for(timestamp)
    result_rel = f"{log_dir}/{run_id}_result.md"
    result_content = _result_content(
        run_id, timestamp, agent, status, context_scope, result_body
    )
    write_log_file(root, result_rel, result_content)

    etrace.step(
        "Run logged to vault",
        module="run_logger",
        result_path=result_rel,
    )
    etrace.detail(
        "File paths written",
        module="run_logger",
        result_path=result_rel,
    )

    context_path: str | None = None
    if store_context and context_body:
        context_rel = f"{log_dir}/{run_id}_context.md"
        context_content = _context_content(
            run_id, timestamp, agent, status, context_scope, context_body
        )
        write_log_file(root, context_rel, context_content)
        context_path = context_rel
        etrace.detail(
            "Context file written",
            module="run_logger",
            context_path=context_rel,
        )

    return result_rel, context_path
