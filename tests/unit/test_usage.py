"""Unit tests for harle.db.usage — get_usage_summary, get_usage_by_day."""

from __future__ import annotations

from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

from harle.db.usage import get_usage_by_day, get_usage_summary


def _utc(*args: int) -> datetime:
    return datetime(*args, tzinfo=timezone.utc)


class TestGetUsageSummary:
    def test_empty_window_returns_zeros_and_empty_by_model(self) -> None:
        session = MagicMock()
        totals_row = SimpleNamespace(
            tokens_input=None,
            tokens_output=None,
            estimated_cost=None,
            run_count=0,
        )
        mock_totals = MagicMock()
        mock_totals.one.return_value = totals_row
        mock_by_model = MagicMock()
        mock_by_model.all.return_value = []
        session.execute.side_effect = [mock_totals, mock_by_model]

        out = get_usage_summary(
            session,
            since=_utc(2026, 1, 1),
            until=_utc(2026, 1, 2),
        )

        assert out["tokens_input"] == 0
        assert out["tokens_output"] == 0
        assert out["estimated_cost"] == 0.0
        assert out["run_count"] == 0
        assert out["by_model"] == []
        assert session.execute.call_count == 2

    def test_totals_and_per_model_breakdown(self) -> None:
        session = MagicMock()
        totals_row = SimpleNamespace(
            tokens_input=100,
            tokens_output=40,
            estimated_cost=0.25,
            run_count=3,
        )
        mock_totals = MagicMock()
        mock_totals.one.return_value = totals_row
        model_rows = [
            SimpleNamespace(
                model="gpt-4o",
                tokens_input=70,
                tokens_output=30,
                estimated_cost=0.2,
                run_count=2,
            ),
            SimpleNamespace(
                model="gpt-4o-mini",
                tokens_input=30,
                tokens_output=10,
                estimated_cost=0.05,
                run_count=1,
            ),
        ]
        mock_by_model = MagicMock()
        mock_by_model.all.return_value = model_rows
        session.execute.side_effect = [mock_totals, mock_by_model]

        out = get_usage_summary(
            session,
            since=_utc(2026, 2, 1),
            until=_utc(2026, 2, 28),
        )

        assert out["tokens_input"] == 100
        assert out["tokens_output"] == 40
        assert out["estimated_cost"] == 0.25
        assert out["run_count"] == 3
        assert len(out["by_model"]) == 2
        assert out["by_model"][0]["model"] == "gpt-4o"
        assert out["by_model"][0]["tokens_input"] == 70
        assert out["by_model"][0]["run_count"] == 2
        assert out["by_model"][1]["model"] == "gpt-4o-mini"

    def test_unknown_model_row_coalesces_null_metrics(self) -> None:
        """Per-model rows still coerce NULL sums to zero (defensive)."""
        session = MagicMock()
        totals_row = SimpleNamespace(
            tokens_input=0,
            tokens_output=0,
            estimated_cost=0.0,
            run_count=1,
        )
        mock_totals = MagicMock()
        mock_totals.one.return_value = totals_row
        model_rows = [
            SimpleNamespace(
                model="unknown",
                tokens_input=None,
                tokens_output=None,
                estimated_cost=None,
                run_count=1,
            ),
        ]
        mock_by_model = MagicMock()
        mock_by_model.all.return_value = model_rows
        session.execute.side_effect = [mock_totals, mock_by_model]

        out = get_usage_summary(
            session,
            since=_utc(2026, 3, 1),
            until=_utc(2026, 3, 2),
        )

        bucket = out["by_model"][0]
        assert bucket["model"] == "unknown"
        assert bucket["tokens_input"] == 0
        assert bucket["tokens_output"] == 0
        assert bucket["estimated_cost"] == 0.0
        assert bucket["run_count"] == 1


class TestGetUsageByDay:
    def test_empty_returns_empty_list(self) -> None:
        session = MagicMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        session.execute.return_value = mock_result

        out = get_usage_by_day(
            session,
            since=_utc(2026, 4, 1),
            until=_utc(2026, 4, 30),
        )

        assert out == []
        session.execute.assert_called_once()

    def test_multiple_days_ordered_ascending(self) -> None:
        session = MagicMock()
        rows = [
            SimpleNamespace(
                day=date(2026, 4, 1),
                tokens_input=10,
                tokens_output=5,
                estimated_cost=0.01,
                run_count=1,
            ),
            SimpleNamespace(
                day=date(2026, 4, 3),
                tokens_input=20,
                tokens_output=8,
                estimated_cost=0.02,
                run_count=2,
            ),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        session.execute.return_value = mock_result

        out = get_usage_by_day(
            session,
            since=_utc(2026, 4, 1),
            until=_utc(2026, 4, 10),
        )

        assert len(out) == 2
        assert out[0]["date"] == "2026-04-01"
        assert out[0]["tokens_input"] == 10
        assert out[0]["run_count"] == 1
        assert out[1]["date"] == "2026-04-03"
        assert out[1]["tokens_input"] == 20
        assert out[1]["run_count"] == 2

    def test_coalesces_null_aggregates_per_day(self) -> None:
        session = MagicMock()
        rows = [
            SimpleNamespace(
                day=date(2026, 5, 1),
                tokens_input=None,
                tokens_output=None,
                estimated_cost=None,
                run_count=1,
            ),
        ]
        mock_result = MagicMock()
        mock_result.all.return_value = rows
        session.execute.return_value = mock_result

        out = get_usage_by_day(
            session,
            since=_utc(2026, 5, 1),
            until=_utc(2026, 5, 2),
        )

        assert out[0]["tokens_input"] == 0
        assert out[0]["tokens_output"] == 0
        assert out[0]["estimated_cost"] == 0.0
        assert out[0]["run_count"] == 1
