"""Unit tests for forge.workflow.stats.notifications.

All Jira API calls are mocked; no real HTTP connections are made.
"""

from __future__ import annotations

import argparse
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.stats.notifications import (
    _format_mention,
    _parse_account_ids,
    get_notification_recipients,
    notify_report_ready,
)


# ---------------------------------------------------------------------------
# Tests for _format_mention
# ---------------------------------------------------------------------------


class TestFormatMention:
    """Tests for the _format_mention() helper."""

    def test_basic_account_id(self):
        """Account ID is wrapped in Jira mention syntax."""
        assert _format_mention("abc123") == "[~accountid:abc123]"

    def test_long_account_id(self):
        """Longer account IDs (real Jira IDs) are formatted correctly."""
        long_id = "5e7e3b1a8c9d2f0b4a6e8c12"
        assert _format_mention(long_id) == f"[~accountid:{long_id}]"

    def test_alphanumeric_account_id(self):
        """Alphanumeric account IDs are formatted correctly."""
        assert _format_mention("user-id-456") == "[~accountid:user-id-456]"

    def test_format_produces_valid_jira_syntax(self):
        """The output should start with [~accountid: and end with ]."""
        result = _format_mention("someuser")
        assert result.startswith("[~accountid:")
        assert result.endswith("]")

    def test_empty_string(self):
        """Empty string is formatted (caller is responsible for filtering)."""
        assert _format_mention("") == "[~accountid:]"


# ---------------------------------------------------------------------------
# Tests for _parse_account_ids
# ---------------------------------------------------------------------------


class TestParseAccountIds:
    """Tests for the _parse_account_ids() helper."""

    def test_list_of_strings(self):
        """A list of strings is returned as-is (stripped)."""
        assert _parse_account_ids(["abc", "def", "ghi"]) == ["abc", "def", "ghi"]

    def test_list_with_whitespace(self):
        """Items with leading/trailing whitespace are stripped."""
        assert _parse_account_ids(["  abc  ", " def"]) == ["abc", "def"]

    def test_comma_separated_string(self):
        """Comma-separated string is split into individual IDs."""
        assert _parse_account_ids("abc,def,ghi") == ["abc", "def", "ghi"]

    def test_comma_separated_with_spaces(self):
        """Spaces around commas are stripped."""
        assert _parse_account_ids("abc, def , ghi") == ["abc", "def", "ghi"]

    def test_single_string(self):
        """A single account ID string (no commas) is returned as a one-item list."""
        assert _parse_account_ids("abc123") == ["abc123"]

    def test_empty_string(self):
        """Empty string returns empty list."""
        assert _parse_account_ids("") == []

    def test_empty_list(self):
        """Empty list returns empty list."""
        assert _parse_account_ids([]) == []

    def test_list_with_empty_entries(self):
        """Empty strings in a list are filtered out."""
        assert _parse_account_ids(["abc", "", "def"]) == ["abc", "def"]

    def test_comma_string_with_empty_parts(self):
        """Consecutive commas produce empty parts that are filtered out."""
        assert _parse_account_ids("abc,,def") == ["abc", "def"]

    def test_deduplication(self):
        """Duplicate IDs are removed, first occurrence wins."""
        assert _parse_account_ids(["abc", "def", "abc"]) == ["abc", "def"]

    def test_deduplication_in_string(self):
        """Duplicate IDs in comma-separated string are deduplicated."""
        assert _parse_account_ids("abc,def,abc") == ["abc", "def"]

    def test_unsupported_type(self):
        """Non-string, non-list input returns empty list."""
        assert _parse_account_ids(None) == []  # type: ignore[arg-type]
        assert _parse_account_ids(42) == []  # type: ignore[arg-type]
        assert _parse_account_ids({}) == []  # type: ignore[arg-type]

    def test_list_of_non_strings(self):
        """Non-string items in list are coerced to strings."""
        result = _parse_account_ids([123, 456])
        assert result == ["123", "456"]


# ---------------------------------------------------------------------------
# Tests for get_notification_recipients
# ---------------------------------------------------------------------------


