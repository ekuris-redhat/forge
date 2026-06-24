"""Unit tests for the /forge stats Jira comment command handler."""

from unittest.mock import AsyncMock, patch

import pytest

from forge.models.events import EventSource
from forge.orchestrator.worker import OrchestratorWorker
from forge.queue.models import QueueMessage


def _make_jira_message(ticket_key: str, comment_body: str) -> QueueMessage:
    """Create a Jira comment QueueMessage."""
    return QueueMessage(
        message_id="1234567890-0",
        event_id="test-event-001",
        source=EventSource.JIRA,
        event_type="comment_created",
        ticket_key=ticket_key,
        payload={
            "issue": {
                "key": ticket_key,
                "fields": {
                    "issuetype": {"name": "Feature"},
                    "labels": [],
                },
            },
            "comment": {"body": comment_body},
            "changelog": {"items": []},
        },
    )


def _base_state(ticket_key: str = "TEST-123", **overrides) -> dict:
    """Return a minimal workflow state dict."""
    return {
        "ticket_key": ticket_key,
        "ticket_type": "Feature",
        "current_node": "prd_approval_gate",
        "is_paused": True,
        "context": {},
        "stats_stages": {
            "prd": {
                "stage_name": "prd",
                "iteration_count": 1,
                "machine_time_seconds": 30.0,
                "human_time_seconds": 120.0,
                "input_tokens": 500,
                "output_tokens": 800,
            }
        },
        "stats_pr_urls": [],
        "stats_ci_cycles": 0,
        "stats_outcome": None,
        "stats_outcome_reason": None,
        **overrides,
    }


@pytest.fixture
def worker() -> OrchestratorWorker:
    return OrchestratorWorker(consumer_name="test-worker")


@pytest.fixture
def mock_jira():
    """Return a mock JiraClient that is also an async context manager."""
    jira = AsyncMock()
    jira.add_comment = AsyncMock()
    jira.close = AsyncMock()
    return jira


class TestForgeStatsCommandDetection:
    """Tests that /forge stats is detected case-insensitively."""

    @pytest.mark.asyncio
    async def test_forge_stats_detected_lowercase(self, worker: OrchestratorWorker, mock_jira):
        """/forge stats (lowercase) triggers stats posting."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result is state, "State must be returned unchanged"
        mock_jira.add_comment.assert_awaited_once()
        mock_jira.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_forge_stats_detected_uppercase(self, worker: OrchestratorWorker, mock_jira):
        """/FORGE STATS (uppercase) triggers stats posting."""
        message = _make_jira_message("TEST-123", "/FORGE STATS")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result is state

    @pytest.mark.asyncio
    async def test_forge_stats_detected_mixed_case(self, worker: OrchestratorWorker, mock_jira):
        """/Forge Stats (mixed case) triggers stats posting."""
        message = _make_jira_message("TEST-123", "/Forge Stats")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result is state

    @pytest.mark.asyncio
    async def test_forge_stats_with_trailing_text(self, worker: OrchestratorWorker, mock_jira):
        """/forge stats with unknown trailing subcommand is treated as informational (no post)."""
        message = _make_jira_message("TEST-123", "/forge stats please show me")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        # Unknown subcommand is informational — state is returned unchanged, no comment posted
        assert result is state
        mock_jira.add_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_forge_stats_with_leading_whitespace(self, worker: OrchestratorWorker, mock_jira):
        """Leading whitespace before /forge stats is stripped before matching."""
        message = _make_jira_message("TEST-123", "   /forge stats")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result is state
        mock_jira.add_comment.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_non_forge_stats_comment_not_intercepted(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """Comments not starting with /forge stats are processed normally."""
        message = _make_jira_message("TEST-123", "!Please revise the PRD")
        state = _base_state()

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch("forge.orchestrator.worker.post_status_comment", new_callable=AsyncMock),
        ):
            result = await worker._handle_resume_event(message, state)

        # Should be treated as a revision request, not a stats command
        assert result is not state or result.get("revision_requested") is True


class TestForgeStatsReturnStateUnchanged:
    """Tests that /forge stats returns the current state without modification."""

    @pytest.mark.asyncio
    async def test_state_identity_returned(self, worker: OrchestratorWorker, mock_jira):
        """The exact same state object is returned (identity check)."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result is state

    @pytest.mark.asyncio
    async def test_is_paused_not_modified(self, worker: OrchestratorWorker, mock_jira):
        """is_paused flag is not changed by /forge stats command."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state(is_paused=True)

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result["is_paused"] is True

    @pytest.mark.asyncio
    async def test_current_node_not_modified(self, worker: OrchestratorWorker, mock_jira):
        """current_node is not changed by /forge stats command."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state(current_node="spec_approval_gate")

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result["current_node"] == "spec_approval_gate"


