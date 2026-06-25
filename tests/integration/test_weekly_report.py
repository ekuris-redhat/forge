"""Integration tests for the weekly reporting system.

These tests verify end-to-end flows for the weekly reporting system including:
- Data aggregation from Redis checkpoints (collect_weekly_data)
- Date-range and project filtering
- Per-feature rollup grouping
- CLI output: text, JSON, and file export
- Jira ticket creation and idempotent updates
- Notification delivery

Redis and Jira network calls are mocked to avoid external dependencies.
"""

from __future__ import annotations

import argparse
import json
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.integrations.jira.models import JiraIssue
from forge.workflow.stats.weekly_report import (
    UNASSIGNED_FEATURE_KEY,
    TicketSummary,
    WeeklyReportData,
    collect_weekly_data,
)

# ---------------------------------------------------------------------------
# Shared constants — computed at import time so timestamps are always recent
# ---------------------------------------------------------------------------

_NOW = datetime.now(UTC)
_ONE_DAY_AGO = (_NOW - timedelta(days=1)).isoformat()
_THREE_DAYS_AGO = (_NOW - timedelta(days=3)).isoformat()
_TEN_DAYS_AGO = (_NOW - timedelta(days=10)).isoformat()


# ---------------------------------------------------------------------------
# Fixture: mock_workflow_checkpoints
# ---------------------------------------------------------------------------


def _make_stage(
    stage_name: str = "prd",
    *,
    iteration_count: int = 1,
    machine_time_seconds: float = 60.0,
    human_time_seconds: float = 0.0,
    input_tokens: int = 500,
    output_tokens: int = 250,
    started_at: str | None = None,
    ended_at: str | None = None,
) -> dict:
    """Build a single stage stats dict with sensible defaults."""
    return {
        "stage_name": stage_name,
        "iteration_count": iteration_count,
        "machine_time_seconds": machine_time_seconds,
        "human_time_seconds": human_time_seconds,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "started_at": started_at or _ONE_DAY_AGO,
        "ended_at": ended_at,
    }


def _make_checkpoint(
    ticket_key: str = "PROJ-1",
    *,
    ticket_type: str = "Feature",
    workflow_outcome: str | None = "Completed",
    is_blocked: bool = False,
    stats_ci_cycles: int = 0,
    updated_at: str | None = None,
    stage_timestamps: dict | None = None,
    **extra: object,
) -> dict:
    """Build a minimal checkpoint state dict that weekly_report can parse."""
    if stage_timestamps is None:
        stage_timestamps = {
            "prd": _make_stage(
                "prd",
                started_at=_ONE_DAY_AGO,
                ended_at=_ONE_DAY_AGO,
            )
        }
    return {
        "ticket_key": ticket_key,
        "ticket_type": ticket_type,
        "workflow_outcome": workflow_outcome,
        "is_blocked": is_blocked,
        "stage_timestamps": stage_timestamps,
        "stats_ci_cycles": stats_ci_cycles,
        "updated_at": updated_at or _ONE_DAY_AGO,
        **extra,
    }


@pytest.fixture
def mock_workflow_checkpoints() -> dict[str, dict]:
    """Factory: a dict of ticket_key to checkpoint state for PROJ-* tickets.

    Contains:
    - PROJ-1: completed Feature, PRD + Spec stages, 1 CI cycle
    - PROJ-2: in-progress Feature, PRD stage only
    - PROJ-3: blocked Feature, PRD stage, is_blocked=True
    """
    return {
        "PROJ-1": _make_checkpoint(
            ticket_key="PROJ-1",
            ticket_type="Feature",
            workflow_outcome="Completed",
            stats_ci_cycles=1,
            stage_timestamps={
                "prd": _make_stage(
                    "prd",
                    iteration_count=2,
                    machine_time_seconds=45.0,
                    input_tokens=1200,
                    output_tokens=2000,
                    started_at=_ONE_DAY_AGO,
                    ended_at=_ONE_DAY_AGO,
                ),
                "spec": _make_stage(
                    "spec",
                    iteration_count=1,
                    machine_time_seconds=30.0,
                    input_tokens=800,
                    output_tokens=1500,
                    started_at=_ONE_DAY_AGO,
                    ended_at=_ONE_DAY_AGO,
                ),
            },
        ),
        "PROJ-2": _make_checkpoint(
            ticket_key="PROJ-2",
            ticket_type="Feature",
            workflow_outcome=None,
            stage_timestamps={
                "prd": _make_stage(
                    "prd",
                    iteration_count=1,
                    machine_time_seconds=60.0,
                    input_tokens=700,
                    output_tokens=900,
                    started_at=_ONE_DAY_AGO,
                    ended_at=None,  # Still running
                )
            },
        ),
        "PROJ-3": _make_checkpoint(
            ticket_key="PROJ-3",
            ticket_type="Feature",
            workflow_outcome=None,
            is_blocked=True,
            stage_timestamps={
                "prd": _make_stage(
                    "prd",
                    iteration_count=3,
                    machine_time_seconds=120.0,
                    input_tokens=3000,
                    output_tokens=4000,
                    started_at=_ONE_DAY_AGO,
                    ended_at=_ONE_DAY_AGO,
                )
            },
        ),
    }