class TestGetNotificationRecipients:
    """Tests for the async get_notification_recipients() function."""

    @pytest.mark.asyncio
    async def test_project_property_takes_precedence(self):
        """Project property overrides env var when both are set."""
        mock_jira = MagicMock()
        mock_jira.get_project_property = AsyncMock(return_value=["prop_user1", "prop_user2"])
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(weekly_report_notify="env_user1,env_user2"),
            ),
        ):
            result = await get_notification_recipients("PROJ")

        assert result == ["prop_user1", "prop_user2"]

    @pytest.mark.asyncio
    async def test_falls_back_to_env_var_when_no_property(self):
        """Env var is used when the project property is not set."""
        mock_jira = MagicMock()
        mock_jira.get_project_property = AsyncMock(return_value=None)
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(weekly_report_notify="env_user1,env_user2"),
            ),
        ):
            result = await get_notification_recipients("PROJ")

        assert result == ["env_user1", "env_user2"]

    @pytest.mark.asyncio
    async def test_empty_when_no_config(self):
        """Returns empty list when no env var and no project property."""
        mock_jira = MagicMock()
        mock_jira.get_project_property = AsyncMock(return_value=None)
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(weekly_report_notify=""),
            ),
        ):
            result = await get_notification_recipients("PROJ")

        assert result == []

    @pytest.mark.asyncio
    async def test_project_leads_sentinel_with_no_property(self):
        """'project-leads' sentinel returns empty list when property is absent."""
        mock_jira = MagicMock()
        mock_jira.get_project_property = AsyncMock(return_value=None)
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(weekly_report_notify="project-leads"),
            ),
        ):
            result = await get_notification_recipients("PROJ")

        assert result == []

    @pytest.mark.asyncio
    async def test_project_property_as_string(self):
        """Project property value as comma-separated string is parsed correctly."""
        mock_jira = MagicMock()
        mock_jira.get_project_property = AsyncMock(return_value="user1,user2")
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(weekly_report_notify=""),
            ),
        ):
            result = await get_notification_recipients("PROJ")

        assert result == ["user1", "user2"]

    @pytest.mark.asyncio
    async def test_project_property_error_falls_back_to_env(self):
        """When the project property lookup fails, env var is used."""
        mock_jira = MagicMock()
        mock_jira.get_project_property = AsyncMock(side_effect=Exception("Network error"))
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(weekly_report_notify="fallback_user"),
            ),
        ):
            result = await get_notification_recipients("PROJ")

        assert result == ["fallback_user"]

    @pytest.mark.asyncio
    async def test_jira_client_is_closed_after_property_lookup(self):
        """The JiraClient is always closed after the project property lookup."""
        mock_jira = MagicMock()
        mock_jira.get_project_property = AsyncMock(return_value=None)
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(weekly_report_notify=""),
            ),
        ):
            await get_notification_recipients("PROJ")

        mock_jira.close.assert_awaited_once()


# ---------------------------------------------------------------------------
# Tests for notify_report_ready
# ---------------------------------------------------------------------------


