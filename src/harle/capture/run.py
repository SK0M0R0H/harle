"""Capture run lifecycle — create, pause, resume, complete.

CaptureRunManager persists capture runs and topic progress to the database
so a run can be resumed across days. "Run" avoids confusion with chat
sessions between the user and Harle.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from sqlalchemy import select
from sqlalchemy.orm import Session

from harle.capture.registry import TopicRegistry
from harle.capture.topics import Tier
from harle.db.models import CaptureRunRow, CaptureRunTopicProgressRow


class CaptureMode(Enum):
    """How the capture run operates."""

    QUICK_PROFILE = "quick_profile"
    INTERVIEW = "interview"
    REFRESH = "refresh"
    PROGRESSIVE = "progressive"


class CaptureRunState(Enum):
    """Lifecycle state of a capture run."""

    CREATED = "created"
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass
class TopicProgress:
    """Tracks capture progress for a single topic within a run."""

    topic_id: str
    status: str  # "pending", "in_progress", "completed", "skipped"
    answers: dict = field(default_factory=dict)
    generated_content: str = ""
    vault_path: str = ""
    completed_at: datetime | None = None


@dataclass
class CaptureRun:
    """A single capture run spanning one or more topics (pause/resume across days)."""

    run_id: str
    mode: CaptureMode
    state: CaptureRunState
    scope: str
    target_tiers: list[int]
    topic_progress: dict[str, TopicProgress]
    conversation_id: str | None = None
    created_at: datetime = field(default_factory=datetime.utcnow)
    updated_at: datetime = field(default_factory=datetime.utcnow)
    completed_at: datetime | None = None


def _new_run_id() -> str:
    return f"cap_{uuid.uuid4().hex[:16]}"


def _row_to_run(row: CaptureRunRow, progress_rows: list[CaptureRunTopicProgressRow]) -> CaptureRun:
    """Build a CaptureRun from DB rows."""
    topic_progress = {}
    for p in progress_rows:
        topic_progress[p.topic_id] = TopicProgress(
            topic_id=p.topic_id,
            status=p.status,
            answers=p.answers if isinstance(p.answers, dict) else {},
            generated_content=p.generated_content or "",
            vault_path=p.vault_path or "",
            completed_at=p.completed_at,
        )
    return CaptureRun(
        run_id=row.run_id,
        mode=CaptureMode(row.mode),
        state=CaptureRunState(row.state),
        scope=row.scope,
        target_tiers=list(row.target_tiers or []),
        topic_progress=topic_progress,
        conversation_id=row.conversation_id,
        created_at=row.created_at,
        updated_at=row.updated_at,
        completed_at=row.completed_at,
    )


class CaptureRunManager:
    """Creates and persists capture runs using the Topic Registry and DB."""

    def __init__(self, registry: TopicRegistry) -> None:
        self._registry = registry

    def create_run(
        self,
        db_session: Session,
        *,
        mode: CaptureMode,
        scope: str = "all",
        target_tiers: list[int] | None = None,
        conversation_id: str | None = None,
    ) -> CaptureRun:
        """Create a new capture run and persist it.

        Topics are selected from the registry by scope and target_tiers.
        Default target_tiers is [1] (essential only).
        """
        tiers = target_tiers if target_tiers is not None else [Tier.ESSENTIAL.value]
        topics = [
            t
            for t in self._registry.get_by_scope(scope)
            if t.tier.value in tiers
        ]
        run_id = _new_run_id()
        row = CaptureRunRow(
            run_id=run_id,
            mode=mode.value,
            state=CaptureRunState.CREATED.value,
            scope=scope,
            target_tiers=tiers,
            conversation_id=conversation_id,
        )
        db_session.add(row)
        db_session.flush()
        for t in topics:
            prog = CaptureRunTopicProgressRow(
                run_id=run_id,
                topic_id=t.id,
                status="pending",
                answers={},
            )
            db_session.add(prog)
        db_session.flush()
        progress_rows = db_session.execute(
            select(CaptureRunTopicProgressRow).where(
                CaptureRunTopicProgressRow.run_id == run_id,
            ),
        ).scalars().all()
        return _row_to_run(row, progress_rows)

    def get_run(
        self,
        db_session: Session,
        run_id: str,
    ) -> CaptureRun | None:
        """Load a capture run by id."""
        row = db_session.execute(
            select(CaptureRunRow).where(CaptureRunRow.run_id == run_id),
        ).scalars().first()
        if row is None:
            return None
        progress_rows = db_session.execute(
            select(CaptureRunTopicProgressRow).where(
                CaptureRunTopicProgressRow.run_id == run_id,
            ),
        ).scalars().all()
        return _row_to_run(row, progress_rows)

    def start_run(self, db_session: Session, run_id: str) -> CaptureRun | None:
        """Set run state to ACTIVE. Returns updated run or None."""
        run = self.get_run(db_session, run_id)
        if run is None:
            return None
        run_row = db_session.execute(
            select(CaptureRunRow).where(CaptureRunRow.run_id == run_id),
        ).scalars().one()
        run_row.state = CaptureRunState.ACTIVE.value
        run_row.updated_at = datetime.utcnow()
        db_session.flush()
        return self.get_run(db_session, run_id)

    def pause_run(self, db_session: Session, run_id: str) -> CaptureRun | None:
        """Set run state to PAUSED."""
        run = self.get_run(db_session, run_id)
        if run is None:
            return None
        run_row = db_session.execute(
            select(CaptureRunRow).where(CaptureRunRow.run_id == run_id),
        ).scalars().one()
        run_row.state = CaptureRunState.PAUSED.value
        run_row.updated_at = datetime.utcnow()
        db_session.flush()
        return self.get_run(db_session, run_id)

    def resume_run(self, db_session: Session, run_id: str) -> CaptureRun | None:
        """Set run state to ACTIVE."""
        return self.start_run(db_session, run_id)

    def complete_run(self, db_session: Session, run_id: str) -> CaptureRun | None:
        """Set run state to COMPLETED and set completed_at."""
        run = self.get_run(db_session, run_id)
        if run is None:
            return None
        run_row = db_session.execute(
            select(CaptureRunRow).where(CaptureRunRow.run_id == run_id),
        ).scalars().one()
        run_row.state = CaptureRunState.COMPLETED.value
        run_row.completed_at = datetime.utcnow()
        run_row.updated_at = run_row.completed_at
        db_session.flush()
        return self.get_run(db_session, run_id)

    def cancel_run(self, db_session: Session, run_id: str) -> CaptureRun | None:
        """Set run state to CANCELLED."""
        run = self.get_run(db_session, run_id)
        if run is None:
            return None
        run_row = db_session.execute(
            select(CaptureRunRow).where(CaptureRunRow.run_id == run_id),
        ).scalars().one()
        run_row.state = CaptureRunState.CANCELLED.value
        run_row.updated_at = datetime.utcnow()
        db_session.flush()
        return self.get_run(db_session, run_id)

    def update_topic_progress(
        self,
        db_session: Session,
        run_id: str,
        topic_id: str,
        *,
        status: str,
        answers: dict | None = None,
        generated_content: str | None = None,
        vault_path: str | None = None,
        completed_at: datetime | None = None,
    ) -> CaptureRun | None:
        """Update progress for one topic in a run."""
        run = self.get_run(db_session, run_id)
        if run is None:
            return None
        prog_row = db_session.execute(
            select(CaptureRunTopicProgressRow).where(
                CaptureRunTopicProgressRow.run_id == run_id,
                CaptureRunTopicProgressRow.topic_id == topic_id,
            ),
        ).scalars().first()
        if prog_row is None:
            return run
        prog_row.status = status
        if answers is not None:
            prog_row.answers = answers
        if generated_content is not None:
            prog_row.generated_content = generated_content
        if vault_path is not None:
            prog_row.vault_path = vault_path
        if completed_at is not None:
            prog_row.completed_at = completed_at
        db_session.flush()
        return self.get_run(db_session, run_id)