# ---------------------------------------------------------------------------
# Fixture: mock_jira_responses
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_jira_responses() -> MagicMock:
    """Mock JiraClient with pre-configured responses for weekly report operations."""
    jira = MagicMock()
    jira.close = AsyncMock()
    jira.get_issue = AsyncMock()
    jira.search_issues = AsyncMock(return_value=[])
    jira.create_task = AsyncMock(return_value="PROJ-99")
    jira.update_description = AsyncMock()
    jira.add_comment = AsyncMock()
    jira.get_project_property = AsyncMock(return_value=None)
    return jira


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _build_redis_mock(checkpoints: dict[str, dict]) -> MagicMock:
    """Build a mock Redis client returning checkpoints keyed by Redis pattern.

    The checkpoint key format is ``langgraph:checkpoint:{ticket_key}``.
    The ``scan`` mock is pattern-aware so only matching keys are returned.
    """
    redis = MagicMock()

    key_map: dict[str, str] = {
        f"langgraph:checkpoint:{ticket_key}": json.dumps(state)
        for ticket_key, state in checkpoints.items()
    }

    async def _scan(cursor: int, match: str, count: int) -> tuple[int, list[str]]:
        if cursor == 0:
            prefix = match.rstrip("*")
            filtered = [k for k in key_map if k.startswith(prefix)]
            return (0, filtered)
        return (0, [])

    redis.scan = AsyncMock(side_effect=_scan)

    async def _get(key: str) -> str | None:
        return key_map.get(key)

    redis.get = AsyncMock(side_effect=_get)
    return redis


def _make_jira_issue(
    key: str,
    issue_type: str = "Task",
    summary: str = "",
    parent_key: str | None = None,
) -> JiraIssue:
    """Build a minimal JiraIssue for testing hierarchy resolution."""
    return JiraIssue(
        key=key,
        id="1",
        summary=summary or f"Summary of {key}",
        description="",
        status="In Progress",
        issue_type=issue_type,
        parent_key=parent_key,
    )


def _make_cli_args(
    project: str = "PROJ",
    days: int = 7,
    output: str | None = None,
    fmt: str = "text",
    create_ticket: bool = False,
    notify: bool = False,
) -> argparse.Namespace:
    """Create a minimal argparse.Namespace for cmd_weekly_report."""
    return argparse.Namespace(
        project=project,
        days=days,
        output=output,
        format=fmt,
        create_ticket=create_ticket,
        notify=notify,
    )


def _make_report(
    project: str = "PROJ",
    *,
    completed: list[TicketSummary] | None = None,
    in_progress: list[TicketSummary] | None = None,
    blocked: list[TicketSummary] | None = None,
) -> WeeklyReportData:
    """Build a WeeklyReportData for CLI testing."""
    if completed is None:
        completed = [
            TicketSummary(
                ticket_key=f"{project}-1",
                status="completed",
                duration_seconds=3600.0,
                input_tokens=1000,
                output_tokens=500,
            )
        ]
    ip = in_progress or []
    bl = blocked or []
    return WeeklyReportData(
        project=project,
        period_days=7,
        report_start=_THREE_DAYS_AGO,
        report_end=_ONE_DAY_AGO,
        completed_tickets=completed,
        in_progress_tickets=ip,
        blocked_tickets=bl,
        total_input_tokens=sum(t.input_tokens for t in completed + ip + bl),
        total_output_tokens=sum(t.output_tokens for t in completed + ip + bl),
        all_tickets=list(completed) + list(ip) + list(bl),
    )


# ---------------------------------------------------------------------------
# Section 1: test_collect_weekly_data_with_multiple_workflows
# ---------------------------------------------------------------------------


