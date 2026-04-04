"""HTTP routes for usage metrics (Phase 5 monitoring dummies)."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Query

from harle.api.models import (
    DailyUsageSummary,
    ModelUsageSummary,
    UsageResponse,
)
from harle.db.connection import Database

logger = logging.getLogger(__name__)


def build_metrics_router(*, db: Database | None = None) -> APIRouter:
    """Create metrics routes bound to the database instance.

    Args:
        db: Optional database instance (required for usage queries).
    """
    router = APIRouter(prefix="/metrics", tags=["metrics"])

    @router.get("/usage", response_model=UsageResponse)
    def metrics_usage(
        days: int = Query(default=7, ge=1, le=90, description="Number of days to aggregate"),
    ) -> UsageResponse:
        """Aggregate LLM token usage and cost over the last N days.

        Returns zeros until the orchestrator populates token columns on run rows.
        """
        if db is None:
            raise HTTPException(
                status_code=503,
                detail="Database is not configured. Set DATABASE_URL in config.",
            )
        from harle.db.usage import get_usage_by_day, get_usage_summary

        until = datetime.now(tz=timezone.utc)
        since = until - timedelta(days=days)

        with db.session() as session:
            summary = get_usage_summary(session, since=since, until=until)
            daily = get_usage_by_day(session, since=since, until=until)

        return UsageResponse(
            days=days,
            since=since.isoformat(),
            until=until.isoformat(),
            tokens_input=summary["tokens_input"],
            tokens_output=summary["tokens_output"],
            estimated_cost=summary["estimated_cost"],
            run_count=summary["run_count"],
            by_model=[
                ModelUsageSummary(
                    model=m["model"],
                    tokens_input=m["tokens_input"],
                    tokens_output=m["tokens_output"],
                    estimated_cost=m["estimated_cost"],
                    run_count=m["run_count"],
                )
                for m in summary["by_model"]
            ],
            by_day=[
                DailyUsageSummary(
                    date=d["date"],
                    tokens_input=d["tokens_input"],
                    tokens_output=d["tokens_output"],
                    estimated_cost=d["estimated_cost"],
                    run_count=d["run_count"],
                )
                for d in daily
            ],
        )

    return router