class TestNotifyReportReady:
    """Tests for the async notify_report_ready() function."""

    @pytest.mark.asyncio
    async def test_posts_comment_with_mentions(self):
        """A comment containing mentions is posted to the ticket."""
        from forge.integrations.jira.models import JiraComment

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(
            return_value=JiraComment(
                id="10001",
                author_id="forge-bot",
                author_name="Forge",
                body="test",
            )
        )
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://example.atlassian.net"),
            ),
        ):
            await notify_report_ready("PROJ-42", ["user1", "user2"])

        mock_jira.add_comment.assert_awaited_once()
        call_args = mock_jira.add_comment.call_args
        assert call_args[0][0] == "PROJ-42"
        comment_body = call_args[0][1]
        assert "[~accountid:user1]" in comment_body
        assert "[~accountid:user2]" in comment_body

    @pytest.mark.asyncio
    async def test_comment_includes_ticket_link(self):
        """The notification comment contains a link to the report ticket."""
        from forge.integrations.jira.models import JiraComment

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(
            return_value=JiraComment(
                id="10001",
                author_id="forge-bot",
                author_name="Forge",
                body="test",
            )
        )
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://example.atlassian.net"),
            ),
        ):
            await notify_report_ready(
                "PROJ-42",
                ["user1"],
                jira_base_url="https://example.atlassian.net",
            )

        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "PROJ-42" in comment_body
        assert "https://example.atlassian.net/browse/PROJ-42" in comment_body

    @pytest.mark.asyncio
    async def test_no_comment_when_recipients_empty(self):
        """No comment is posted when the recipients list is empty."""
        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock()
        mock_jira.close = AsyncMock()

        with patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira):
            await notify_report_ready("PROJ-42", [])

        mock_jira.add_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_skips_invalid_account_ids_with_spaces(self):
        """Account IDs containing spaces are skipped with a warning."""
        from forge.integrations.jira.models import JiraComment

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(
            return_value=JiraComment(
                id="10001",
                author_id="forge-bot",
                author_name="Forge",
                body="test",
            )
        )
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://example.atlassian.net"),
            ),
        ):
            await notify_report_ready("PROJ-42", ["valid_user", "bad user"])

        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "[~accountid:valid_user]" in comment_body
        assert "bad user" not in comment_body

    @pytest.mark.asyncio
    async def test_skips_account_ids_with_commas(self):
        """Account IDs containing commas are treated as malformed and skipped."""
        from forge.integrations.jira.models import JiraComment

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(
            return_value=JiraComment(
                id="10001",
                author_id="forge-bot",
                author_name="Forge",
                body="test",
            )
        )
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://example.atlassian.net"),
            ),
        ):
            await notify_report_ready("PROJ-42", ["valid_user", "bad,user"])

        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "[~accountid:valid_user]" in comment_body
        assert "bad,user" not in comment_body

    @pytest.mark.asyncio
    async def test_no_comment_when_all_recipients_invalid(self):
        """No comment is posted when all recipients are invalid."""
        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock()
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://example.atlassian.net"),
            ),
        ):
            await notify_report_ready("PROJ-42", ["bad user", "also,bad"])

        mock_jira.add_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_jira_client_closed_on_success(self):
        """JiraClient.close() is called after a successful comment post."""
        from forge.integrations.jira.models import JiraComment

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(
            return_value=JiraComment(
                id="10001",
                author_id="forge-bot",
                author_name="Forge",
                body="test",
            )
        )
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://example.atlassian.net"),
            ),
        ):
            await notify_report_ready("PROJ-42", ["user1"])

        mock_jira.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_jira_client_closed_on_error(self):
        """JiraClient.close() is called even when add_comment raises."""
        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(side_effect=Exception("API error"))
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://example.atlassian.net"),
            ),
        ):
            with pytest.raises(Exception, match="API error"):
                await notify_report_ready("PROJ-42", ["user1"])

        mock_jira.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_jira_base_url_override(self):
        """jira_base_url parameter overrides the settings value."""
        from forge.integrations.jira.models import JiraComment

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(
            return_value=JiraComment(
                id="10001",
                author_id="forge-bot",
                author_name="Forge",
                body="test",
            )
        )
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://wrong.atlassian.net"),
            ),
        ):
            await notify_report_ready(
                "PROJ-1",
                ["user1"],
                jira_base_url="https://correct.atlassian.net",
            )

        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "https://correct.atlassian.net/browse/PROJ-1" in comment_body
        assert "wrong" not in comment_body

    @pytest.mark.asyncio
    async def test_trailing_slash_stripped_from_base_url(self):
        """Trailing slashes in jira_base_url are stripped before building the link."""
        from forge.integrations.jira.models import JiraComment

        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(
            return_value=JiraComment(
                id="10001",
                author_id="forge-bot",
                author_name="Forge",
                body="test",
            )
        )
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.notifications.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.notifications.get_settings",
                return_value=MagicMock(jira_base_url="https://example.atlassian.net/"),
            ),
        ):
            await notify_report_ready("PROJ-5", ["user1"])

        comment_body = mock_jira.add_comment.call_args[0][1]
        # Should not have double slash
        assert "//browse" not in comment_body
        assert "https://example.atlassian.net/browse/PROJ-5" in comment_body