class TestForgeStatsRetrieval:
    """Tests for stats retrieval and formatting."""

    @pytest.mark.asyncio
    async def test_posts_formatted_stats_to_correct_ticket(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """The stats comment is posted to the ticket from the message."""
        message = _make_jira_message("PROJ-456", "/forge stats")
        state = _base_state(ticket_key="PROJ-456")

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, state)

        mock_jira.add_comment.assert_awaited_once()
        call_args = mock_jira.add_comment.await_args
        assert call_args.args[0] == "PROJ-456"

    @pytest.mark.asyncio
    async def test_posted_comment_contains_stats_heading(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """The posted comment includes a workflow statistics section."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, state)

        comment_body = mock_jira.add_comment.await_args.args[1]
        assert "Workflow Statistics" in comment_body

    @pytest.mark.asyncio
    async def test_stats_uses_pre_set_outcome(self, worker: OrchestratorWorker, mock_jira):
        """When stats_outcome is set in state, it is used in the formatted output."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state(stats_outcome="Completed")

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, state)

        comment_body = mock_jira.add_comment.await_args.args[1]
        assert "Completed" in comment_body

    @pytest.mark.asyncio
    async def test_stats_derives_blocked_outcome(self, worker: OrchestratorWorker, mock_jira):
        """When is_blocked=True and no pre-set outcome, outcome is 'Blocked'."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state(is_blocked=True, stats_outcome=None)

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, state)

        comment_body = mock_jira.add_comment.await_args.args[1]
        assert "Blocked" in comment_body

    @pytest.mark.asyncio
    async def test_stats_derives_failed_outcome(self, worker: OrchestratorWorker, mock_jira):
        """When last_error is set and no pre-set outcome, outcome is 'Failed'."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state(last_error="Something went wrong", stats_outcome=None)

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, state)

        comment_body = mock_jira.add_comment.await_args.args[1]
        assert "Failed" in comment_body

    @pytest.mark.asyncio
    async def test_stats_in_progress_outcome_for_active_workflow(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """Active workflow with no error/blocked status uses 'In Progress' outcome."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state(stats_outcome=None, is_blocked=False, last_error=None)

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, state)

        comment_body = mock_jira.add_comment.await_args.args[1]
        assert "In Progress" in comment_body


class TestForgeStatsMissingCheckpoint:
    """Tests for graceful handling when no stats data is present."""

    @pytest.mark.asyncio
    async def test_no_stats_stages_posts_no_data_message(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """When stats_stages key is missing, posts 'No workflow data found.' message."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = {
            "ticket_key": "TEST-123",
            "current_node": "prd_approval_gate",
            "is_paused": True,
            "context": {},
            # stats_stages is absent entirely
        }

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result is state
        mock_jira.add_comment.assert_awaited_once()
        comment_body = mock_jira.add_comment.await_args.args[1]
        assert "No workflow data found" in comment_body

    @pytest.mark.asyncio
    async def test_empty_stats_stages_still_formats(self, worker: OrchestratorWorker, mock_jira):
        """Empty stats_stages dict (workflow just started) still produces formatted output."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state(stats_stages={})

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result is state
        mock_jira.add_comment.assert_awaited_once()
        comment_body = mock_jira.add_comment.await_args.args[1]
        # Should contain the stats table, not the "no data" message
        assert "Workflow Statistics" in comment_body

    @pytest.mark.asyncio
    async def test_no_stats_returns_state_unchanged(self, worker: OrchestratorWorker, mock_jira):
        """Even when no data is found, current state is returned unchanged."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = {
            "ticket_key": "TEST-123",
            "current_node": "prd_approval_gate",
            "is_paused": True,
        }

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        assert result is state


