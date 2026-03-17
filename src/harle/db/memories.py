"""CRUD operations for the ``memories`` table.

Provides search and persistence for learned preferences, past decisions,
and explicit corrections — the episodic memory tier described in the TRD.
"""

from __future__ import annotations

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from harle.db.models import Memory


def search_memories(
    session: Session,
    *,
    context_scope: str,
    query_text: str,
    min_confidence: float = 0.0,
    limit: int = 10,
) -> list[Memory]:
    """Return memories relevant to the query (Phase 2 search).

    Uses PostgreSQL full-text search on content, scoped by context and
    confidence. Memories with context_scope ``global`` are included
    for any requested scope.

    Args:
        session: Active SQLAlchemy session.
        context_scope: ``work`` or ``personal``.
        query_text: Query string for full-text match on content.
        min_confidence: Minimum confidence (0–1) to include.
        limit: Maximum number of memories to return.

    Returns:
        List of :class:`Memory` instances, ordered by confidence DESC.
    """
    if not query_text or not query_text.strip():
        stmt = (
            select(Memory)
            .where(
                Memory.context_scope.in_([context_scope, "global"]),
                Memory.active.is_(True),
                Memory.confidence >= min_confidence,
            )
            .order_by(Memory.confidence.desc())
            .limit(limit)
        )
        return list(session.scalars(stmt).all())

    clause = text(
        "to_tsvector('english', content) @@ plainto_tsquery('english', :q)"
    )
    stmt = (
        select(Memory)
        .where(
            Memory.context_scope.in_([context_scope, "global"]),
            Memory.active.is_(True),
            Memory.confidence >= min_confidence,
            clause,
        )
        .order_by(Memory.confidence.desc())
        .limit(limit)
    )
    result = session.execute(stmt, {"q": query_text.strip()})
    return list(result.scalars().all())