# ---------------------------------------------------------------------------
# Tests for CLI --notify integration
# ---------------------------------------------------------------------------


class TestCLINotifyFlag:
    """Tests for the --notify flag in cmd_weekly_report."""

    def _make_args(self, **kwargs) -> argparse.Namespace:
        defaults = {
            "project": "PROJ",
            "days": 7,
            "output": None,
            "format": "text",
            "create_ticket": False,
            "notify": False,
        }
        defaults.update(kwargs)
        return argparse.Namespace(**defaults)

    @pytest.mark.asyncio
    async def test_notify_without_create_ticket_returns_error(self):
        """--notify without --create-ticket returns exit code 1."""
        from forge.cli import cmd_weekly_report
        from forge.workflow.stats.weekly_report import (
            TicketSummary,
            WeeklyReportData,
        )

        report = WeeklyReportData(
            project="PROJ",
            period_days=7,
            report_start="2024-01-01T00:00:00+00:00",
            report_end="2024-01-08T00:00:00+00:00",
            completed_tickets=[
                TicketSummary(ticket_key="PROJ-1", status="completed")
            ],
        )

        with patch(
            "forge.workflow.stats.weekly_report.collect_weekly_data",
            new_callable=AsyncMock,
            return_value=report,
        ):
            args = self._make_args(notify=True, create_ticket=False)
            result = await cmd_weekly_report(args)

        assert result == 1

    @pytest.mark.asyncio
    async def test_notify_sends_notification_when_create_ticket_succeeds(self):
        """--notify posts a notification after successfully creating the ticket."""
        from forge.cli import cmd_weekly_report
        from forge.workflow.stats.weekly_report import (
            TicketSummary,
            WeeklyReportData,
        )

        report = WeeklyReportData(
            project="PROJ",
            period_days=7,
            report_start="2024-01-01T00:00:00+00:00",
            report_end="2024-01-08T00:00:00+00:00",
            completed_tickets=[
                TicketSummary(ticket_key="PROJ-1", status="completed")
            ],
        )

        with (
            patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new_callable=AsyncMock,
                return_value=report,
            ),
            patch(
                "forge.workflow.stats.report_ticket.ensure_report_ticket",
                new_callable=AsyncMock,
                return_value="PROJ-99",
            ),
            patch(
                "forge.workflow.stats.notifications.get_notification_recipients",
                new_callable=AsyncMock,
                return_value=["user1"],
            ),
            patch(
                "forge.workflow.stats.notifications.notify_report_ready",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            args = self._make_args(notify=True, create_ticket=True)
            result = await cmd_weekly_report(args)

        assert result == 0
        mock_notify.assert_awaited_once_with("PROJ-99", ["user1"])

    @pytest.mark.asyncio
    async def test_no_notification_when_notify_flag_not_set(self):
        """Without --notify, no notification functions are called."""
        from forge.cli import cmd_weekly_report
        from forge.workflow.stats.weekly_report import (
            TicketSummary,
            WeeklyReportData,
        )

        report = WeeklyReportData(
            project="PROJ",
            period_days=7,
            report_start="2024-01-01T00:00:00+00:00",
            report_end="2024-01-08T00:00:00+00:00",
            completed_tickets=[
                TicketSummary(ticket_key="PROJ-1", status="completed")
            ],
        )

        with (
            patch(
                "forge.workflow.stats.weekly_report.collect_weekly_data",
                new_callable=AsyncMock,
                return_value=report,
            ),
            patch(
                "forge.workflow.stats.notifications.notify_report_ready",
                new_callable=AsyncMock,
            ) as mock_notify,
        ):
            args = self._make_args(notify=False, create_ticket=False)
            result = await cmd_weekly_report(args)

        mock_notify.assert_not_awaited()
        assert result == 0
