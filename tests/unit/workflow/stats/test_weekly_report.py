"""Unit tests for forge.workflow.stats.weekly_report.

All Redis and external I/O is mocked.  Tests cover:

- WeeklyReportData dataclass construction and fields
- TicketSummary dataclass construction and fields
- BottleneckAnalysis dataclass construction and fields
- _parse_checkpoint_stats: extraction from various checkpoint shapes
- _calculate_bottlenecks: averages, ordering, CI fix rate
- _is_within_window: time-window filtering
- _aggregate_tokens: cross-ticket aggregation
- _avg_cycle_time: average cycle time computation
- collect_weekly_data: Redis scan integration with mocked client
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.stats.weekly_report import (
    BottleneckAnalysis,
    TicketSummary,
    WeeklyReportData,
    _aggregate_tokens,
    _avg_cycle_time,
    _calculate_bottlenecks,
    _is_within_window,
    _parse_checkpoint_stats,
    collect_weekly_data,
)

# ---------------------------------------------------------------------------
# Shared helpers / fixtures
# ---------------------------------------------------------------------------

_NOW = datetime(2024, 6, 15, 12, 0, 0, tzinfo=UTC)
_ONE_DAY_AGO = (_NOW - timedelta(days=1)).isoformat()
_TWO_WEEKS_AGO = (_NOW - timedelta(weeks=2)).isoformat()
_TICKET = "AISOS-100"


def _make_stage_data(
    *,
    stage_name: str = "prd",
    iteration_count: int = 1,
    machine_time_seconds: float = 120.0,
    human_time_seconds: float = 0.0,
    input_tokens: int = 500,
    output_tokens: int = 250,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> dict:
    if started_at is None:
        started_at = _ONE_DAY_AGO
    return {
        "stage_name": stage_name,
        "iteration_count": iteration_count,
        "machine_time_seconds": machine_time_seconds,
        "human_time_seconds": human_time_seconds,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _make_state(
    *,
    ticket_key: str = _TICKET,
    ticket_type: str = "Feature",
    stats_outcome: str | None = "Completed",
    is_blocked: bool = False,
    stats_stages: dict | None = None,
    stats_ci_cycles: int = 0,
    updated_at: str | None = None,
    **extra,
) -> dict:
    if stats_stages is None:
        stats_stages = {
            "prd": _make_stage_data(
                stage_name="prd",
                started_at=_ONE_DAY_AGO,
                ended_at=_ONE_DAY_AGO,
            )
        }
    if updated_at is None:
        updated_at = _ONE_DAY_AGO
    return {
        "ticket_key": ticket_key,
        "ticket_type": ticket_type,
        "stats_outcome": stats_outcome,
        "is_blocked": is_blocked,
        "stats_stages": stats_stages,
        "stats_ci_cycles": stats_ci_cycles,
        "updated_at": updated_at,
        **extra,
    }


# ---------------------------------------------------------------------------
# WeeklyReportData dataclass
# ---------------------------------------------------------------------------


class TestWeeklyReportData:
    def test_construction_defaults(self) -> None:
        report = WeeklyReportData(project="AISOS")
        assert report.project == "AISOS"
        assert report.period_days == 7
        assert report.completed_tickets == []
        assert report.in_progress_tickets == []
        assert report.blocked_tickets == []
        assert report.total_input_tokens == 0
        assert report.total_output_tokens == 0
        assert report.tokens_by_stage == {}
        assert report.avg_cycle_time is None
        assert isinstance(report.bottlenecks, BottleneckAnalysis)
        assert report.all_tickets == []

    def test_construction_with_values(self) -> None:
        ticket = TicketSummary(ticket_key="AISOS-1", status="completed")
        report = WeeklyReportData(
            project="AISOS",
            period_days=14,
            completed_tickets=[ticket],
            total_input_tokens=1000,
            total_output_tokens=500,
            avg_cycle_time=3600.0,
        )
        assert report.period_days == 14
        assert len(report.completed_tickets) == 1
        assert report.total_input_tokens == 1000
        assert report.total_output_tokens == 500
        assert report.avg_cycle_time == 3600.0

    def test_report_start_end_fields(self) -> None:
        report = WeeklyReportData(
            project="AISOS",
            report_start="2024-06-08T00:00:00+00:00",
            report_end="2024-06-15T00:00:00+00:00",
        )
        assert report.report_start == "2024-06-08T00:00:00+00:00"
        assert report.report_end == "2024-06-15T00:00:00+00:00"

    def test_mutable_defaults_are_independent(self) -> None:
        r1 = WeeklyReportData(project="A")
        r2 = WeeklyReportData(project="B")
        r1.completed_tickets.append(TicketSummary(ticket_key="A-1"))
        assert r2.completed_tickets == []


# ---------------------------------------------------------------------------
# TicketSummary dataclass
# ---------------------------------------------------------------------------


class TestTicketSummary:
    def test_defaults(self) -> None:
        t = TicketSummary(ticket_key="AISOS-1")
        assert t.ticket_type == "Feature"
        assert t.status == "in_progress"
        assert t.duration_seconds is None
        assert t.input_tokens == 0
        assert t.output_tokens == 0
        assert t.tokens_by_stage == {}
        assert t.revision_counts == {}
        assert t.ci_cycles == 0
        assert t.outcome is None
        assert t.stage_durations == {}

    def test_all_fields(self) -> None:
        t = TicketSummary(
            ticket_key="AISOS-2",
            ticket_type="Bug",
            status="completed",
            duration_seconds=3600.0,
            input_tokens=1000,
            output_tokens=500,
            tokens_by_stage={"prd": (1000, 500)},
            revision_counts={"prd": 2},
            ci_cycles=3,
            outcome="Completed",
            stage_durations={"prd": 120.0},
        )
        assert t.ticket_type == "Bug"
        assert t.status == "completed"
        assert t.duration_seconds == 3600.0
        assert t.ci_cycles == 3


# ---------------------------------------------------------------------------
# BottleneckAnalysis dataclass
# ---------------------------------------------------------------------------


class TestBottleneckAnalysis:
    def test_defaults(self) -> None:
        b = BottleneckAnalysis()
        assert b.avg_stage_durations == {}
        assert b.most_revised_stages == []
        assert b.ci_fix_rate == 0.0
        assert b.slowest_stage is None
        assert b.total_tickets_analyzed == 0

    def test_with_values(self) -> None:
        b = BottleneckAnalysis(
            avg_stage_durations={"prd": 60.0, "spec": 120.0},
            most_revised_stages=["spec", "prd"],
            ci_fix_rate=0.5,
            slowest_stage="spec",
            total_tickets_analyzed=4,
        )
        assert b.ci_fix_rate == 0.5
        assert b.slowest_stage == "spec"
        assert b.total_tickets_analyzed == 4


# ---------------------------------------------------------------------------
# _parse_checkpoint_stats
# ---------------------------------------------------------------------------


class TestParseCheckpointStats:
    def test_missing_ticket_key_returns_none(self) -> None:
        result = _parse_checkpoint_stats({"stats_stages": {}})
        assert result is None

    def test_missing_stats_stages_returns_none(self) -> None:
        result = _parse_checkpoint_stats({"ticket_key": "AISOS-1"})
        assert result is None

    def test_minimal_valid_state(self) -> None:
        state = {"ticket_key": "AISOS-1", "stats_stages": {}}
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.ticket_key == "AISOS-1"
        assert result.input_tokens == 0
        assert result.output_tokens == 0

    def test_token_aggregation(self) -> None:
        state = {
            "ticket_key": "AISOS-1",
            "stats_stages": {
                "prd": _make_stage_data(input_tokens=300, output_tokens=150),
                "spec": _make_stage_data(
                    stage_name="spec", input_tokens=200, output_tokens=100
                ),
            },
            "stats_outcome": "Completed",
        }
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.input_tokens == 500
        assert result.output_tokens == 250
        assert result.tokens_by_stage["prd"] == (300, 150)
        assert result.tokens_by_stage["spec"] == (200, 100)

    def test_status_completed(self) -> None:
        state = _make_state(stats_outcome="Completed")
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.status == "completed"

    def test_status_blocked_from_is_blocked(self) -> None:
        state = _make_state(stats_outcome=None, is_blocked=True)
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.status == "blocked"

    def test_status_blocked_from_outcome(self) -> None:
        state = _make_state(stats_outcome="Blocked: waiting for approval")
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.status == "blocked"

    def test_status_in_progress(self) -> None:
        state = _make_state(stats_outcome=None, is_blocked=False)
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.status == "in_progress"

    def test_ticket_type_extraction(self) -> None:
        state = _make_state(ticket_type="Bug")
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.ticket_type == "Bug"

    def test_ticket_type_defaults_to_feature(self) -> None:
        state = {"ticket_key": "AISOS-1", "stats_stages": {}}
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.ticket_type == "Feature"

    def test_ci_cycles_extracted(self) -> None:
        state = _make_state(stats_ci_cycles=3)
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.ci_cycles == 3

    def test_revision_counts_extracted(self) -> None:
        state = {
            "ticket_key": "AISOS-1",
            "stats_stages": {
                "prd": _make_stage_data(iteration_count=3),
                "spec": _make_stage_data(stage_name="spec", iteration_count=1),
            },
            "stats_outcome": "Completed",
        }
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.revision_counts["prd"] == 3
        assert result.revision_counts["spec"] == 1

    def test_stage_durations_extracted(self) -> None:
        state = {
            "ticket_key": "AISOS-1",
            "stats_stages": {
                "prd": _make_stage_data(machine_time_seconds=60.0),
                "spec": _make_stage_data(stage_name="spec", machine_time_seconds=90.0),
            },
            "stats_outcome": "Completed",
        }
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.stage_durations["prd"] == 60.0
        assert result.stage_durations["spec"] == 90.0

    def test_duration_seconds_for_completed_ticket(self) -> None:
        started = "2024-06-14T10:00:00+00:00"
        ended = "2024-06-14T11:00:00+00:00"
        state = {
            "ticket_key": "AISOS-1",
            "stats_stages": {
                "prd": _make_stage_data(started_at=started, ended_at=ended),
            },
            "stats_outcome": "Completed",
        }
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.duration_seconds == 3600.0

    def test_duration_seconds_none_when_no_timestamps(self) -> None:
        state = {
            "ticket_key": "AISOS-1",
            "stats_stages": {
                "prd": {
                    "stage_name": "prd",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "iteration_count": 1,
                    "machine_time_seconds": 0.0,
                    "started_at": None,
                    "ended_at": None,
                }
            },
            "stats_outcome": "Completed",
        }
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.duration_seconds is None

    def test_in_progress_duration_measured_from_start_to_now(self) -> None:
        # The start is 1 hour ago; outcome is None (in_progress)
        one_hour_ago = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        state = {
            "ticket_key": "AISOS-1",
            "stats_stages": {
                "prd": _make_stage_data(started_at=one_hour_ago, ended_at=None),
            },
            "stats_outcome": None,
        }
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.status == "in_progress"
        # Allow generous delta for test execution time
        assert result.duration_seconds is not None
        assert 3500 < result.duration_seconds < 3700

    def test_malformed_stats_stages_treated_as_empty(self) -> None:
        state = {"ticket_key": "AISOS-1", "stats_stages": "not-a-dict"}
        result = _parse_checkpoint_stats(state)
        assert result is not None
        assert result.input_tokens == 0


# ---------------------------------------------------------------------------
# _calculate_bottlenecks
# ---------------------------------------------------------------------------


class TestCalculateBottlenecks:
    def test_empty_list(self) -> None:
        result = _calculate_bottlenecks([])
        assert result.total_tickets_analyzed == 0
        assert result.avg_stage_durations == {}
        assert result.most_revised_stages == []
        assert result.ci_fix_rate == 0.0
        assert result.slowest_stage is None

    def test_single_ticket_no_ci(self) -> None:
        ticket = TicketSummary(
            ticket_key="AISOS-1",
            stage_durations={"prd": 60.0, "spec": 120.0},
            revision_counts={"prd": 2, "spec": 1},
            ci_cycles=0,
        )
        result = _calculate_bottlenecks([ticket])
        assert result.total_tickets_analyzed == 1
        assert result.avg_stage_durations["prd"] == 60.0
        assert result.avg_stage_durations["spec"] == 120.0
        assert result.slowest_stage == "spec"
        assert result.ci_fix_rate == 0.0

    def test_ci_fix_rate_all_triggered(self) -> None:
        tickets = [
            TicketSummary(ticket_key="A-1", ci_cycles=2),
            TicketSummary(ticket_key="A-2", ci_cycles=1),
        ]
        result = _calculate_bottlenecks(tickets)
        assert result.ci_fix_rate == 1.0

    def test_ci_fix_rate_partial(self) -> None:
        tickets = [
            TicketSummary(ticket_key="A-1", ci_cycles=1),
            TicketSummary(ticket_key="A-2", ci_cycles=0),
            TicketSummary(ticket_key="A-3", ci_cycles=0),
            TicketSummary(ticket_key="A-4", ci_cycles=0),
        ]
        result = _calculate_bottlenecks(tickets)
        assert result.ci_fix_rate == pytest.approx(0.25)

    def test_avg_stage_durations_across_tickets(self) -> None:
        tickets = [
            TicketSummary(ticket_key="A-1", stage_durations={"prd": 60.0}),
            TicketSummary(ticket_key="A-2", stage_durations={"prd": 120.0}),
        ]
        result = _calculate_bottlenecks(tickets)
        assert result.avg_stage_durations["prd"] == pytest.approx(90.0)

    def test_most_revised_stages_ordering(self) -> None:
        tickets = [
            TicketSummary(
                ticket_key="A-1",
                revision_counts={"spec": 5, "prd": 1, "ci": 3},
            ),
        ]
        result = _calculate_bottlenecks(tickets)
        assert result.most_revised_stages[0] == "spec"
        assert result.most_revised_stages[1] == "ci"
        assert result.most_revised_stages[2] == "prd"

    def test_slowest_stage(self) -> None:
        tickets = [
            TicketSummary(
                ticket_key="A-1",
                stage_durations={"prd": 60.0, "implementation": 3600.0, "ci": 300.0},
            ),
        ]
        result = _calculate_bottlenecks(tickets)
        assert result.slowest_stage == "implementation"

    def test_stages_only_in_some_tickets(self) -> None:
        tickets = [
            TicketSummary(
                ticket_key="A-1", stage_durations={"prd": 60.0, "spec": 90.0}
            ),
            TicketSummary(ticket_key="A-2", stage_durations={"prd": 120.0}),
        ]
        result = _calculate_bottlenecks(tickets)
        # prd averaged across both; spec only from A-1
        assert result.avg_stage_durations["prd"] == pytest.approx(90.0)
        assert result.avg_stage_durations["spec"] == pytest.approx(90.0)


# ---------------------------------------------------------------------------
# _is_within_window
# ---------------------------------------------------------------------------


class TestIsWithinWindow:
    def _cutoff(self) -> datetime:
        return _NOW - timedelta(days=7)

    def test_updated_at_within_window(self) -> None:
        state = {"updated_at": _ONE_DAY_AGO}
        assert _is_within_window(state, self._cutoff()) is True

    def test_updated_at_outside_window(self) -> None:
        state = {"updated_at": _TWO_WEEKS_AGO}
        assert _is_within_window(state, self._cutoff()) is False

    def test_stage_started_at_within_window(self) -> None:
        state = {
            "updated_at": _TWO_WEEKS_AGO,
            "stats_stages": {
                "prd": {"started_at": _ONE_DAY_AGO, "ended_at": None}
            },
        }
        assert _is_within_window(state, self._cutoff()) is True

    def test_stage_ended_at_within_window(self) -> None:
        state = {
            "updated_at": _TWO_WEEKS_AGO,
            "stats_stages": {
                "prd": {"started_at": _TWO_WEEKS_AGO, "ended_at": _ONE_DAY_AGO}
            },
        }
        assert _is_within_window(state, self._cutoff()) is True

    def test_all_timestamps_outside_window(self) -> None:
        state = {
            "updated_at": _TWO_WEEKS_AGO,
            "stats_stages": {
                "prd": {"started_at": _TWO_WEEKS_AGO, "ended_at": _TWO_WEEKS_AGO}
            },
        }
        assert _is_within_window(state, self._cutoff()) is False

    def test_no_timestamps(self) -> None:
        state = {"stats_stages": {}}
        assert _is_within_window(state, self._cutoff()) is False

    def test_missing_stats_stages(self) -> None:
        state = {"updated_at": _TWO_WEEKS_AGO}
        assert _is_within_window(state, self._cutoff()) is False

    def test_malformed_stats_stages(self) -> None:
        state = {"stats_stages": "bad", "updated_at": _TWO_WEEKS_AGO}
        assert _is_within_window(state, self._cutoff()) is False


# ---------------------------------------------------------------------------
# _aggregate_tokens
# ---------------------------------------------------------------------------


class TestAggregateTokens:
    def test_empty_list(self) -> None:
        total_in, total_out, by_stage = _aggregate_tokens([])
        assert total_in == 0
        assert total_out == 0
        assert by_stage == {}

    def test_single_ticket(self) -> None:
        ticket = TicketSummary(
            ticket_key="A-1",
            input_tokens=1000,
            output_tokens=500,
            tokens_by_stage={"prd": (1000, 500)},
        )
        total_in, total_out, by_stage = _aggregate_tokens([ticket])
        assert total_in == 1000
        assert total_out == 500
        assert by_stage["prd"] == (1000, 500)

    def test_multiple_tickets_same_stage(self) -> None:
        t1 = TicketSummary(
            ticket_key="A-1",
            input_tokens=300,
            output_tokens=100,
            tokens_by_stage={"prd": (300, 100)},
        )
        t2 = TicketSummary(
            ticket_key="A-2",
            input_tokens=200,
            output_tokens=150,
            tokens_by_stage={"prd": (200, 150)},
        )
        total_in, total_out, by_stage = _aggregate_tokens([t1, t2])
        assert total_in == 500
        assert total_out == 250
        assert by_stage["prd"] == (500, 250)

    def test_multiple_stages(self) -> None:
        ticket = TicketSummary(
            ticket_key="A-1",
            input_tokens=700,
            output_tokens=350,
            tokens_by_stage={"prd": (300, 150), "spec": (400, 200)},
        )
        total_in, total_out, by_stage = _aggregate_tokens([ticket])
        assert total_in == 700
        assert total_out == 350
        assert by_stage["prd"] == (300, 150)
        assert by_stage["spec"] == (400, 200)


# ---------------------------------------------------------------------------
# _avg_cycle_time
# ---------------------------------------------------------------------------


class TestAvgCycleTime:
    def test_empty_list(self) -> None:
        assert _avg_cycle_time([]) is None

    def test_no_completed_tickets(self) -> None:
        tickets = [
            TicketSummary(ticket_key="A-1", status="in_progress", duration_seconds=100.0)
        ]
        assert _avg_cycle_time(tickets) is None

    def test_single_completed_ticket(self) -> None:
        tickets = [
            TicketSummary(ticket_key="A-1", status="completed", duration_seconds=3600.0)
        ]
        assert _avg_cycle_time(tickets) == pytest.approx(3600.0)

    def test_multiple_completed_tickets(self) -> None:
        tickets = [
            TicketSummary(ticket_key="A-1", status="completed", duration_seconds=3600.0),
            TicketSummary(ticket_key="A-2", status="completed", duration_seconds=7200.0),
        ]
        assert _avg_cycle_time(tickets) == pytest.approx(5400.0)

    def test_completed_ticket_without_duration(self) -> None:
        tickets = [
            TicketSummary(ticket_key="A-1", status="completed", duration_seconds=None),
            TicketSummary(ticket_key="A-2", status="completed", duration_seconds=3600.0),
        ]
        assert _avg_cycle_time(tickets) == pytest.approx(3600.0)

    def test_mixed_statuses_only_completed_counted(self) -> None:
        tickets = [
            TicketSummary(ticket_key="A-1", status="completed", duration_seconds=3600.0),
            TicketSummary(
                ticket_key="A-2", status="in_progress", duration_seconds=1800.0
            ),
            TicketSummary(ticket_key="A-3", status="blocked", duration_seconds=7200.0),
        ]
        assert _avg_cycle_time(tickets) == pytest.approx(3600.0)


# ---------------------------------------------------------------------------
# collect_weekly_data — integration with mocked Redis
# ---------------------------------------------------------------------------


def _make_redis_mock(keys: list[str], states: dict[str, dict]) -> MagicMock:
    """Build a fake async Redis client that returns the given keys and states."""
    mock = MagicMock()

    # scan returns (cursor, keys_list); call it once and return 0 to stop loop
    async def scan_side_effect(cursor, match, count):
        if cursor == 0:
            # Filter keys by match pattern (simple prefix check)
            prefix = match.rstrip("*")
            filtered = [k for k in keys if k.startswith(prefix)]
            return (0, filtered)
        return (0, [])

    mock.scan = AsyncMock(side_effect=scan_side_effect)

    async def get_side_effect(key):
        state = states.get(key)
        if state is None:
            return None
        return json.dumps(state)

    mock.get = AsyncMock(side_effect=get_side_effect)
    return mock


@pytest.fixture
def _redis_mock_with_data():
    """Fixture providing a Redis mock with two checkpoints in the window."""
    ticket1 = "AISOS-1"
    ticket2 = "AISOS-2"
    key1 = f"langgraph:checkpoint:{ticket1}"
    key2 = f"langgraph:checkpoint:{ticket2}"
    state1 = _make_state(
        ticket_key=ticket1,
        stats_outcome="Completed",
        stats_stages={
            "prd": _make_stage_data(
                stage_name="prd",
                input_tokens=300,
                output_tokens=150,
                started_at=_ONE_DAY_AGO,
                ended_at=_ONE_DAY_AGO,
                machine_time_seconds=60.0,
                iteration_count=1,
            )
        },
        stats_ci_cycles=0,
    )
    state2 = _make_state(
        ticket_key=ticket2,
        stats_outcome=None,
        is_blocked=False,
        stats_stages={
            "prd": _make_stage_data(
                stage_name="prd",
                input_tokens=200,
                output_tokens=100,
                started_at=_ONE_DAY_AGO,
                ended_at=None,
                machine_time_seconds=30.0,
                iteration_count=2,
            )
        },
        stats_ci_cycles=1,
    )
    redis_mock = _make_redis_mock(
        keys=[key1, key2],
        states={key1: state1, key2: state2},
    )
    return redis_mock


def _patch_now(fixed_now: datetime):
    """Context manager that patches datetime.now(UTC) in the weekly_report module.

    Replaces the ``datetime`` name in the weekly_report module with a subclass
    whose ``now()`` classmethod always returns *fixed_now*.  All other
    ``datetime`` functionality (fromisoformat, arithmetic, etc.) is inherited
    unchanged.
    """

    class _FakeDatetime(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed_now

    return patch("forge.workflow.stats.weekly_report.datetime", _FakeDatetime)


class TestCollectWeeklyData:
    @pytest.mark.asyncio
    async def test_returns_weekly_report_data(self, _redis_mock_with_data) -> None:
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=_redis_mock_with_data),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS", days=7)
        assert isinstance(report, WeeklyReportData)

    @pytest.mark.asyncio
    async def test_project_and_period_fields(self, _redis_mock_with_data) -> None:
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=_redis_mock_with_data),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS", days=14)
        assert report.project == "AISOS"
        assert report.period_days == 14

    @pytest.mark.asyncio
    async def test_completed_and_in_progress_split(
        self, _redis_mock_with_data
    ) -> None:
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=_redis_mock_with_data),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS")
        assert len(report.completed_tickets) == 1
        assert len(report.in_progress_tickets) == 1
        assert len(report.blocked_tickets) == 0
        assert report.completed_tickets[0].ticket_key == "AISOS-1"
        assert report.in_progress_tickets[0].ticket_key == "AISOS-2"

    @pytest.mark.asyncio
    async def test_token_aggregation(self, _redis_mock_with_data) -> None:
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=_redis_mock_with_data),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS")
        assert report.total_input_tokens == 500   # 300 + 200
        assert report.total_output_tokens == 250  # 150 + 100

    @pytest.mark.asyncio
    async def test_bottlenecks_populated(self, _redis_mock_with_data) -> None:
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=_redis_mock_with_data),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS")
        assert report.bottlenecks.total_tickets_analyzed == 2
        assert "prd" in report.bottlenecks.avg_stage_durations

    @pytest.mark.asyncio
    async def test_avg_cycle_time_computed(self, _redis_mock_with_data) -> None:
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=_redis_mock_with_data),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS")
        # Only the completed ticket has an ended_at timestamp; avg_cycle_time
        # should be non-None for the completed one.
        assert report.avg_cycle_time is not None

    @pytest.mark.asyncio
    async def test_empty_project_returns_zero_report(self) -> None:
        redis_mock = _make_redis_mock(keys=[], states={})
        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            new=AsyncMock(return_value=redis_mock),
        ):
            report = await collect_weekly_data("EMPTY")
        assert report.completed_tickets == []
        assert report.in_progress_tickets == []
        assert report.blocked_tickets == []
        assert report.total_input_tokens == 0
        assert report.avg_cycle_time is None

    @pytest.mark.asyncio
    async def test_tickets_outside_window_excluded(self) -> None:
        ticket_key = "AISOS-99"
        redis_key = f"langgraph:checkpoint:{ticket_key}"
        # All timestamps are two weeks ago — outside a 7-day window
        old_state = _make_state(
            ticket_key=ticket_key,
            stats_outcome="Completed",
            updated_at=_TWO_WEEKS_AGO,
            stats_stages={
                "prd": _make_stage_data(
                    started_at=_TWO_WEEKS_AGO, ended_at=_TWO_WEEKS_AGO
                )
            },
        )
        redis_mock = _make_redis_mock(
            keys=[redis_key], states={redis_key: old_state}
        )
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis_mock),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS", days=7)
        assert report.all_tickets == []

    @pytest.mark.asyncio
    async def test_blocked_ticket_categorised(self) -> None:
        ticket_key = "AISOS-77"
        redis_key = f"langgraph:checkpoint:{ticket_key}"
        state = _make_state(
            ticket_key=ticket_key,
            stats_outcome=None,
            is_blocked=True,
            updated_at=_ONE_DAY_AGO,
        )
        redis_mock = _make_redis_mock(
            keys=[redis_key], states={redis_key: state}
        )
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis_mock),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS")
        assert len(report.blocked_tickets) == 1
        assert report.blocked_tickets[0].ticket_key == ticket_key

    @pytest.mark.asyncio
    async def test_malformed_json_skipped(self) -> None:
        redis_key = "langgraph:checkpoint:AISOS-BAD"
        mock = MagicMock()

        async def scan_side_effect(cursor, match, count):
            if cursor == 0:
                return (0, [redis_key])
            return (0, [])

        mock.scan = AsyncMock(side_effect=scan_side_effect)
        mock.get = AsyncMock(return_value="not-valid-json{{{{")

        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            new=AsyncMock(return_value=mock),
        ):
            report = await collect_weekly_data("AISOS")
        # Should not raise; simply skips the malformed key
        assert report.all_tickets == []

    @pytest.mark.asyncio
    async def test_redis_scan_failure_returns_empty_report(self) -> None:
        mock = MagicMock()
        mock.scan = AsyncMock(side_effect=ConnectionError("Redis down"))

        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            new=AsyncMock(return_value=mock),
        ):
            report = await collect_weekly_data("AISOS")
        assert report.all_tickets == []

    @pytest.mark.asyncio
    async def test_report_start_end_populated(self) -> None:
        redis_mock = _make_redis_mock(keys=[], states={})
        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            new=AsyncMock(return_value=redis_mock),
        ):
            report = await collect_weekly_data("AISOS", days=7)
        assert report.report_start != ""
        assert report.report_end != ""
        # Both should be parseable ISO-8601
        start = datetime.fromisoformat(report.report_start)
        end = datetime.fromisoformat(report.report_end)
        assert (end - start).days == 7

    @pytest.mark.asyncio
    async def test_all_tickets_field_populated(self, _redis_mock_with_data) -> None:
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=_redis_mock_with_data),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS")
        assert len(report.all_tickets) == 2

    @pytest.mark.asyncio
    async def test_tokens_by_stage_populated(self, _redis_mock_with_data) -> None:
        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=_redis_mock_with_data),
            ),
            _patch_now(_NOW),
        ):
            report = await collect_weekly_data("AISOS")
        assert "prd" in report.tokens_by_stage
        total_in, total_out = report.tokens_by_stage["prd"]
        assert total_in == 500   # 300 + 200
        assert total_out == 250  # 150 + 100

    @pytest.mark.asyncio
    async def test_null_value_from_redis_skipped(self) -> None:
        redis_key = "langgraph:checkpoint:AISOS-NULL"
        mock = MagicMock()

        async def scan_side_effect(cursor, match, count):
            if cursor == 0:
                return (0, [redis_key])
            return (0, [])

        mock.scan = AsyncMock(side_effect=scan_side_effect)
        mock.get = AsyncMock(return_value=None)

        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            new=AsyncMock(return_value=mock),
        ):
            report = await collect_weekly_data("AISOS")
        assert report.all_tickets == []


# ---------------------------------------------------------------------------
# Import path checks
# ---------------------------------------------------------------------------


class TestImports:
    def test_public_symbols_importable(self) -> None:
        from forge.workflow.stats.weekly_report import (  # noqa: F401
            BottleneckAnalysis,
            TicketSummary,
            WeeklyReportData,
            collect_weekly_data,
        )

    def test_internal_helpers_importable(self) -> None:
        from forge.workflow.stats.weekly_report import (  # noqa: F401
            _aggregate_tokens,
            _avg_cycle_time,
            _calculate_bottlenecks,
            _is_within_window,
            _parse_checkpoint_stats,
        )
