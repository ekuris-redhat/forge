"""Unit tests for forge.workflow.stats.report_ticket.

Tests verify:
- resolve_report_ticket() uses the correct JQL and returns the first match key
- resolve_report_ticket() returns None when no issues are found
- create_report_ticket() calls create_task() with the correct args
- update_report_ticket() calls update_description() with the correct args
- ensure_report_ticket() creates a ticket when none exists
- ensure_report_ticket() updates an existing ticket (no duplicate)
- ensure_report_ticket() is idempotent — second call updates, not duplicates
- JiraClient is always closed after each operation
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.stats.report_ticket import (
    REPORT_LABELS,
    _report_jql,
    _report_summary,
    create_report_ticket,
    ensure_report_ticket,
    resolve_report_ticket,
    update_report_ticket,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

PROJECT = "PROJ"
WEEK_START = date(2024, 1, 8)
REPORT_MARKDOWN = "## Weekly Report\n\nAll good."
TICKET_KEY = "PROJ-42"


def _make_jira_mock(
    search_return: list | None = None,
    create_task_return: str = TICKET_KEY,
) -> MagicMock:
    """Return a mock JiraClient with async search_issues, create_task, update_description."""
    mock = MagicMock()
    mock.search_issues = AsyncMock(return_value=search_return or [])
    mock.create_task = AsyncMock(return_value=create_task_return)
    mock.update_description = AsyncMock(return_value=None)
    mock.close = AsyncMock()
    return mock


def _make_issue(key: str = TICKET_KEY) -> MagicMock:
    issue = MagicMock()
    issue.key = key
    return issue


# ---------------------------------------------------------------------------
# _report_summary
# ---------------------------------------------------------------------------


class TestReportSummary:
    def test_format(self):
        summary = _report_summary("PROJ", date(2024, 1, 8))
        assert summary == "Forge Weekly Report - PROJ - Week of 2024-01-08"

    def test_different_project(self):
        summary = _report_summary("MYPROJ", date(2024, 6, 3))
        assert summary == "Forge Weekly Report - MYPROJ - Week of 2024-06-03"

    def test_contains_week_of_fragment(self):
        summary = _report_summary("X", date(2024, 12, 30))
        assert "Week of 2024-12-30" in summary


# ---------------------------------------------------------------------------
# _report_jql
# ---------------------------------------------------------------------------


class TestReportJql:
    def test_contains_project(self):
        jql = _report_jql("PROJ", date(2024, 1, 8))
        assert '"PROJ"' in jql

    def test_contains_label(self):
        jql = _report_jql("PROJ", date(2024, 1, 8))
        assert '"forge:weekly-report"' in jql

    def test_contains_week_of(self):
        jql = _report_jql("PROJ", date(2024, 1, 8))
        assert "Week of 2024-01-08" in jql

    def test_full_jql(self):
        jql = _report_jql("PROJ", date(2024, 1, 8))
        assert 'project = "PROJ"' in jql
        assert 'labels = "forge:weekly-report"' in jql
        assert 'summary ~ "Week of 2024-01-08"' in jql


# ---------------------------------------------------------------------------
# resolve_report_ticket
# ---------------------------------------------------------------------------


class TestResolveReportTicket:
    @pytest.mark.asyncio
    async def test_returns_none_when_no_issues(self):
        mock_jira = _make_jira_mock(search_return=[])
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            result = await resolve_report_ticket(PROJECT, WEEK_START)

        assert result is None

    @pytest.mark.asyncio
    async def test_returns_first_issue_key(self):
        issues = [_make_issue("PROJ-42"), _make_issue("PROJ-43")]
        mock_jira = _make_jira_mock(search_return=issues)
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            result = await resolve_report_ticket(PROJECT, WEEK_START)

        assert result == "PROJ-42"

    @pytest.mark.asyncio
    async def test_calls_search_issues_with_correct_jql(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await resolve_report_ticket(PROJECT, WEEK_START)

        mock_jira.search_issues.assert_called_once()
        call_kwargs = mock_jira.search_issues.call_args
        jql = call_kwargs[1].get("jql") or call_kwargs[0][0]
        assert "PROJ" in jql
        assert "forge:weekly-report" in jql
        assert "2024-01-08" in jql

    @pytest.mark.asyncio
    async def test_limits_results(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await resolve_report_ticket(PROJECT, WEEK_START)

        _, kwargs = mock_jira.search_issues.call_args
        assert kwargs.get("max_results", 50) <= 10

    @pytest.mark.asyncio
    async def test_closes_client_on_success(self):
        mock_jira = _make_jira_mock(search_return=[_make_issue()])
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await resolve_report_ticket(PROJECT, WEEK_START)

        mock_jira.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_client_on_empty_result(self):
        mock_jira = _make_jira_mock(search_return=[])
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await resolve_report_ticket(PROJECT, WEEK_START)

        mock_jira.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_client_on_error(self):
        mock_jira = _make_jira_mock()
        mock_jira.search_issues = AsyncMock(side_effect=RuntimeError("network error"))
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            with pytest.raises(RuntimeError):
                await resolve_report_ticket(PROJECT, WEEK_START)

        mock_jira.close.assert_called_once()


# ---------------------------------------------------------------------------
# create_report_ticket
# ---------------------------------------------------------------------------


class TestCreateReportTicket:
    @pytest.mark.asyncio
    async def test_returns_ticket_key(self):
        mock_jira = _make_jira_mock(create_task_return="PROJ-42")
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            result = await create_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        assert result == "PROJ-42"

    @pytest.mark.asyncio
    async def test_calls_create_task_with_correct_project(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await create_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        _, kwargs = mock_jira.create_task.call_args
        assert kwargs.get("project_key") == PROJECT

    @pytest.mark.asyncio
    async def test_calls_create_task_with_correct_summary(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await create_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        _, kwargs = mock_jira.create_task.call_args
        expected_summary = "Forge Weekly Report - PROJ - Week of 2024-01-08"
        assert kwargs.get("summary") == expected_summary

    @pytest.mark.asyncio
    async def test_calls_create_task_with_correct_description(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await create_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        _, kwargs = mock_jira.create_task.call_args
        assert kwargs.get("description") == REPORT_MARKDOWN

    @pytest.mark.asyncio
    async def test_calls_create_task_with_correct_labels(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await create_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        _, kwargs = mock_jira.create_task.call_args
        labels = kwargs.get("labels") or []
        assert "forge:weekly-report" in labels
        assert "forge:generated" in labels

    @pytest.mark.asyncio
    async def test_closes_client_on_success(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await create_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        mock_jira.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_client_on_error(self):
        mock_jira = _make_jira_mock()
        mock_jira.create_task = AsyncMock(side_effect=RuntimeError("API error"))
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            with pytest.raises(RuntimeError):
                await create_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        mock_jira.close.assert_called_once()


# ---------------------------------------------------------------------------
# update_report_ticket
# ---------------------------------------------------------------------------


class TestUpdateReportTicket:
    @pytest.mark.asyncio
    async def test_calls_update_description_with_correct_key(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await update_report_ticket(TICKET_KEY, REPORT_MARKDOWN)

        mock_jira.update_description.assert_called_once_with(TICKET_KEY, REPORT_MARKDOWN)

    @pytest.mark.asyncio
    async def test_calls_update_description_with_correct_content(self):
        new_content = "## Updated Report\n\nNew data."
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await update_report_ticket(TICKET_KEY, new_content)

        mock_jira.update_description.assert_called_once_with(TICKET_KEY, new_content)

    @pytest.mark.asyncio
    async def test_does_not_call_create_task(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await update_report_ticket(TICKET_KEY, REPORT_MARKDOWN)

        mock_jira.create_task.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_none(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            result = await update_report_ticket(TICKET_KEY, REPORT_MARKDOWN)

        assert result is None

    @pytest.mark.asyncio
    async def test_closes_client_on_success(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            await update_report_ticket(TICKET_KEY, REPORT_MARKDOWN)

        mock_jira.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_closes_client_on_error(self):
        mock_jira = _make_jira_mock()
        mock_jira.update_description = AsyncMock(side_effect=RuntimeError("fail"))
        with patch("forge.workflow.stats.report_ticket.JiraClient", return_value=mock_jira):
            with pytest.raises(RuntimeError):
                await update_report_ticket(TICKET_KEY, REPORT_MARKDOWN)

        mock_jira.close.assert_called_once()


# ---------------------------------------------------------------------------
# ensure_report_ticket
# ---------------------------------------------------------------------------


class TestEnsureReportTicket:
    @pytest.mark.asyncio
    async def test_creates_ticket_when_none_exists(self):
        """When resolve returns None, create_report_ticket should be called."""
        with (
            patch(
                "forge.workflow.stats.report_ticket.resolve_report_ticket",
                new=AsyncMock(return_value=None),
            ) as mock_resolve,
            patch(
                "forge.workflow.stats.report_ticket.create_report_ticket",
                new=AsyncMock(return_value=TICKET_KEY),
            ) as mock_create,
            patch(
                "forge.workflow.stats.report_ticket.update_report_ticket",
                new=AsyncMock(),
            ) as mock_update,
        ):
            result = await ensure_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        assert result == TICKET_KEY
        mock_resolve.assert_called_once_with(PROJECT, WEEK_START)
        mock_create.assert_called_once_with(PROJECT, WEEK_START, REPORT_MARKDOWN)
        # update is NOT called when creating (create already sets description)
        mock_update.assert_not_called()

    @pytest.mark.asyncio
    async def test_updates_existing_ticket(self):
        """When resolve returns a key, update_report_ticket should be called."""
        with (
            patch(
                "forge.workflow.stats.report_ticket.resolve_report_ticket",
                new=AsyncMock(return_value=TICKET_KEY),
            ) as mock_resolve,
            patch(
                "forge.workflow.stats.report_ticket.create_report_ticket",
                new=AsyncMock(return_value="PROJ-99"),
            ) as mock_create,
            patch(
                "forge.workflow.stats.report_ticket.update_report_ticket",
                new=AsyncMock(),
            ) as mock_update,
        ):
            result = await ensure_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        assert result == TICKET_KEY
        mock_resolve.assert_called_once_with(PROJECT, WEEK_START)
        mock_create.assert_not_called()
        mock_update.assert_called_once_with(TICKET_KEY, REPORT_MARKDOWN)

    @pytest.mark.asyncio
    async def test_idempotent_on_existing_ticket(self):
        """Calling ensure_report_ticket twice should yield the same key (no duplicate)."""
        with (
            patch(
                "forge.workflow.stats.report_ticket.resolve_report_ticket",
                new=AsyncMock(return_value=TICKET_KEY),
            ),
            patch(
                "forge.workflow.stats.report_ticket.create_report_ticket",
                new=AsyncMock(return_value="PROJ-99"),
            ) as mock_create,
            patch(
                "forge.workflow.stats.report_ticket.update_report_ticket",
                new=AsyncMock(),
            ),
        ):
            key1 = await ensure_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)
            key2 = await ensure_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        assert key1 == key2 == TICKET_KEY
        mock_create.assert_not_called()

    @pytest.mark.asyncio
    async def test_returns_created_key(self):
        new_key = "PROJ-100"
        with (
            patch(
                "forge.workflow.stats.report_ticket.resolve_report_ticket",
                new=AsyncMock(return_value=None),
            ),
            patch(
                "forge.workflow.stats.report_ticket.create_report_ticket",
                new=AsyncMock(return_value=new_key),
            ),
            patch(
                "forge.workflow.stats.report_ticket.update_report_ticket",
                new=AsyncMock(),
            ),
        ):
            result = await ensure_report_ticket(PROJECT, WEEK_START, REPORT_MARKDOWN)

        assert result == new_key


# ---------------------------------------------------------------------------
# REPORT_LABELS constant
# ---------------------------------------------------------------------------


class TestReportLabels:
    def test_contains_weekly_report_label(self):
        assert "forge:weekly-report" in REPORT_LABELS

    def test_contains_generated_label(self):
        assert "forge:generated" in REPORT_LABELS

    def test_is_list(self):
        assert isinstance(REPORT_LABELS, list)
