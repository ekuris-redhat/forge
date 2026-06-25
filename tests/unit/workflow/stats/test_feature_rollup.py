"""Unit tests for per-Feature rollup aggregation in weekly_report.

All Jira API calls are mocked via AsyncMock so no real HTTP requests are made.

Coverage:
- FeatureRollup dataclass: construction, defaults, field semantics
- UNASSIGNED_FEATURE_KEY sentinel
- _resolve_feature_key: direct-Feature parent, Epic→Feature chain, no parent,
  Jira errors, ticket-is-Feature edge case
- _build_feature_rollup: token sums, duration, counts, completion_percentage
- _group_by_feature: grouping, unassigned bucket, mixed groups, empty input,
  feature summary fetching, Jira errors during summary fetch
- WeeklyReportData: feature_rollups field present and defaults to {}
- collect_weekly_data: feature_rollups populated when jira_client injected
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.integrations.jira.models import JiraIssue
from forge.workflow.stats.weekly_report import (
    UNASSIGNED_FEATURE_KEY,
    FeatureRollup,
    TicketSummary,
    WeeklyReportData,
    _build_feature_rollup,
    _group_by_feature,
    _resolve_feature_key,
    collect_weekly_data,
)

_NOW = datetime.now(UTC)
_ONE_DAY_AGO = (_NOW - timedelta(days=1)).isoformat()


def _make_issue(
    key: str,
    issue_type: str = "Task",
    summary: str = "",
    parent_key: str | None = None,
) -> JiraIssue:
    return JiraIssue(
        key=key,
        id="123",
        summary=summary or f"Summary of {key}",
        description="",
        status="In Progress",
        issue_type=issue_type,
        parent_key=parent_key,
    )


def _make_ticket(
    key: str = "AISOS-100",
    status: str = "in_progress",
    input_tokens: int = 100,
    output_tokens: int = 50,
    duration_seconds: float | None = None,
) -> TicketSummary:
    return TicketSummary(
        ticket_key=key,
        ticket_type="Feature",
        status=status,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        duration_seconds=duration_seconds,
    )


def _make_stage_data(
    *,
    stage_name: str = "prd",
    started_at: str | None = None,
    ended_at: str | None = None,
    input_tokens: int = 500,
    output_tokens: int = 250,
) -> dict:
    if started_at is None:
        started_at = _ONE_DAY_AGO
    return {
        "stage_name": stage_name,
        "iteration_count": 1,
        "machine_time_seconds": 120.0,
        "human_time_seconds": 0.0,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "started_at": started_at,
        "ended_at": ended_at,
    }


def _make_state(
    ticket_key: str = "AISOS-100",
    workflow_outcome: str | None = "Completed",
    updated_at: str | None = None,
) -> dict:
    if updated_at is None:
        updated_at = _ONE_DAY_AGO
    return {
        "ticket_key": ticket_key,
        "ticket_type": "Feature",
        "workflow_outcome": workflow_outcome,
        "is_blocked": False,
        "stage_timestamps": {
            "prd": _make_stage_data(started_at=_ONE_DAY_AGO, ended_at=_ONE_DAY_AGO),
        },
        "stats_ci_cycles": 0,
        "updated_at": updated_at,
    }


# ---------------------------------------------------------------------------
# FeatureRollup dataclass
# ---------------------------------------------------------------------------


class TestFeatureRollupDataclass:
    def test_required_field_feature_key(self) -> None:
        rollup = FeatureRollup(feature_key="AISOS-10")
        assert rollup.feature_key == "AISOS-10"

    def test_default_feature_summary_empty(self) -> None:
        rollup = FeatureRollup(feature_key="AISOS-10")
        assert rollup.feature_summary == ""

    def test_default_linked_tickets_empty(self) -> None:
        rollup = FeatureRollup(feature_key="AISOS-10")
        assert rollup.linked_tickets == []

    def test_default_token_counts_zero(self) -> None:
        rollup = FeatureRollup(feature_key="AISOS-10")
        assert rollup.total_input_tokens == 0
        assert rollup.total_output_tokens == 0

    def test_default_total_duration_none(self) -> None:
        rollup = FeatureRollup(feature_key="AISOS-10")
        assert rollup.total_duration is None

    def test_default_ticket_counts_zero(self) -> None:
        rollup = FeatureRollup(feature_key="AISOS-10")
        assert rollup.tickets_completed == 0
        assert rollup.tickets_in_progress == 0

    def test_default_completion_percentage_zero(self) -> None:
        rollup = FeatureRollup(feature_key="AISOS-10")
        assert rollup.completion_percentage == 0.0

    def test_all_fields_set_explicitly(self) -> None:
        t = _make_ticket("AISOS-1", status="completed")
        rollup = FeatureRollup(
            feature_key="AISOS-10",
            feature_summary="My Feature",
            linked_tickets=[t],
            total_input_tokens=500,
            total_output_tokens=250,
            total_duration=3600.0,
            tickets_completed=1,
            tickets_in_progress=0,
            completion_percentage=100.0,
        )
        assert rollup.feature_key == "AISOS-10"
        assert rollup.feature_summary == "My Feature"
        assert len(rollup.linked_tickets) == 1
        assert rollup.total_input_tokens == 500
        assert rollup.total_output_tokens == 250
        assert rollup.total_duration == 3600.0
        assert rollup.tickets_completed == 1
        assert rollup.tickets_in_progress == 0
        assert rollup.completion_percentage == 100.0

    def test_mutable_defaults_are_independent(self) -> None:
        r1 = FeatureRollup(feature_key="AISOS-10")
        r2 = FeatureRollup(feature_key="AISOS-20")
        r1.linked_tickets.append(_make_ticket())
        assert r2.linked_tickets == []

    def test_unassigned_sentinel_value(self) -> None:
        assert UNASSIGNED_FEATURE_KEY == "Unassigned"
        rollup = FeatureRollup(feature_key=UNASSIGNED_FEATURE_KEY)
        assert rollup.feature_key == "Unassigned"


# ---------------------------------------------------------------------------
# WeeklyReportData.feature_rollups field
# ---------------------------------------------------------------------------


class TestWeeklyReportDataFeatureRollups:
    def test_feature_rollups_defaults_to_empty_dict(self) -> None:
        report = WeeklyReportData(project="AISOS")
        assert report.feature_rollups == {}

    def test_feature_rollups_can_be_set(self) -> None:
        rollup = FeatureRollup(feature_key="AISOS-10")
        report = WeeklyReportData(
            project="AISOS",
            feature_rollups={"AISOS-10": rollup},
        )
        assert "AISOS-10" in report.feature_rollups
        assert report.feature_rollups["AISOS-10"] is rollup

    def test_feature_rollups_mutable_defaults_are_independent(self) -> None:
        r1 = WeeklyReportData(project="A")
        r2 = WeeklyReportData(project="B")
        r1.feature_rollups["AISOS-10"] = FeatureRollup(feature_key="AISOS-10")
        assert r2.feature_rollups == {}


# ---------------------------------------------------------------------------
# _build_feature_rollup
# ---------------------------------------------------------------------------


class TestBuildFeatureRollup:
    def test_empty_ticket_list(self) -> None:
        rollup = _build_feature_rollup("AISOS-10", "My Feature", [])
        assert rollup.feature_key == "AISOS-10"
        assert rollup.feature_summary == "My Feature"
        assert rollup.linked_tickets == []
        assert rollup.total_input_tokens == 0
        assert rollup.total_output_tokens == 0
        assert rollup.total_duration is None
        assert rollup.tickets_completed == 0
        assert rollup.tickets_in_progress == 0
        assert rollup.completion_percentage == 0.0

    def test_token_sums(self) -> None:
        tickets = [
            _make_ticket("T-1", input_tokens=100, output_tokens=50),
            _make_ticket("T-2", input_tokens=200, output_tokens=80),
        ]
        rollup = _build_feature_rollup("AISOS-10", "", tickets)
        assert rollup.total_input_tokens == 300
        assert rollup.total_output_tokens == 130

    def test_total_duration_sums_non_none(self) -> None:
        tickets = [
            _make_ticket("T-1", duration_seconds=100.0),
            _make_ticket("T-2", duration_seconds=200.0),
            _make_ticket("T-3", duration_seconds=None),
        ]
        rollup = _build_feature_rollup("AISOS-10", "", tickets)
        assert rollup.total_duration == 300.0

    def test_total_duration_none_when_all_none(self) -> None:
        tickets = [
            _make_ticket("T-1", duration_seconds=None),
            _make_ticket("T-2", duration_seconds=None),
        ]
        rollup = _build_feature_rollup("AISOS-10", "", tickets)
        assert rollup.total_duration is None

    def test_ticket_status_counts(self) -> None:
        tickets = [
            _make_ticket("T-1", status="completed"),
            _make_ticket("T-2", status="completed"),
            _make_ticket("T-3", status="in_progress"),
            _make_ticket("T-4", status="blocked"),
        ]
        rollup = _build_feature_rollup("AISOS-10", "", tickets)
        assert rollup.tickets_completed == 2
        assert rollup.tickets_in_progress == 1

    def test_completion_percentage_all_done(self) -> None:
        tickets = [
            _make_ticket("T-1", status="completed"),
            _make_ticket("T-2", status="completed"),
        ]
        rollup = _build_feature_rollup("AISOS-10", "", tickets)
        assert rollup.completion_percentage == 100.0

    def test_completion_percentage_partial(self) -> None:
        tickets = [
            _make_ticket("T-1", status="completed"),
            _make_ticket("T-2", status="in_progress"),
            _make_ticket("T-3", status="in_progress"),
            _make_ticket("T-4", status="in_progress"),
        ]
        rollup = _build_feature_rollup("AISOS-10", "", tickets)
        assert rollup.completion_percentage == 25.0

    def test_completion_percentage_zero_when_no_tickets(self) -> None:
        rollup = _build_feature_rollup("AISOS-10", "", [])
        assert rollup.completion_percentage == 0.0

    def test_linked_tickets_is_copy(self) -> None:
        tickets = [_make_ticket("T-1")]
        rollup = _build_feature_rollup("AISOS-10", "", tickets)
        # modifying original list should not affect rollup
        tickets.append(_make_ticket("T-2"))
        assert len(rollup.linked_tickets) == 1


# ---------------------------------------------------------------------------
# _resolve_feature_key
# ---------------------------------------------------------------------------


class TestResolveFeatureKey:
    @pytest.mark.asyncio
    async def test_ticket_is_feature_returns_own_key(self) -> None:
        jira = MagicMock()
        jira.get_issue = AsyncMock(return_value=_make_issue("AISOS-10", issue_type="Feature"))
        ticket = _make_ticket("AISOS-10")
        result = await _resolve_feature_key(ticket, jira)
        assert result == "AISOS-10"

    @pytest.mark.asyncio
    async def test_direct_feature_parent(self) -> None:
        # Task → Feature
        task_issue = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-10")
        feature_issue = _make_issue("AISOS-10", issue_type="Feature")
        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=[task_issue, feature_issue])
        ticket = _make_ticket("AISOS-50")
        result = await _resolve_feature_key(ticket, jira)
        assert result == "AISOS-10"

    @pytest.mark.asyncio
    async def test_epic_to_feature_chain(self) -> None:
        # Task → Epic → Feature
        task_issue = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-20")
        epic_issue = _make_issue("AISOS-20", issue_type="Epic", parent_key="AISOS-10")
        feature_issue = _make_issue("AISOS-10", issue_type="Feature")
        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=[task_issue, epic_issue, feature_issue])
        ticket = _make_ticket("AISOS-50")
        result = await _resolve_feature_key(ticket, jira)
        assert result == "AISOS-10"

    @pytest.mark.asyncio
    async def test_no_parent_returns_none(self) -> None:
        task_issue = _make_issue("AISOS-50", issue_type="Task", parent_key=None)
        jira = MagicMock()
        jira.get_issue = AsyncMock(return_value=task_issue)
        ticket = _make_ticket("AISOS-50")
        result = await _resolve_feature_key(ticket, jira)
        assert result is None

    @pytest.mark.asyncio
    async def test_epic_without_feature_parent_returns_none(self) -> None:
        # Task → Epic (no grandparent)
        task_issue = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-20")
        epic_issue = _make_issue("AISOS-20", issue_type="Epic", parent_key=None)
        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=[task_issue, epic_issue])
        ticket = _make_ticket("AISOS-50")
        result = await _resolve_feature_key(ticket, jira)
        assert result is None

    @pytest.mark.asyncio
    async def test_epic_grandparent_not_feature_returns_none(self) -> None:
        # Task → Epic → Epic (not a Feature)
        task_issue = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-20")
        epic_issue = _make_issue("AISOS-20", issue_type="Epic", parent_key="AISOS-10")
        other_issue = _make_issue("AISOS-10", issue_type="Epic")
        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=[task_issue, epic_issue, other_issue])
        ticket = _make_ticket("AISOS-50")
        result = await _resolve_feature_key(ticket, jira)
        assert result is None

    @pytest.mark.asyncio
    async def test_jira_error_returns_none(self) -> None:
        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=Exception("network error"))
        ticket = _make_ticket("AISOS-50")
        result = await _resolve_feature_key(ticket, jira)
        assert result is None

    @pytest.mark.asyncio
    async def test_jira_error_on_parent_fetch_returns_none(self) -> None:
        # First call succeeds, second call (parent fetch) raises
        task_issue = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-20")
        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=[task_issue, Exception("parent not found")])
        ticket = _make_ticket("AISOS-50")
        result = await _resolve_feature_key(ticket, jira)
        assert result is None


# ---------------------------------------------------------------------------
# _group_by_feature
# ---------------------------------------------------------------------------


class TestGroupByFeature:
    @pytest.mark.asyncio
    async def test_empty_tickets_returns_empty_dict(self) -> None:
        jira = MagicMock()
        result = await _group_by_feature([], jira)
        assert result == {}

    @pytest.mark.asyncio
    async def test_all_tickets_resolved_to_same_feature(self) -> None:
        feature_issue = _make_issue("AISOS-10", issue_type="Feature", summary="Feature Alpha")
        # Each ticket: Task → Feature
        side_effects = []
        for i in range(3):
            # get_issue for the ticket itself
            side_effects.append(
                _make_issue(f"AISOS-{50 + i}", issue_type="Task", parent_key="AISOS-10")
            )
            # get_issue for parent (Feature)
            side_effects.append(feature_issue)
        # One extra call to fetch Feature summary
        side_effects.append(feature_issue)

        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=side_effects)

        tickets = [_make_ticket(f"AISOS-{50 + i}") for i in range(3)]
        result = await _group_by_feature(tickets, jira)

        assert len(result) == 1
        assert "AISOS-10" in result
        rollup = result["AISOS-10"]
        assert len(rollup.linked_tickets) == 3
        assert rollup.feature_key == "AISOS-10"

    @pytest.mark.asyncio
    async def test_unresolved_tickets_go_to_unassigned(self) -> None:
        # All tickets have no parent → unassigned
        jira = MagicMock()
        jira.get_issue = AsyncMock(
            return_value=_make_issue("AISOS-50", issue_type="Task", parent_key=None)
        )
        tickets = [_make_ticket("AISOS-50"), _make_ticket("AISOS-51")]
        result = await _group_by_feature(tickets, jira)

        assert UNASSIGNED_FEATURE_KEY in result
        assert len(result[UNASSIGNED_FEATURE_KEY].linked_tickets) == 2

    @pytest.mark.asyncio
    async def test_mixed_resolved_and_unassigned(self) -> None:
        feature_issue = _make_issue("AISOS-10", issue_type="Feature", summary="Feature A")

        # Ticket AISOS-50: Task → Feature AISOS-10
        t50_task = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-10")
        # Ticket AISOS-51: Task → no parent (unassigned)
        t51_task = _make_issue("AISOS-51", issue_type="Task", parent_key=None)

        async def _side_effect(key: str) -> JiraIssue:
            if key == "AISOS-50":
                return t50_task
            elif key == "AISOS-51":
                return t51_task
            else:
                return feature_issue  # AISOS-10 (parent check + summary fetch)

        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=_side_effect)

        tickets = [_make_ticket("AISOS-50"), _make_ticket("AISOS-51")]
        result = await _group_by_feature(tickets, jira)

        assert "AISOS-10" in result
        assert UNASSIGNED_FEATURE_KEY in result
        assert len(result["AISOS-10"].linked_tickets) == 1
        assert len(result[UNASSIGNED_FEATURE_KEY].linked_tickets) == 1

    @pytest.mark.asyncio
    async def test_multiple_distinct_features(self) -> None:
        feature_a = _make_issue("AISOS-10", issue_type="Feature", summary="Feature A")
        feature_b = _make_issue("AISOS-11", issue_type="Feature", summary="Feature B")

        t1 = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-10")
        t2 = _make_issue("AISOS-51", issue_type="Task", parent_key="AISOS-11")

        side_effects = [
            t1,  # get_issue(AISOS-50)
            feature_a,  # parent of AISOS-50
            t2,  # get_issue(AISOS-51)
            feature_b,  # parent of AISOS-51
            feature_a,  # summary fetch for AISOS-10
            feature_b,  # summary fetch for AISOS-11
        ]
        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=side_effects)

        tickets = [_make_ticket("AISOS-50"), _make_ticket("AISOS-51")]
        result = await _group_by_feature(tickets, jira)

        assert set(result.keys()) == {"AISOS-10", "AISOS-11"}
        assert len(result["AISOS-10"].linked_tickets) == 1
        assert len(result["AISOS-11"].linked_tickets) == 1

    @pytest.mark.asyncio
    async def test_feature_summary_fetched(self) -> None:
        feature_issue = _make_issue("AISOS-10", issue_type="Feature", summary="My Feature")
        task_issue = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-10")

        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=[task_issue, feature_issue, feature_issue])

        tickets = [_make_ticket("AISOS-50")]
        result = await _group_by_feature(tickets, jira)

        assert result["AISOS-10"].feature_summary == "My Feature"

    @pytest.mark.asyncio
    async def test_feature_summary_empty_on_jira_error(self) -> None:
        # First resolve succeeds: AISOS-50 → AISOS-10 (Feature)
        feature_issue = _make_issue("AISOS-10", issue_type="Feature")
        task_issue = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-10")

        call_count = 0

        async def _side_effect(_key: str) -> JiraIssue:
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return task_issue
            elif call_count == 2:
                return feature_issue  # parent check
            else:
                raise Exception("summary fetch failed")

        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=_side_effect)

        tickets = [_make_ticket("AISOS-50")]
        result = await _group_by_feature(tickets, jira)

        assert "AISOS-10" in result
        assert result["AISOS-10"].feature_summary == ""

    @pytest.mark.asyncio
    async def test_unassigned_group_has_empty_summary(self) -> None:
        jira = MagicMock()
        jira.get_issue = AsyncMock(
            return_value=_make_issue("AISOS-50", issue_type="Task", parent_key=None)
        )
        tickets = [_make_ticket("AISOS-50")]
        result = await _group_by_feature(tickets, jira)

        assert result[UNASSIGNED_FEATURE_KEY].feature_summary == ""

    @pytest.mark.asyncio
    async def test_feature_summary_fetched_once_per_key(self) -> None:
        """Feature summary should be fetched only once even when multiple
        tickets resolve to the same Feature."""
        feature_issue = _make_issue("AISOS-10", issue_type="Feature", summary="F")
        task_a = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-10")
        task_b = _make_issue("AISOS-51", issue_type="Task", parent_key="AISOS-10")

        get_issue_calls: list[str] = []

        async def _tracked(key: str) -> JiraIssue:
            get_issue_calls.append(key)
            if key == "AISOS-50":
                return task_a
            elif key == "AISOS-51":
                return task_b
            else:
                return feature_issue

        jira = MagicMock()
        jira.get_issue = AsyncMock(side_effect=_tracked)

        tickets = [_make_ticket("AISOS-50"), _make_ticket("AISOS-51")]
        await _group_by_feature(tickets, jira)

        # AISOS-10 should appear: twice as parent check + once for summary fetch = 3
        feature_calls = [k for k in get_issue_calls if k == "AISOS-10"]
        assert len(feature_calls) == 3  # 2 parent lookups + 1 summary fetch

    @pytest.mark.asyncio
    async def test_rollup_aggregates_tokens(self) -> None:
        feature_issue = _make_issue("AISOS-10", issue_type="Feature")
        task_a = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-10")
        task_b = _make_issue("AISOS-51", issue_type="Task", parent_key="AISOS-10")

        jira = MagicMock()
        jira.get_issue = AsyncMock(
            side_effect=[task_a, feature_issue, task_b, feature_issue, feature_issue]
        )

        tickets = [
            _make_ticket("AISOS-50", input_tokens=100, output_tokens=50),
            _make_ticket("AISOS-51", input_tokens=200, output_tokens=80),
        ]
        result = await _group_by_feature(tickets, jira)

        rollup = result["AISOS-10"]
        assert rollup.total_input_tokens == 300
        assert rollup.total_output_tokens == 130

    @pytest.mark.asyncio
    async def test_rollup_completion_percentage(self) -> None:
        feature_issue = _make_issue("AISOS-10", issue_type="Feature")
        task_a = _make_issue("AISOS-50", issue_type="Task", parent_key="AISOS-10")
        task_b = _make_issue("AISOS-51", issue_type="Task", parent_key="AISOS-10")

        jira = MagicMock()
        jira.get_issue = AsyncMock(
            side_effect=[task_a, feature_issue, task_b, feature_issue, feature_issue]
        )

        tickets = [
            _make_ticket("AISOS-50", status="completed"),
            _make_ticket("AISOS-51", status="in_progress"),
        ]
        result = await _group_by_feature(tickets, jira)

        rollup = result["AISOS-10"]
        assert rollup.tickets_completed == 1
        assert rollup.tickets_in_progress == 1
        assert rollup.completion_percentage == 50.0


# ---------------------------------------------------------------------------
# collect_weekly_data: feature_rollups integration
# ---------------------------------------------------------------------------


class TestCollectWeeklyDataFeatureRollups:
    @pytest.mark.asyncio
    async def test_feature_rollups_populated(self) -> None:
        """collect_weekly_data uses jira_client kwarg to populate feature_rollups."""
        feature_issue = _make_issue("AISOS-10", issue_type="Feature", summary="Feat")
        task_issue = _make_issue("AISOS-100", issue_type="Task", parent_key="AISOS-10")

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(side_effect=[task_issue, feature_issue, feature_issue])
        mock_jira.close = AsyncMock()

        redis_key = "langgraph:checkpoint:AISOS-100"
        redis_state = _make_state("AISOS-100")

        async def _scan(cursor, **_kwargs):
            return (0, [redis_key]) if cursor == 0 else (0, [])

        async def _get(key):
            return json.dumps(redis_state) if key == redis_key else None

        redis_mock = AsyncMock()
        redis_mock.scan = AsyncMock(side_effect=_scan)
        redis_mock.get = AsyncMock(side_effect=_get)

        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            AsyncMock(return_value=redis_mock),
        ):
            report = await collect_weekly_data("AISOS", days=30, jira_client=mock_jira)

        assert "AISOS-10" in report.feature_rollups
        assert len(report.feature_rollups["AISOS-10"].linked_tickets) == 1

    @pytest.mark.asyncio
    async def test_feature_rollups_unassigned_when_no_parent(self) -> None:
        task_issue = _make_issue("AISOS-100", issue_type="Task", parent_key=None)

        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(return_value=task_issue)
        mock_jira.close = AsyncMock()

        redis_key = "langgraph:checkpoint:AISOS-100"
        redis_state = _make_state("AISOS-100")

        async def _scan(cursor, **_kwargs):
            return (0, [redis_key]) if cursor == 0 else (0, [])

        async def _get(key):
            return json.dumps(redis_state) if key == redis_key else None

        redis_mock = AsyncMock()
        redis_mock.scan = AsyncMock(side_effect=_scan)
        redis_mock.get = AsyncMock(side_effect=_get)

        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            AsyncMock(return_value=redis_mock),
        ):
            report = await collect_weekly_data("AISOS", days=30, jira_client=mock_jira)

        assert UNASSIGNED_FEATURE_KEY in report.feature_rollups

    @pytest.mark.asyncio
    async def test_feature_rollups_empty_when_no_tickets(self) -> None:
        mock_jira = MagicMock()
        mock_jira.close = AsyncMock()

        redis_mock = AsyncMock()
        redis_mock.scan = AsyncMock(return_value=(0, []))

        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            AsyncMock(return_value=redis_mock),
        ):
            report = await collect_weekly_data("AISOS", days=7, jira_client=mock_jira)

        assert report.feature_rollups == {}

    @pytest.mark.asyncio
    async def test_jira_client_not_closed_when_injected(self) -> None:
        """When caller passes jira_client, collect_weekly_data must NOT close it."""
        mock_jira = MagicMock()
        mock_jira.get_issue = AsyncMock(
            return_value=_make_issue("AISOS-100", issue_type="Task", parent_key=None)
        )
        mock_jira.close = AsyncMock()

        redis_mock = AsyncMock()
        redis_mock.scan = AsyncMock(return_value=(0, []))

        with patch(
            "forge.workflow.stats.weekly_report.get_redis_client",
            AsyncMock(return_value=redis_mock),
        ):
            await collect_weekly_data("AISOS", days=7, jira_client=mock_jira)

        mock_jira.close.assert_not_called()
