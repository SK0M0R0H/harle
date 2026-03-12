"""CRUD operations for the ``debug_traces`` table.

Provides insert and query helpers for debug trace records.
Each row stores the full span tree as JSONB for one run.
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from harle.db.models import DebugTrace


def create_debug_trace(
    session: Session,
    *,
    run_id: str,
    trace_json: dict[str, Any],
    total_spans: int,
    duration_ms: int | None = None,
) -> DebugTrace:
    """Insert a debug trace record for a single run.

    Args:
        session: Active SQLAlchemy session.
        run_id: The run this trace belongs to.
        trace_json: Serialised span tree (JSONB).
        total_spans: Number of spans in the tree.
        duration_ms: Root span duration in milliseconds.

    Returns:
        The created :class:`DebugTrace` instance.
    """
    row = DebugTrace(
        run_id=run_id,
        trace_json=trace_json,
        total_spans=total_spans,
        duration_ms=duration_ms,
    )
    session.add(row)
    session.flush()
    return row


def get_debug_trace(session: Session, run_id: str) -> DebugTrace | None:
    """Fetch the debug trace for a given run_id.

    Returns:
        The :class:`DebugTrace` if found, otherwise ``None``.
    """
    stmt = select(DebugTrace).where(DebugTrace.run_id == run_id)
    return session.execute(stmt).scalar_one_or_none()
