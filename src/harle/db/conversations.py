"""CRUD operations for ``conversations`` and ``messages`` tables.

Manages multi-turn chat state — creating conversations, appending
messages, loading recent history for context assembly, and
deactivating inactive sessions.

Design follows ``docs/trd/architecture/orchestrator.md`` (Conversation
Mode) and ``docs/trd/architecture/data.md`` (Table 5).
"""

from __future__ import annotations

import logging

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from harle.db.models import Conversation, Message

logger = logging.getLogger(__name__)

DEFAULT_RECENT_MESSAGE_LIMIT: int = 20


def create_conversation(
    session: Session,
    *,
    conversation_id: str,
    context_scope: str,
    agent_role: str,
) -> Conversation:
    """Create a new conversation record.

    Args:
        session: Active SQLAlchemy session.
        conversation_id: Unique identifier for the conversation.
        context_scope: Scope of the conversation (``"work"`` or
            ``"personal"``).
        agent_role: Initial agent role handling the conversation
            (e.g. ``"secretary"``).

    Returns:
        The newly created :class:`Conversation` row.

    Raises:
        sqlalchemy.exc.IntegrityError: If *conversation_id* already
            exists.
    """
    conv = Conversation(
        conversation_id=conversation_id,
        context_scope=context_scope,
        agent_role=agent_role,
    )
    session.add(conv)
    session.flush()
    logger.debug(
        "Created conversation %s (scope=%s, role=%s)",
        conversation_id,
        context_scope,
        agent_role,
    )
    return conv


def get_conversation(
    session: Session,
    conversation_id: str,
) -> Conversation | None:
    """Look up a conversation by its unique identifier.

    Args:
        session: Active SQLAlchemy session.
        conversation_id: The conversation ID to look up.

    Returns:
        The matching :class:`Conversation` row, or ``None``.
    """
    stmt = select(Conversation).where(
        Conversation.conversation_id == conversation_id,
    )
    return session.scalars(stmt).first()


def list_active_conversations(
    session: Session,
    *,
    context_scope: str | None = None,
) -> list[Conversation]:
    """Return all active conversations, optionally filtered by scope.

    Args:
        session: Active SQLAlchemy session.
        context_scope: If provided, only return conversations matching
            this scope (e.g. ``"work"`` or ``"personal"``).

    Returns:
        List of active :class:`Conversation` rows ordered by most
        recently updated first.
    """
    stmt = (
        select(Conversation)
        .where(Conversation.active.is_(True))
        .order_by(Conversation.updated_at.desc())
    )
    if context_scope:
        stmt = stmt.where(Conversation.context_scope == context_scope)
    return list(session.scalars(stmt).all())


def update_conversation_summary(
    session: Session,
    conversation_id: str,
    summary: str,
) -> None:
    """Set the running summary of older messages.

    Used by the context assembler when older messages are summarised
    to save context-window tokens.

    Args:
        session: Active SQLAlchemy session.
        conversation_id: Target conversation.
        summary: New summary text.
    """
    stmt = (
        update(Conversation)
        .where(Conversation.conversation_id == conversation_id)
        .values(summary=summary, updated_at=func.now())
    )
    session.execute(stmt)


def deactivate_conversation(
    session: Session,
    conversation_id: str,
) -> None:
    """Mark a conversation as inactive.

    Inactive conversations are excluded from
    :func:`list_active_conversations` but remain in the database
    for audit and history.

    Args:
        session: Active SQLAlchemy session.
        conversation_id: The conversation to deactivate.
    """
    stmt = (
        update(Conversation)
        .where(Conversation.conversation_id == conversation_id)
        .values(active=False, updated_at=func.now())
    )
    session.execute(stmt)
    logger.debug("Deactivated conversation %s", conversation_id)


def touch_conversation(
    session: Session,
    conversation_id: str,
) -> None:
    """Bump the conversation's ``updated_at`` timestamp.

    Called after appending messages so the conversation surfaces
    correctly in recency-based queries.

    Args:
        session: Active SQLAlchemy session.
        conversation_id: The conversation to touch.
    """
    stmt = (
        update(Conversation)
        .where(Conversation.conversation_id == conversation_id)
        .values(updated_at=func.now())
    )
    session.execute(stmt)


# ── Message operations ────────────────────────────────────────────────


def add_message(
    session: Session,
    *,
    conversation_id: str,
    role: str,
    content: str,
    run_id: str | None = None,
) -> Message:
    """Append a message to a conversation.

    Args:
        session: Active SQLAlchemy session.
        conversation_id: Target conversation.
        role: Message role (``"user"`` or ``"assistant"``).
        content: Message text.
        run_id: Optional link to the orchestrator run that produced
            this message.

    Returns:
        The newly created :class:`Message` row.
    """
    msg = Message(
        conversation_id=conversation_id,
        role=role,
        content=content,
        run_id=run_id,
    )
    session.add(msg)
    session.flush()
    return msg


def get_messages(
    session: Session,
    conversation_id: str,
) -> list[Message]:
    """Return all messages for a conversation in chronological order.

    Args:
        session: Active SQLAlchemy session.
        conversation_id: Target conversation.

    Returns:
        List of :class:`Message` rows ordered by creation time.
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.asc())
    )
    return list(session.scalars(stmt).all())


def get_recent_messages(
    session: Session,
    conversation_id: str,
    *,
    limit: int = DEFAULT_RECENT_MESSAGE_LIMIT,
) -> list[Message]:
    """Return the most recent messages for context assembly.

    Retrieves the *limit* most recent messages and returns them in
    chronological order (oldest first).  The default limit of 20
    covers roughly 10 user–assistant turns.

    Args:
        session: Active SQLAlchemy session.
        conversation_id: Target conversation.
        limit: Maximum number of messages to return.

    Returns:
        Messages ordered oldest-first (chronological).
    """
    stmt = (
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.created_at.desc())
        .limit(limit)
    )
    messages = list(session.scalars(stmt).all())
    messages.reverse()
    return messages
