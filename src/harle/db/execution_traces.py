"""CRUD operations for the ``execution_traces`` table.

Provides insert and query helpers for execution trace records.
Each row stores the full span tree as JSONB for one run.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from harle.db.models import ExecutionTrace


def create_execution_trace(
    session: Session,
    *,
    run_id: str,
    trace_json: dict[str, Any],
    total_spans: int,
    duration_ms: int | None = None,
) -> ExecutionTrace:
    """Insert an execution trace record for a single run.

    Args:
        session: Active SQLAlchemy session.
        run_id: The run this trace belongs to.
        trace_json: Serialised span tree (JSONB).
        total_spans: Number of spans in the tree.
        duration_ms: Root span duration in milliseconds.

    Returns:
        The created :class:`ExecutionTrace` instance.
    """
    row = ExecutionTrace(
        run_id=run_id,
        trace_json=trace_json,
        total_spans=total_spans,
        duration_ms=duration_ms,
    )
    session.add(row)
    session.flush()
    return row


def get_execution_trace(session: Session, run_id: str) -> ExecutionTrace | None:
    """Fetch the execution trace for a given run_id.

    Returns:
        The :class:`ExecutionTrace` if found, otherwise ``None``.
    """
    stmt = select(ExecutionTrace).where(ExecutionTrace.run_id == run_id)
    return session.execute(stmt).scalar_one_or_none()
