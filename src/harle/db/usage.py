"""Usage aggregation queries over the ``runs`` table.

Provides helpers for summarising LLM token consumption, estimated cost,
and run counts over configurable time windows.  The underlying columns
(``tokens_input``, ``tokens_output``, ``estimated_cost``) are nullable;
these helpers coalesce NULLs to zero so callers always get numeric results
even before token tracking is wired into the orchestrator pipeline.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, TypedDict

from sqlalchemy import Date, cast, func, select

from harle.db.models import Run

if TYPE_CHECKING:
    from sqlalchemy.orm import Session


class ModelUsage(TypedDict):
    """Per-model usage bucket."""

    model: str
    tokens_input: int
    tokens_output: int
    estimated_cost: float
    run_count: int


class DailyUsage(TypedDict):
    """Per-day usage bucket."""

    date: str  # ISO date YYYY-MM-DD
    tokens_input: int
    tokens_output: int
    estimated_cost: float
    run_count: int


class UsageSummary(TypedDict):
    """Aggregate usage over a time window."""

    tokens_input: int
    tokens_output: int
    estimated_cost: float
    run_count: int
    by_model: list[ModelUsage]


def get_usage_summary(
    session: Session,
    *,
    since: datetime,
    until: datetime,
) -> UsageSummary:
    """Aggregate token usage and cost over a time window, grouped by model.

    Args:
        session: Active SQLAlchemy session.
        since: Start of the window (inclusive).
        until: End of the window (exclusive).

    Returns:
        :class:`UsageSummary` with totals and per-model breakdown.
    """
    _coalesce_in = func.coalesce(Run.tokens_input, 0)
    _coalesce_out = func.coalesce(Run.tokens_output, 0)
    _coalesce_cost = func.coalesce(Run.estimated_cost, 0)

    time_filter = [
        Run.timestamp >= since,
        Run.timestamp < until,
    ]

    totals_stmt = select(
        func.sum(_coalesce_in).label("tokens_input"),
        func.sum(_coalesce_out).label("tokens_output"),
        func.sum(_coalesce_cost).label("estimated_cost"),
        func.count().label("run_count"),
    ).where(*time_filter)

    row = session.execute(totals_stmt).one()

    by_model_stmt = (
        select(
            func.coalesce(Run.model_used, "unknown").label("model"),
            func.sum(_coalesce_in).label("tokens_input"),
            func.sum(_coalesce_out).label("tokens_output"),
            func.sum(_coalesce_cost).label("estimated_cost"),
            func.count().label("run_count"),
        )
        .where(*time_filter)
        .group_by(func.coalesce(Run.model_used, "unknown"))
        .order_by(func.count().desc())
    )

    by_model: list[ModelUsage] = [
        ModelUsage(
            model=r.model,
            tokens_input=int(r.tokens_input or 0),
            tokens_output=int(r.tokens_output or 0),
            estimated_cost=float(r.estimated_cost or 0),
            run_count=int(r.run_count),
        )
        for r in session.execute(by_model_stmt).all()
    ]

    return UsageSummary(
        tokens_input=int(row.tokens_input or 0),
        tokens_output=int(row.tokens_output or 0),
        estimated_cost=float(row.estimated_cost or 0),
        run_count=int(row.run_count or 0),
        by_model=by_model,
    )


def get_usage_by_day(
    session: Session,
    *,
    since: datetime,
    until: datetime,
) -> list[DailyUsage]:
    """Daily token usage breakdown over a time window.

    Args:
        session: Active SQLAlchemy session.
        since: Start of the window (inclusive).
        until: End of the window (exclusive).

    Returns:
        List of :class:`DailyUsage` dicts ordered by date ascending.
    """
    day_col = cast(Run.timestamp, Date).label("day")

    stmt = (
        select(
            day_col,
            func.sum(func.coalesce(Run.tokens_input, 0)).label("tokens_input"),
            func.sum(func.coalesce(Run.tokens_output, 0)).label("tokens_output"),
            func.sum(func.coalesce(Run.estimated_cost, 0)).label("estimated_cost"),
            func.count().label("run_count"),
        )
        .where(Run.timestamp >= since, Run.timestamp < until)
        .group_by(day_col)
        .order_by(day_col)
    )

    return [
        DailyUsage(
            date=str(r.day),
            tokens_input=int(r.tokens_input or 0),
            tokens_output=int(r.tokens_output or 0),
            estimated_cost=float(r.estimated_cost or 0),
            run_count=int(r.run_count),
        )
        for r in session.execute(stmt).all()
    ]
