"""SQLAlchemy table definitions for the Harle indexer.

Defines all tables described in the TRD data architecture document.
Tables that are not yet actively used (runs, artifacts, memories,
conversations, messages, embeddings) are included so the schema is
complete from day one and future features require no schema redesign.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, JSON, Numeric, Text, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Shared declarative base for all Harle ORM models."""


class FileIndex(Base):
    """Mirrors every Markdown file in the user dataset with queryable metadata.

    This is the primary table used by the search algorithm to pre-filter
    candidates before content-level matching.
    """

    __tablename__ = "file_index"

    id: Mapped[int] = mapped_column(primary_key=True)
    file_path: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    context: Mapped[str | None] = mapped_column(Text)
    content_hash: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int | None] = mapped_column(Integer)
    token_count: Mapped[int | None] = mapped_column(Integer)
    summary: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    last_indexed: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class Run(Base):
    """Execution history — one row per orchestrator run."""

    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    timestamp: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    user_request: Mapped[str] = mapped_column(Text, nullable=False)
    context_scope: Mapped[str] = mapped_column(Text, nullable=False)
    agent: Mapped[str] = mapped_column(Text, nullable=False)
    routing_method: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    files_used: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    tools_called: Mapped[list[str] | None] = mapped_column(ARRAY(Text))
    model_used: Mapped[str | None] = mapped_column(Text)
    tokens_input: Mapped[int | None] = mapped_column(Integer)
    tokens_output: Mapped[int | None] = mapped_column(Integer)
    estimated_cost: Mapped[float | None] = mapped_column(  # type: ignore[assignment]
        Numeric(10, 6)
    )
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    result_summary: Mapped[str | None] = mapped_column(Text)
    result_path: Mapped[str | None] = mapped_column(Text)
    context_path: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    reflection_triggered: Mapped[bool | None] = mapped_column(Boolean)
    reflection_improved: Mapped[bool | None] = mapped_column(Boolean)
    handoffs: Mapped[list[dict[str, str]] | None] = mapped_column(JSON)


class ExecutionTrace(Base):
    """Hierarchical execution trace stored as JSONB for a single run.

    The ``trace_json`` column holds the full span tree serialised by
    :class:`~harle.debug.exporters.db.PostgresExporter`.  Using JSONB
    keeps writes simple (one row per run) and allows PostgreSQL jsonpath
    queries across traces (e.g. find runs where a tool was slow).
    """

    __tablename__ = "execution_traces"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False, index=True)
    trace_json: Mapped[dict] = mapped_column(JSON, nullable=False)
    total_spans: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class Artifact(Base):
    """Large agent outputs stored separately from run metadata."""

    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    artifact_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str | None] = mapped_column(Text)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    file_path: Mapped[str | None] = mapped_column(Text)
    context_scope: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class Memory(Base):
    """Learned preferences, decisions, and corrections."""

    __tablename__ = "memories"

    id: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    context_scope: Mapped[str] = mapped_column(Text, nullable=False)
    source_run_id: Mapped[str | None] = mapped_column(Text)
    confidence: Mapped[float | None] = mapped_column(  # type: ignore[assignment]
        Numeric(3, 2)
    )
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    """Multi-turn conversation state."""

    __tablename__ = "conversations"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(
        Text, unique=True, nullable=False
    )
    context_scope: Mapped[str] = mapped_column(Text, nullable=False)
    agent_role: Mapped[str] = mapped_column(Text, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    """Individual messages within a conversation."""

    __tablename__ = "messages"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[str] = mapped_column(Text, nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    run_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class Embedding(Base):
    """Vector representations for semantic search (future).

    The ``embedding`` column is stored as Text for now. When pgvector
    is enabled, this column will be migrated to ``vector(1536)``.
    """

    __tablename__ = "embeddings"

    id: Mapped[int] = mapped_column(primary_key=True)
    source_type: Mapped[str] = mapped_column(Text, nullable=False)
    source_id: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    chunk_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[str | None] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )


class CaptureRunRow(Base):
    """One row per vault capture run (quick profile, interview, or refresh).

    Stores run identity (run_id), mode, current state (created/active/
    paused/completed/cancelled), scope (all/work/personal/goals), target tiers,
    and optional conversation_id. Enables pause/resume across days and supplies
    run history for the Health Checker's coverage and staleness analysis.
    """

    __tablename__ = "capture_runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    mode: Mapped[str] = mapped_column(Text, nullable=False)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    scope: Mapped[str] = mapped_column(Text, nullable=False)
    target_tiers: Mapped[list[int] | None] = mapped_column(ARRAY(Integer))
    conversation_id: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=func.now(), onupdate=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)


class CaptureRunTopicProgressRow(Base):
    """One row per topic in a capture run: status, answers, and write result.

    Links a run_id to a topic_id (unique per run). Tracks status
    (pending/in_progress/completed/skipped), raw answers (JSON), generated
    Markdown, the vault path written, and completed_at. Used to resume
    runs and to compute per-topic staleness for refresh.
    """

    __tablename__ = "capture_run_topic_progress"

    id: Mapped[int] = mapped_column(primary_key=True)
    run_id: Mapped[str] = mapped_column(Text, nullable=False)
    topic_id: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    answers: Mapped[dict] = mapped_column(JSON, nullable=False)
    generated_content: Mapped[str | None] = mapped_column(Text)
    vault_path: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)

    __table_args__ = (UniqueConstraint("run_id", "topic_id", name="uq_capture_run_topic"),)
