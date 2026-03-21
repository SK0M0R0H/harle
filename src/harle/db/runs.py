"""CRUD operations for the ``runs`` table.

Provides insert, query, and list helpers for orchestrator execution
history (cost tracking, debugging, analytics). Design follows
``docs/trd/architecture/data.md`` (runs table and logs directory).
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from harle.db.models import Run

if TYPE_CHECKING:
    from collections.abc import Sequence


def search_similar_runs(
    session: Session,
    *,
    context_scope: str,
    query_text: str,
    limit: int = 5,
) -> list[Run]:
    """Return completed runs whose request/summary match the query (Phase 2).

    Uses PostgreSQL full-text search on user_request and result_summary.
    Used to surface prior runs for context assembly and prior_run_bonus.

    Args:
        session: Active SQLAlchemy session.
        context_scope: ``work`` or ``personal``.
        query_text: Query string for full-text match.
        limit: Maximum number of runs to return.

    Returns:
        List of :class:`Run` instances, ordered by timestamp DESC.
    """
    if not query_text or not query_text.strip():
        stmt = (
            select(Run)
            .where(
                Run.context_scope == context_scope,
                Run.status == "completed",
            )
            .order_by(Run.timestamp.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    clause = text(
        "to_tsvector('english', user_request || ' ' || COALESCE(result_summary, '')) "
        "@@ plainto_tsquery('english', :q)"
    )
    stmt = (
        select(Run)
        .where(
            Run.context_scope == context_scope,
            Run.status == "completed",
            clause,
        )
        .order_by(Run.timestamp.desc())
        .limit(limit)
    )
    result = session.execute(stmt, {"q": query_text.strip()})
    return list(result.scalars().all())


def create_run(
    session: Session,
    *,
    run_id: str,
    timestamp: datetime,
    user_request: str,
    context_scope: str,
    agent: str,
    status: str,
    routing_method: str | None = None,
    files_used: list[str] | None = None,
    tools_called: list[str] | None = None,
    model_used: str | None = None,
    tokens_input: int | None = None,
    tokens_output: int | None = None,
    estimated_cost: float | None = None,
    duration_ms: int | None = None,
    result_summary: str | None = None,
    result_path: str | None = None,
    context_path: str | None = None,
    conversation_id: str | None = None,
    reflection_triggered: bool | None = None,
    reflection_improved: bool | None = None,
    handoffs: list[dict[str, str]] | None = None,
) -> Run:
    """Insert a single run record.

    Args:
        session: Active SQLAlchemy session.
        run_id: Unique run identifier (e.g. run_abc123def456).
        timestamp: When the run occurred.
        user_request: The user's request text.
        context_scope: ``work`` or ``personal``.
        agent: Agent role that handled the run (e.g. secretary).
        status: ``completed``, ``failed``, ``timeout``, or ``aborted``.
        routing_method: How the agent was chosen (optional).
        files_used: Dataset file paths included in context (optional).
        tools_called: Tools invoked during the run (optional).
        model_used: LLM model name (optional).
        tokens_input: Input token count (optional).
        tokens_output: Output token count (optional).
        estimated_cost: Estimated cost in USD (optional).
        duration_ms: Run duration in milliseconds (optional).
        result_summary: Short summary of the result (optional).
        result_path: Vault-relative path to result log file (optional).
        context_path: Vault-relative path to context log file (optional).
        conversation_id: Conversation ID if part of a chat (optional).
        reflection_triggered: Whether Level 4 reflection ran (optional).
        reflection_improved: Whether an improvement pass replaced the draft (optional).
        handoffs: Optional list of handoff events (source, target, reason).

    Returns:
        The created :class:`Run` instance.
    """
    run = Run(
        run_id=run_id,
        timestamp=timestamp,
        user_request=user_request,
        context_scope=context_scope,
        agent=agent,
        status=status,
        routing_method=routing_method,
        files_used=files_used or None,
        tools_called=tools_called or None,
        model_used=model_used,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        estimated_cost=estimated_cost,
        duration_ms=duration_ms,
        result_summary=result_summary,
        result_path=result_path,
        context_path=context_path,
        conversation_id=conversation_id,
        reflection_triggered=reflection_triggered,
        reflection_improved=reflection_improved,
        handoffs=handoffs,
    )
    session.add(run)
    session.flush()
    return run


def get_run(session: Session, run_id: str) -> Run | None:
    """Fetch a run by its unique run_id.

    Returns:
        The :class:`Run` if found, otherwise ``None``.
    """
    stmt = select(Run).where(Run.run_id == run_id)
    return session.execute(stmt).scalar_one_or_none()


def list_runs(
    session: Session,
    *,
    limit: int = 50,
    offset: int = 0,
    agent: str | None = None,
    status: str | None = None,
    context_scope: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
) -> Sequence[Run]:
    """List runs with optional filters, ordered by timestamp descending.

    Args:
        session: Active SQLAlchemy session.
        limit: Maximum number of runs to return.
        offset: Number of runs to skip.
        agent: Filter by agent role (e.g. secretary).
        status: Filter by status (e.g. completed).
        context_scope: Filter by context (work / personal).
        since: Only runs at or after this time (inclusive).
        until: Only runs before this time (exclusive).

    Returns:
        List of :class:`Run` instances across all statuses unless
        a specific status filter is requested.
    """
    stmt = select(Run).order_by(Run.timestamp.desc())
    if agent is not None:
        stmt = stmt.where(Run.agent == agent)
    if status is not None:
        stmt = stmt.where(Run.status == status)
    if context_scope is not None:
        stmt = stmt.where(Run.context_scope == context_scope)
    if since is not None:
        stmt = stmt.where(Run.timestamp >= since)
    if until is not None:
        stmt = stmt.where(Run.timestamp < until)
    stmt = stmt.limit(limit).offset(offset)
    return session.execute(stmt).scalars().all()