class TestForgeStatsErrorHandling:
    """Tests for error resilience in the stats command handler."""

    @pytest.mark.asyncio
    async def test_jira_add_comment_failure_does_not_raise(self, worker: OrchestratorWorker):
        """JiraClient.add_comment failure is caught and does not propagate."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state()

        mock_jira = AsyncMock()
        mock_jira.add_comment = AsyncMock(side_effect=Exception("Jira API error"))
        mock_jira.close = AsyncMock()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            # Should not raise
            result = await worker._handle_resume_event(message, state)

        assert result is state

    @pytest.mark.asyncio
    async def test_formatter_failure_posts_fallback_message(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """When the formatter raises, a fallback message is posted."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state()

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch(
                "forge.orchestrator.worker.format_stats_summary",
                side_effect=RuntimeError("formatter error"),
            ),
        ):
            result = await worker._handle_resume_event(message, state)

        assert result is state
        mock_jira.add_comment.assert_awaited_once()
        comment_body = mock_jira.add_comment.await_args.args[1]
        assert "Unable to format" in comment_body

    @pytest.mark.asyncio
    async def test_jira_close_always_called_on_success(self, worker: OrchestratorWorker, mock_jira):
        """JiraClient.close() is called even after a successful add_comment."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, state)

        mock_jira.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_jira_close_called_even_after_no_data_path(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """JiraClient.close() is called in the 'no data' path too."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = {"ticket_key": "TEST-123", "current_node": "prd_approval_gate"}

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, state)

        mock_jira.close.assert_awaited_once()


class TestHandleStatsCommandDirect:
    """Direct unit tests for _handle_stats_command."""

    @pytest.mark.asyncio
    async def test_direct_call_with_stats(self, worker: OrchestratorWorker, mock_jira):
        """Direct call with stats data posts a formatted comment."""
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_stats_command("TEST-123", state)

        mock_jira.add_comment.assert_awaited_once()
        args = mock_jira.add_comment.await_args.args
        assert args[0] == "TEST-123"
        assert "Workflow Statistics" in args[1]

    @pytest.mark.asyncio
    async def test_direct_call_without_stats_stages(self, worker: OrchestratorWorker, mock_jira):
        """Direct call when stats_stages is missing posts 'No workflow data found.'."""
        state = {"ticket_key": "TEST-123", "current_node": "prd_approval_gate"}

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_stats_command("TEST-123", state)

        mock_jira.add_comment.assert_awaited_once()
        body = mock_jira.add_comment.await_args.args[1]
        assert "No workflow data found" in body

    @pytest.mark.asyncio
    async def test_uses_stats_outcome_reason_as_detail(self, worker: OrchestratorWorker, mock_jira):
        """stats_outcome_reason is passed as outcome_detail to the formatter."""
        state = _base_state(
            stats_outcome="Blocked",
            stats_outcome_reason="Waiting for security review",
        )

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch("forge.orchestrator.worker.format_stats_summary") as mock_format,
        ):
            mock_format.return_value = "formatted stats"
            await worker._handle_stats_command("TEST-123", state)

        mock_format.assert_called_once_with(state, "Blocked", "Waiting for security review")

    @pytest.mark.asyncio
    async def test_uses_last_error_as_detail_when_no_reason(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """last_error is used as outcome_detail when stats_outcome_reason is absent."""
        state = _base_state(
            stats_outcome=None,
            last_error="Connection timeout",
            stats_outcome_reason=None,
        )

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch("forge.orchestrator.worker.format_stats_summary") as mock_format,
        ):
            mock_format.return_value = "formatted stats"
            await worker._handle_stats_command("TEST-123", state)

        _, called_outcome, called_detail = mock_format.call_args.args
        assert called_outcome == "Failed"
        assert called_detail == "Connection timeout"