class TestCollectWeeklyDataWithMultipleWorkflows:
    """Verifies data aggregation from multiple checkpoints."""

    @pytest.mark.asyncio
    async def test_all_tickets_collected(self, mock_workflow_checkpoints):
        """All checkpoints within the window are included in all_tickets."""
        redis = _build_redis_mock(mock_workflow_checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert len(report.all_tickets) == 3

    @pytest.mark.asyncio
    async def test_completed_tickets_categorised(self, mock_workflow_checkpoints):
        """Completed tickets go into the completed_tickets list."""
        redis = _build_redis_mock(mock_workflow_checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert len(report.completed_tickets) == 1
        assert report.completed_tickets[0].ticket_key == "PROJ-1"

    @pytest.mark.asyncio
    async def test_in_progress_tickets_categorised(self, mock_workflow_checkpoints):
        """In-progress tickets go into the in_progress_tickets list."""
        redis = _build_redis_mock(mock_workflow_checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert len(report.in_progress_tickets) == 1
        assert report.in_progress_tickets[0].ticket_key == "PROJ-2"

    @pytest.mark.asyncio
    async def test_blocked_tickets_categorised(self, mock_workflow_checkpoints):
        """Blocked tickets go into the blocked_tickets list."""
        redis = _build_redis_mock(mock_workflow_checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert len(report.blocked_tickets) == 1
        assert report.blocked_tickets[0].ticket_key == "PROJ-3"

    @pytest.mark.asyncio
    async def test_token_totals_aggregated(self, mock_workflow_checkpoints):
        """Token counts are summed across all tickets."""
        redis = _build_redis_mock(mock_workflow_checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        # PROJ-1: prd(1200) + spec(800) = 2000 in; prd(2000) + spec(1500) = 3500 out
        # PROJ-2: 700 in, 900 out
        # PROJ-3: 3000 in, 4000 out
        assert report.total_input_tokens == 5700
        assert report.total_output_tokens == 8400

    @pytest.mark.asyncio
    async def test_project_field_set(self, mock_workflow_checkpoints):
        """The project field in the report matches the argument."""
        redis = _build_redis_mock(mock_workflow_checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert report.project == "PROJ"

    @pytest.mark.asyncio
    async def test_empty_data_returns_zero_counts(self):
        """When no checkpoints exist, all ticket lists are empty."""
        redis = _build_redis_mock({})
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert report.all_tickets == []
        assert report.completed_tickets == []
        assert report.in_progress_tickets == []
        assert report.blocked_tickets == []
        assert report.total_input_tokens == 0
        assert report.total_output_tokens == 0


# ---------------------------------------------------------------------------
# Section 2: test_collect_weekly_data_filters_by_date_range
# ---------------------------------------------------------------------------


class TestCollectWeeklyDataFiltersByDateRange:
    """Verifies time-window filtering."""

    @pytest.mark.asyncio
    async def test_recent_checkpoint_included(self):
        """A checkpoint updated 1 day ago is included in a 7-day window."""
        checkpoints = {
            "PROJ-10": _make_checkpoint(
                ticket_key="PROJ-10",
                updated_at=_ONE_DAY_AGO,
            )
        }
        redis = _build_redis_mock(checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert len(report.all_tickets) == 1
        assert report.all_tickets[0].ticket_key == "PROJ-10"

    @pytest.mark.asyncio
    async def test_old_checkpoint_excluded(self):
        """A checkpoint updated 10 days ago is excluded from a 7-day window."""
        old_checkpoint = _make_checkpoint(
            ticket_key="PROJ-20",
            updated_at=_TEN_DAYS_AGO,
            stage_timestamps={
                "prd": _make_stage(
                    "prd",
                    started_at=_TEN_DAYS_AGO,
                    ended_at=_TEN_DAYS_AGO,
                )
            },
        )
        checkpoints = {"PROJ-20": old_checkpoint}
        redis = _build_redis_mock(checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert report.all_tickets == []

    @pytest.mark.asyncio
    async def test_mixed_old_and_recent(self):
        """Only the recent checkpoint is returned when mixed ages are present."""
        checkpoints = {
            "PROJ-10": _make_checkpoint(
                ticket_key="PROJ-10",
                updated_at=_ONE_DAY_AGO,
            ),
            "PROJ-20": _make_checkpoint(
                ticket_key="PROJ-20",
                updated_at=_TEN_DAYS_AGO,
                stage_timestamps={
                    "prd": _make_stage(
                        "prd", started_at=_TEN_DAYS_AGO, ended_at=_TEN_DAYS_AGO
                    )
                },
            ),
        }
        redis = _build_redis_mock(checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert len(report.all_tickets) == 1
        assert report.all_tickets[0].ticket_key == "PROJ-10"

    @pytest.mark.asyncio
    async def test_stage_timestamp_qualifies_checkpoint(self):
        """A checkpoint qualifies by stage.started_at even if updated_at is old."""
        # updated_at is 10 days ago but a stage started_at is within the window
        checkpoint = _make_checkpoint(
            ticket_key="PROJ-30",
            updated_at=_TEN_DAYS_AGO,  # old top-level timestamp
            stage_timestamps={
                "prd": _make_stage(
                    "prd",
                    started_at=_ONE_DAY_AGO,  # recent stage timestamp qualifies it
                    ended_at=_ONE_DAY_AGO,
                )
            },
        )
        checkpoints = {"PROJ-30": checkpoint}
        redis = _build_redis_mock(checkpoints)
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert len(report.all_tickets) == 1
        assert report.all_tickets[0].ticket_key == "PROJ-30"


# ---------------------------------------------------------------------------
# Section 3: test_collect_weekly_data_filters_by_project
# ---------------------------------------------------------------------------


class TestCollectWeeklyDataFiltersByProject:
    """Verifies project scoping via Redis scan pattern."""

    @pytest.mark.asyncio
    async def test_only_matching_project_keys_returned(self):
        """Only checkpoints for project PROJ are returned, not OTHER."""
        proj_checkpoint = _make_checkpoint(ticket_key="PROJ-1")
        other_checkpoint = _make_checkpoint(ticket_key="OTHER-1")

        redis = MagicMock()
        key_map = {
            "langgraph:checkpoint:PROJ-1": json.dumps(proj_checkpoint),
            "langgraph:checkpoint:OTHER-1": json.dumps(other_checkpoint),
        }

        async def _scan(cursor: int, match: str, count: int) -> tuple[int, list[str]]:
            prefix = match.rstrip("*")
            filtered = [k for k in key_map if k.startswith(prefix)]
            return (0, filtered)

        async def _get(key: str) -> str | None:
            return key_map.get(key)

        redis.scan = AsyncMock(side_effect=_scan)
        redis.get = AsyncMock(side_effect=_get)

        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert len(report.all_tickets) == 1
        assert report.all_tickets[0].ticket_key == "PROJ-1"

    @pytest.mark.asyncio
    async def test_different_project_key_not_mixed_in(self):
        """Requesting OTHER project does not return PROJ tickets."""
        proj_checkpoint = _make_checkpoint(ticket_key="PROJ-1")
        other_checkpoint = _make_checkpoint(ticket_key="OTHER-1")

        redis = MagicMock()
        key_map = {
            "langgraph:checkpoint:PROJ-1": json.dumps(proj_checkpoint),
            "langgraph:checkpoint:OTHER-1": json.dumps(other_checkpoint),
        }

        async def _scan(cursor: int, match: str, count: int) -> tuple[int, list[str]]:
            prefix = match.rstrip("*")
            filtered = [k for k in key_map if k.startswith(prefix)]
            return (0, filtered)

        async def _get(key: str) -> str | None:
            return key_map.get(key)

        redis.scan = AsyncMock(side_effect=_scan)
        redis.get = AsyncMock(side_effect=_get)

        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("OTHER", days=7)

        assert len(report.all_tickets) == 1
        assert report.all_tickets[0].ticket_key == "OTHER-1"


# ---------------------------------------------------------------------------
# Section 4: test_feature_rollup_groups_correctly
# ---------------------------------------------------------------------------


class TestFeatureRollupGroupsCorrectly:
    """Verifies tickets are grouped by parent feature."""

    @pytest.mark.asyncio
    async def test_tickets_grouped_under_feature(self):
        """Tickets resolved to the same Feature are grouped into one rollup."""
        checkpoint_t1 = _make_checkpoint(ticket_key="PROJ-10")
        checkpoint_t2 = _make_checkpoint(ticket_key="PROJ-11")

        redis = _build_redis_mock({"PROJ-10": checkpoint_t1, "PROJ-11": checkpoint_t2})

        # Both tickets resolve to parent FEAT-1
        feature_issue = _make_jira_issue(
            "FEAT-1", issue_type="Feature", summary="My Feature"
        )
        task_issue_t1 = _make_jira_issue(
            "PROJ-10", issue_type="Task", parent_key="FEAT-1"
        )
        task_issue_t2 = _make_jira_issue(
            "PROJ-11", issue_type="Task", parent_key="FEAT-1"
        )

        issue_map = {
            "FEAT-1": feature_issue,
            "PROJ-10": task_issue_t1,
            "PROJ-11": task_issue_t2,
        }

        async def _get_issue(key: str) -> JiraIssue:
            return issue_map[key]

        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=_get_issue)

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert "FEAT-1" in report.feature_rollups
        rollup = report.feature_rollups["FEAT-1"]
        assert len(rollup.linked_tickets) == 2

    @pytest.mark.asyncio
    async def test_unresolvable_tickets_go_to_unassigned(self):
        """Tickets with no feature parent are placed in the Unassigned bucket."""
        checkpoint = _make_checkpoint(ticket_key="PROJ-50")
        redis = _build_redis_mock({"PROJ-50": checkpoint})

        # get_issue raises so no Feature can be resolved
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("Jira unavailable"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert UNASSIGNED_FEATURE_KEY in report.feature_rollups
        assert len(report.feature_rollups[UNASSIGNED_FEATURE_KEY].linked_tickets) == 1

    @pytest.mark.asyncio
    async def test_completion_percentage_computed(self):
        """completion_percentage is 50 % when 1 of 2 linked tickets is completed."""
        checkpoint_done = _make_checkpoint(
            ticket_key="PROJ-60", workflow_outcome="Completed"
        )
        checkpoint_wip = _make_checkpoint(ticket_key="PROJ-61", workflow_outcome=None)
        redis = _build_redis_mock(
            {"PROJ-60": checkpoint_done, "PROJ-61": checkpoint_wip}
        )

        feature_issue = _make_jira_issue("FEAT-2", issue_type="Feature")
        task_done = _make_jira_issue("PROJ-60", issue_type="Task", parent_key="FEAT-2")
        task_wip = _make_jira_issue("PROJ-61", issue_type="Task", parent_key="FEAT-2")

        issue_map = {
            "FEAT-2": feature_issue,
            "PROJ-60": task_done,
            "PROJ-61": task_wip,
        }

        async def _get_issue(key: str) -> JiraIssue:
            return issue_map[key]

        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=_get_issue)

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        rollup = report.feature_rollups.get("FEAT-2")
        assert rollup is not None
        assert rollup.completion_percentage == pytest.approx(50.0)

    @pytest.mark.asyncio
    async def test_empty_checkpoint_list_produces_no_rollups(self):
        """When there are no checkpoints, feature_rollups is an empty dict."""
        redis = _build_redis_mock({})
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("should not be called"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        assert report.feature_rollups == {}


# ---------------------------------------------------------------------------
# Section 5: test_cli_weekly_report_text_output
# ---------------------------------------------------------------------------


class TestCliWeeklyReportTextOutput:
    """Verifies CLI produces correct text output."""

    @pytest.mark.asyncio
    async def test_text_output_exits_zero(self, capsys):
        """forge weekly-report exits 0 when data is available."""
        from forge.cli import cmd_weekly_report

        report = _make_report()

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            code = await cmd_weekly_report(_make_cli_args(fmt="text"))

        assert code == 0

    @pytest.mark.asyncio
    async def test_text_output_contains_ticket_key(self, capsys):
        """Text output mentions the completed ticket key."""
        from forge.cli import cmd_weekly_report

        report = _make_report(project="PROJ")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(_make_cli_args(project="PROJ", fmt="text"))

        out = capsys.readouterr().out
        assert "PROJ-1" in out

    @pytest.mark.asyncio
    async def test_text_output_contains_project_name(self, capsys):
        """Text output includes the project name."""
        from forge.cli import cmd_weekly_report

        report = _make_report(project="MYPROJ")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(_make_cli_args(project="MYPROJ", fmt="text"))

        out = capsys.readouterr().out
        assert "MYPROJ" in out

    @pytest.mark.asyncio
    async def test_no_data_exits_nonzero(self, capsys):
        """forge weekly-report exits 1 when no tickets are found."""
        from forge.cli import cmd_weekly_report

        empty_report = WeeklyReportData(
            project="PROJ",
            period_days=7,
            report_start=_THREE_DAYS_AGO,
            report_end=_ONE_DAY_AGO,
        )

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=empty_report),
        ):
            code = await cmd_weekly_report(_make_cli_args())

        assert code == 1

    @pytest.mark.asyncio
    async def test_error_during_collection_exits_nonzero(self, capsys):
        """forge weekly-report exits 1 on collection errors."""
        from forge.cli import cmd_weekly_report

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(side_effect=RuntimeError("Redis unavailable")),
        ):
            code = await cmd_weekly_report(_make_cli_args())

        assert code == 1

    @pytest.mark.asyncio
    async def test_single_ticket_text_output(self, capsys):
        """A report with a single completed ticket produces text output."""
        from forge.cli import cmd_weekly_report

        report = _make_report(
            completed=[
                TicketSummary(
                    ticket_key="PROJ-1",
                    status="completed",
                    duration_seconds=1800.0,
                    input_tokens=500,
                    output_tokens=200,
                )
            ]
        )

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            code = await cmd_weekly_report(_make_cli_args(fmt="text"))

        assert code == 0
        out = capsys.readouterr().out
        assert "PROJ-1" in out

    @pytest.mark.asyncio
    async def test_no_completed_tickets_text_output(self, capsys):
        """A report with only in-progress tickets still exits 0."""
        from forge.cli import cmd_weekly_report

        report = _make_report(
            completed=[],
            in_progress=[
                TicketSummary(
                    ticket_key="PROJ-5",
                    status="in_progress",
                    input_tokens=200,
                    output_tokens=100,
                )
            ],
        )

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            code = await cmd_weekly_report(_make_cli_args(fmt="text"))

        assert code == 0


# ---------------------------------------------------------------------------
# Section 6: test_cli_weekly_report_json_output
# ---------------------------------------------------------------------------


class TestCliWeeklyReportJsonOutput:
    """Verifies JSON output is valid and complete."""

    @pytest.mark.asyncio
    async def test_json_output_is_valid(self, capsys):
        """--format json produces parseable JSON."""
        from forge.cli import cmd_weekly_report

        report = _make_report()

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            code = await cmd_weekly_report(_make_cli_args(fmt="json"))

        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_json_output_contains_required_fields(self, capsys):
        """JSON output contains the required top-level sections."""
        from forge.cli import cmd_weekly_report

        report = _make_report()

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(_make_cli_args(fmt="json"))

        out = capsys.readouterr().out
        data = json.loads(out)
        # Weekly JSON formatter has these mandatory top-level keys
        assert "project" in data
        assert "completed_tickets" in data
        assert "in_progress_tickets" in data
        assert "blocked_tickets" in data
        # Token totals are nested under 'summary'
        assert "summary" in data
        assert "total_input_tokens" in data["summary"]
        assert "total_output_tokens" in data["summary"]

    @pytest.mark.asyncio
    async def test_json_output_contains_ticket_keys(self, capsys):
        """JSON completed_tickets contains the ticket keys."""
        from forge.cli import cmd_weekly_report

        report = _make_report(project="PROJ")

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            await cmd_weekly_report(_make_cli_args(project="PROJ", fmt="json"))

        out = capsys.readouterr().out
        data = json.loads(out)
        ticket_keys = [t["ticket_key"] for t in data["completed_tickets"]]
        assert "PROJ-1" in ticket_keys

    @pytest.mark.asyncio
    async def test_json_output_empty_completed(self, capsys):
        """JSON output is still valid when completed_tickets is empty."""
        from forge.cli import cmd_weekly_report

        report = _make_report(
            completed=[],
            in_progress=[TicketSummary(ticket_key="PROJ-5", status="in_progress")],
        )

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            code = await cmd_weekly_report(_make_cli_args(fmt="json"))

        assert code == 0
        out = capsys.readouterr().out
        data = json.loads(out)
        assert data["completed_tickets"] == []


# ---------------------------------------------------------------------------
# Section 7: test_cli_weekly_report_file_export
# ---------------------------------------------------------------------------


class TestCliWeeklyReportFileExport:
    """Verifies file export works."""

    @pytest.mark.asyncio
    async def test_file_export_creates_file(self):
        """--output writes the report to disk."""
        from forge.cli import cmd_weekly_report

        report = _make_report()

        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = str(Path(tmpdir) / "report.txt")
            with patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new=AsyncMock(return_value=report),
            ):
                code = await cmd_weekly_report(
                    _make_cli_args(fmt="text", output=outfile)
                )

            assert code == 0
            assert Path(outfile).exists()

    @pytest.mark.asyncio
    async def test_file_export_contains_project_name(self):
        """The exported file content includes the project name."""
        from forge.cli import cmd_weekly_report

        report = _make_report(project="MYPROJ")

        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = str(Path(tmpdir) / "report.txt")
            with patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new=AsyncMock(return_value=report),
            ):
                await cmd_weekly_report(
                    _make_cli_args(project="MYPROJ", fmt="text", output=outfile)
                )

            content = Path(outfile).read_text()
            assert "MYPROJ" in content

    @pytest.mark.asyncio
    async def test_file_export_json_format(self):
        """File export with --format json writes valid JSON."""
        from forge.cli import cmd_weekly_report

        report = _make_report()

        with tempfile.TemporaryDirectory() as tmpdir:
            outfile = str(Path(tmpdir) / "report.json")
            with patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new=AsyncMock(return_value=report),
            ):
                code = await cmd_weekly_report(
                    _make_cli_args(fmt="json", output=outfile)
                )

            assert code == 0
            content = Path(outfile).read_text()
            data = json.loads(content)
            assert "project" in data

    @pytest.mark.asyncio
    async def test_file_export_invalid_path_exits_nonzero(self, capsys):
        """Writing to a non-existent directory exits 1."""
        from forge.cli import cmd_weekly_report

        report = _make_report()

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new=AsyncMock(return_value=report),
        ):
            code = await cmd_weekly_report(
                _make_cli_args(fmt="text", output="/nonexistent/dir/report.txt")
            )

        assert code == 1


# ---------------------------------------------------------------------------
# Section 8: test_report_ticket_creation
# ---------------------------------------------------------------------------


class TestReportTicketCreation:
    """Verifies Jira ticket is created with correct fields."""

    @pytest.mark.asyncio
    async def test_ticket_created_with_correct_summary(self):
        """create_report_ticket uses the expected summary format."""
        from datetime import date

        from forge.workflow.stats.report_ticket import create_report_ticket

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.create_task = AsyncMock(return_value="PROJ-99")

        week_start = date(2024, 1, 8)

        with patch(
            "forge.workflow.stats.report_ticket.JiraClient",
            return_value=mock_jira,
        ):
            key = await create_report_ticket("PROJ", week_start, "## Report")

        assert key == "PROJ-99"
        call_kwargs = mock_jira.create_task.call_args.kwargs
        assert "Forge Weekly Report" in call_kwargs["summary"]
        assert "PROJ" in call_kwargs["summary"]
        assert "2024-01-08" in call_kwargs["summary"]

    @pytest.mark.asyncio
    async def test_ticket_created_with_required_labels(self):
        """Report ticket is created with both required labels."""
        from datetime import date

        from forge.workflow.stats.report_ticket import create_report_ticket

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.create_task = AsyncMock(return_value="PROJ-99")

        with patch(
            "forge.workflow.stats.report_ticket.JiraClient",
            return_value=mock_jira,
        ):
            await create_report_ticket("PROJ", date(2024, 1, 8), "## Report")

        call_kwargs = mock_jira.create_task.call_args.kwargs
        assert "forge:weekly-report" in call_kwargs["labels"]
        assert "forge:generated" in call_kwargs["labels"]

    @pytest.mark.asyncio
    async def test_ticket_created_with_report_content(self):
        """The report markdown is passed as the description."""
        from datetime import date

        from forge.workflow.stats.report_ticket import create_report_ticket

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.create_task = AsyncMock(return_value="PROJ-99")

        report_md = "## Weekly Report\n\nSome content here."

        with patch(
            "forge.workflow.stats.report_ticket.JiraClient",
            return_value=mock_jira,
        ):
            await create_report_ticket("PROJ", date(2024, 1, 8), report_md)

        call_kwargs = mock_jira.create_task.call_args.kwargs
        assert call_kwargs["description"] == report_md

    @pytest.mark.asyncio
    async def test_jira_client_closed_after_creation(self):
        """JiraClient.close() is always called after ticket creation."""
        from datetime import date

        from forge.workflow.stats.report_ticket import create_report_ticket

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.create_task = AsyncMock(return_value="PROJ-99")

        with patch(
            "forge.workflow.stats.report_ticket.JiraClient",
            return_value=mock_jira,
        ):
            await create_report_ticket("PROJ", date(2024, 1, 8), "## Report")

        mock_jira.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Section 9: test_report_ticket_update_idempotency
# ---------------------------------------------------------------------------


class TestReportTicketUpdateIdempotency:
    """Verifies updating existing ticket works and is idempotent."""

    @pytest.mark.asyncio
    async def test_existing_ticket_is_updated_not_recreated(self):
        """ensure_report_ticket updates the description instead of creating a new ticket."""
        from datetime import date

        from forge.integrations.jira.models import JiraIssue
        from forge.workflow.stats.report_ticket import ensure_report_ticket

        existing_ticket = JiraIssue(
            key="PROJ-42",
            id="100",
            summary="Forge Weekly Report - PROJ - Week of 2024-01-08",
            description="",
            status="Open",
            issue_type="Task",
        )

        mock_jira_resolve = MagicMock()
        mock_jira_resolve.close = AsyncMock()
        mock_jira_resolve.search_issues = AsyncMock(return_value=[existing_ticket])

        mock_jira_update = MagicMock()
        mock_jira_update.close = AsyncMock()
        mock_jira_update.update_description = AsyncMock()

        jira_instances = iter([mock_jira_resolve, mock_jira_update])

        with patch(
            "forge.workflow.stats.report_ticket.JiraClient",
            side_effect=jira_instances,
        ):
            ticket_key = await ensure_report_ticket(
                "PROJ", date(2024, 1, 8), "## Report content"
            )

        assert ticket_key == "PROJ-42"
        mock_jira_resolve.search_issues.assert_awaited_once()
        mock_jira_update.update_description.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_new_ticket_created_when_not_found(self):
        """ensure_report_ticket creates a new ticket when none exists."""
        from datetime import date

        from forge.workflow.stats.report_ticket import ensure_report_ticket

        mock_jira_search = MagicMock()
        mock_jira_search.close = AsyncMock()
        mock_jira_search.search_issues = AsyncMock(return_value=[])

        mock_jira_create = MagicMock()
        mock_jira_create.close = AsyncMock()
        mock_jira_create.create_task = AsyncMock(return_value="PROJ-100")

        # The update call after create
        mock_jira_update = MagicMock()
        mock_jira_update.close = AsyncMock()
        mock_jira_update.update_description = AsyncMock()

        jira_instances = iter([mock_jira_search, mock_jira_create, mock_jira_update])

        with patch(
            "forge.workflow.stats.report_ticket.JiraClient",
            side_effect=jira_instances,
        ):
            ticket_key = await ensure_report_ticket(
                "PROJ", date(2024, 1, 8), "## New report"
            )

        assert ticket_key == "PROJ-100"
        mock_jira_create.create_task.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_called_with_correct_content(self):
        """update_report_ticket passes the correct markdown to Jira."""
        from forge.workflow.stats.report_ticket import update_report_ticket

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.update_description = AsyncMock()

        report_md = "# Updated Weekly Report\n\nNew content."

        with patch(
            "forge.workflow.stats.report_ticket.JiraClient",
            return_value=mock_jira,
        ):
            await update_report_ticket("PROJ-42", report_md)

        mock_jira.update_description.assert_awaited_once_with("PROJ-42", report_md)

    @pytest.mark.asyncio
    async def test_calling_twice_does_not_create_duplicate(self):
        """Calling ensure_report_ticket a second time updates, not creates."""
        from datetime import date

        from forge.integrations.jira.models import JiraIssue
        from forge.workflow.stats.report_ticket import ensure_report_ticket

        existing_ticket = JiraIssue(
            key="PROJ-42",
            id="100",
            summary="Forge Weekly Report - PROJ - Week of 2024-01-08",
            description="",
            status="Open",
            issue_type="Task",
        )

        create_task_mock = AsyncMock(return_value="PROJ-NEW")
        update_desc_mock = AsyncMock()
        search_mock = AsyncMock(return_value=[existing_ticket])

        def _make_jira() -> MagicMock:
            m = MagicMock()
            m.close = AsyncMock()
            m.search_issues = search_mock
            m.create_task = create_task_mock
            m.update_description = update_desc_mock
            return m

        with patch(
            "forge.workflow.stats.report_ticket.JiraClient",
            side_effect=_make_jira,
        ):
            key1 = await ensure_report_ticket("PROJ", date(2024, 1, 8), "v1")
            key2 = await ensure_report_ticket("PROJ", date(2024, 1, 8), "v2")

        # No create_task should have been called since the ticket already exists
        create_task_mock.assert_not_awaited()
        # Both calls updated the description
        assert update_desc_mock.await_count == 2
        assert key1 == "PROJ-42"
        assert key2 == "PROJ-42"

    @pytest.mark.asyncio
    async def test_missing_stats_fields_handled_gracefully(self):
        """Checkpoints with missing optional stats fields still produce TicketSummary."""
        # A checkpoint that has stage_timestamps present but with missing optional fields
        checkpoint = {
            "ticket_key": "PROJ-70",
            "ticket_type": "Feature",
            "stage_timestamps": {
                "prd": {
                    "stage_name": "prd",
                    # input_tokens, output_tokens, etc. intentionally absent
                    "started_at": _ONE_DAY_AGO,
                    "ended_at": _ONE_DAY_AGO,
                }
            },
            # workflow_outcome, stats_ci_cycles, is_blocked intentionally absent
            "updated_at": _ONE_DAY_AGO,
        }
        redis = _build_redis_mock({"PROJ-70": checkpoint})
        jira = MagicMock()
        jira.close = AsyncMock()
        jira.get_issue = AsyncMock(side_effect=Exception("hierarchy not needed"))

        with (
            patch(
                "forge.workflow.stats.weekly_report.get_redis_client",
                new=AsyncMock(return_value=redis),
            ),
            patch(
                "forge.workflow.stats.weekly_report.JiraClient",
                return_value=jira,
            ),
        ):
            report = await collect_weekly_data("PROJ", days=7)

        # Should still parse without crashing; tokens default to 0
        assert len(report.all_tickets) == 1
        ticket = report.all_tickets[0]
        assert ticket.ticket_key == "PROJ-70"
        assert ticket.input_tokens == 0
        assert ticket.output_tokens == 0


# ---------------------------------------------------------------------------
# Section 10: test_notification_delivery
# ---------------------------------------------------------------------------


class TestNotificationDelivery:
    """Verifies notification comment is posted."""

    @pytest.mark.asyncio
    async def test_notification_comment_posted(self):
        """notify_report_ready posts a comment to the Jira ticket."""
        from forge.workflow.stats.notifications import notify_report_ready

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.add_comment = AsyncMock()

        with patch(
            "forge.workflow.stats.notifications.JiraClient",
            return_value=mock_jira,
        ):
            await notify_report_ready(
                "PROJ-42",
                ["user1", "user2"],
                jira_base_url="https://test.atlassian.net",
            )

        mock_jira.add_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notification_posted_to_correct_ticket(self):
        """notify_report_ready posts the comment to the specified ticket key."""
        from forge.workflow.stats.notifications import notify_report_ready

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.add_comment = AsyncMock()

        with patch(
            "forge.workflow.stats.notifications.JiraClient",
            return_value=mock_jira,
        ):
            await notify_report_ready(
                "PROJ-99",
                ["user1"],
                jira_base_url="https://test.atlassian.net",
            )

        call_args = mock_jira.add_comment.call_args
        ticket_arg = call_args[0][0]
        assert ticket_arg == "PROJ-99"

    @pytest.mark.asyncio
    async def test_notification_comment_mentions_recipients(self):
        """The notification comment body mentions each recipient."""
        from forge.workflow.stats.notifications import notify_report_ready

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.add_comment = AsyncMock()

        with patch(
            "forge.workflow.stats.notifications.JiraClient",
            return_value=mock_jira,
        ):
            await notify_report_ready(
                "PROJ-42",
                ["abc123", "def456"],
                jira_base_url="https://test.atlassian.net",
            )

        call_args = mock_jira.add_comment.call_args
        comment_body = call_args[0][1]
        assert "abc123" in comment_body
        assert "def456" in comment_body

    @pytest.mark.asyncio
    async def test_no_notification_for_empty_recipients(self):
        """notify_report_ready does not post when recipients list is empty."""
        from forge.workflow.stats.notifications import notify_report_ready

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.add_comment = AsyncMock()

        with patch(
            "forge.workflow.stats.notifications.JiraClient",
            return_value=mock_jira,
        ):
            await notify_report_ready(
                "PROJ-42",
                [],
                jira_base_url="https://test.atlassian.net",
            )

        mock_jira.add_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_jira_client_closed_after_notification(self):
        """JiraClient.close() is always called after notification delivery."""
        from forge.workflow.stats.notifications import notify_report_ready

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.add_comment = AsyncMock()

        with patch(
            "forge.workflow.stats.notifications.JiraClient",
            return_value=mock_jira,
        ):
            await notify_report_ready(
                "PROJ-42",
                ["user1"],
                jira_base_url="https://test.atlassian.net",
            )

        mock_jira.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_notification_comment_includes_ticket_link(self):
        """The notification comment body includes a link to the report ticket."""
        from forge.workflow.stats.notifications import notify_report_ready

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.add_comment = AsyncMock()

        with patch(
            "forge.workflow.stats.notifications.JiraClient",
            return_value=mock_jira,
        ):
            await notify_report_ready(
                "PROJ-42",
                ["user1"],
                jira_base_url="https://test.atlassian.net",
            )

        call_args = mock_jira.add_comment.call_args
        comment_body = call_args[0][1]
        assert "PROJ-42" in comment_body

    @pytest.mark.asyncio
    async def test_invalid_account_ids_are_skipped(self):
        """Account IDs containing spaces or commas are skipped with a warning."""
        from forge.workflow.stats.notifications import notify_report_ready

        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()
        mock_jira.add_comment = AsyncMock()

        with patch(
            "forge.workflow.stats.notifications.JiraClient",
            return_value=mock_jira,
        ):
            # "bad id" has a space and "another,bad" has a comma — both invalid
            await notify_report_ready(
                "PROJ-42",
                ["bad id", "another,bad"],
                jira_base_url="https://test.atlassian.net",
            )

        # All recipients are invalid so no comment is posted
        mock_jira.add_comment.assert_not_awaited()
