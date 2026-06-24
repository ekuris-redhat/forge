"""Unit tests for the /forge stats retry subcommand handler."""

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
    """Return a minimal workflow state dict with stats data."""
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


class TestForgeStatsRetryDetection:
    """Tests that /forge stats retry is detected distinctly from base /forge stats."""

    @pytest.mark.asyncio
    async def test_retry_detected_lowercase(self, worker: OrchestratorWorker):
        """/forge stats retry (lowercase) triggers the retry handler."""
        message = _make_jira_message("TEST-123", "/forge stats retry")
        state = _base_state()

        with patch.object(
            worker, "_handle_stats_retry_command", new_callable=AsyncMock
        ) as mock_retry:
            result = await worker._handle_resume_event(message, state)

        mock_retry.assert_awaited_once_with("TEST-123", state)
        assert result is state

    @pytest.mark.asyncio
    async def test_retry_detected_uppercase(self, worker: OrchestratorWorker):
        """/FORGE STATS RETRY (uppercase) triggers the retry handler."""
        message = _make_jira_message("TEST-123", "/FORGE STATS RETRY")
        state = _base_state()

        with patch.object(
            worker, "_handle_stats_retry_command", new_callable=AsyncMock
        ) as mock_retry:
            result = await worker._handle_resume_event(message, state)

        mock_retry.assert_awaited_once_with("TEST-123", state)
        assert result is state

    @pytest.mark.asyncio
    async def test_retry_detected_mixed_case(self, worker: OrchestratorWorker):
        """/Forge Stats Retry (mixed case) triggers the retry handler."""
        message = _make_jira_message("TEST-123", "/Forge Stats Retry")
        state = _base_state()

        with patch.object(
            worker, "_handle_stats_retry_command", new_callable=AsyncMock
        ) as mock_retry:
            result = await worker._handle_resume_event(message, state)

        mock_retry.assert_awaited_once_with("TEST-123", state)
        assert result is state

    @pytest.mark.asyncio
    async def test_retry_returns_state_unchanged(self, worker: OrchestratorWorker):
        """/forge stats retry returns current state without modification."""
        message = _make_jira_message("TEST-123", "/forge stats retry")
        state = _base_state(current_node="spec_approval_gate", is_paused=True)

        with patch.object(worker, "_handle_stats_retry_command", new_callable=AsyncMock):
            result = await worker._handle_resume_event(message, state)

        assert result is state
        assert result["current_node"] == "spec_approval_gate"
        assert result["is_paused"] is True

    @pytest.mark.asyncio
    async def test_base_stats_uses_base_handler(self, worker: OrchestratorWorker):
        """Plain /forge stats (no subcommand) uses the base handler, not retry."""
        message = _make_jira_message("TEST-123", "/forge stats")
        state = _base_state()

        base_called = []
        retry_called = []

        with (
            patch.object(
                worker,
                "_handle_stats_command",
                new_callable=AsyncMock,
                side_effect=lambda *_a, **_kw: base_called.append(True),
            ),
            patch.object(
                worker,
                "_handle_stats_retry_command",
                new_callable=AsyncMock,
                side_effect=lambda *_a, **_kw: retry_called.append(True),
            ),
        ):
            result = await worker._handle_resume_event(message, state)

        assert len(base_called) == 1, "Base handler should be called once"
        assert len(retry_called) == 0, "Retry handler should NOT be called"
        assert result is state

    @pytest.mark.asyncio
    async def test_retry_does_not_call_base_handler(self, worker: OrchestratorWorker):
        """/forge stats retry does not invoke the base stats handler."""
        message = _make_jira_message("TEST-123", "/forge stats retry")
        state = _base_state()

        base_called = []
        retry_called = []

        with (
            patch.object(
                worker,
                "_handle_stats_command",
                new_callable=AsyncMock,
                side_effect=lambda *_a, **_kw: base_called.append(True),
            ),
            patch.object(
                worker,
                "_handle_stats_retry_command",
                new_callable=AsyncMock,
                side_effect=lambda *_a, **_kw: retry_called.append(True),
            ),
        ):
            result = await worker._handle_resume_event(message, state)

        assert len(retry_called) == 1, "Retry handler should be called once"
        assert len(base_called) == 0, "Base handler should NOT be called"
        assert result is state


class TestForgeStatsUnknownSubcommand:
    """Tests that unknown /forge stats subcommands are handled gracefully."""

    @pytest.mark.asyncio
    async def test_unknown_subcommand_returns_state_unchanged(self, worker: OrchestratorWorker):
        """Unknown /forge stats subcommand returns current state without posting."""
        message = _make_jira_message("TEST-123", "/forge stats unknown-command")
        state = _base_state()

        with (
            patch.object(worker, "_handle_stats_command", new_callable=AsyncMock) as mock_base,
            patch.object(
                worker, "_handle_stats_retry_command", new_callable=AsyncMock
            ) as mock_retry,
        ):
            result = await worker._handle_resume_event(message, state)

        # Neither handler should be called for an unknown subcommand
        mock_base.assert_not_awaited()
        mock_retry.assert_not_awaited()
        assert result is state

    @pytest.mark.asyncio
    async def test_unknown_subcommand_does_not_post_comment(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """Unknown subcommand does not post any comment to Jira."""
        message = _make_jira_message("TEST-123", "/forge stats foobar")
        state = _base_state()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        mock_jira.add_comment.assert_not_awaited()
        assert result is state

    @pytest.mark.asyncio
    async def test_unknown_subcommand_is_informational_not_error(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """Unknown subcommand does not trigger revision request or any workflow change."""
        message = _make_jira_message("TEST-123", "/forge stats bogus")
        state = _base_state(is_paused=True, current_node="prd_approval_gate")

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, state)

        # State must be returned unchanged — workflow not resumed
        assert result is state
        assert result["is_paused"] is True
        assert result["current_node"] == "prd_approval_gate"


class TestForgeStatsRetryRepostBehavior:
    """Tests that /forge stats retry uses the re-post mechanism."""

    @pytest.mark.asyncio
    async def test_retry_calls_ensure_stats_is_final_comment(self, worker: OrchestratorWorker):
        """/forge stats retry calls ensure_stats_is_final_comment for re-posting."""
        state = _base_state()

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            await worker._handle_stats_retry_command("TEST-123", state)

        mock_ensure.assert_awaited_once()
        # args: (ticket_key, stats, outcome, outcome_detail)
        assert mock_ensure.await_args.args[0] == "TEST-123"
        assert mock_ensure.await_args.args[1] is state

    @pytest.mark.asyncio
    async def test_retry_does_not_call_add_comment_directly(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """/forge stats retry does not call JiraClient.add_comment directly."""
        state = _base_state()

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch(
                "forge.orchestrator.worker.ensure_stats_is_final_comment",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            await worker._handle_stats_retry_command("TEST-123", state)

        # The retry path goes through ensure_stats_is_final_comment, not direct add_comment
        mock_jira.add_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_passes_correct_outcome_to_ensure(self, worker: OrchestratorWorker):
        """Retry derives outcome correctly and passes it to ensure_stats_is_final_comment."""
        state = _base_state(stats_outcome="Completed")

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            await worker._handle_stats_retry_command("TEST-123", state)

        # args: (ticket_key, stats, outcome, outcome_detail)
        assert mock_ensure.await_args.args[0] == "TEST-123"
        assert mock_ensure.await_args.args[2] == "Completed"

    @pytest.mark.asyncio
    async def test_retry_derives_blocked_outcome(self, worker: OrchestratorWorker):
        """Retry correctly derives 'Blocked' outcome when is_blocked=True."""
        state = _base_state(is_blocked=True, stats_outcome=None)

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            await worker._handle_stats_retry_command("TEST-123", state)

        assert mock_ensure.await_args.args[2] == "Blocked"

    @pytest.mark.asyncio
    async def test_retry_derives_failed_outcome(self, worker: OrchestratorWorker):
        """Retry correctly derives 'Failed' outcome when last_error is set."""
        state = _base_state(last_error="Something went wrong", stats_outcome=None)

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            await worker._handle_stats_retry_command("TEST-123", state)

        assert mock_ensure.await_args.args[2] == "Failed"

    @pytest.mark.asyncio
    async def test_retry_derives_in_progress_outcome(self, worker: OrchestratorWorker):
        """Retry uses 'In Progress' outcome for active workflows."""
        state = _base_state(stats_outcome=None, is_blocked=False, last_error=None)

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            await worker._handle_stats_retry_command("TEST-123", state)

        assert mock_ensure.await_args.args[2] == "In Progress"

    @pytest.mark.asyncio
    async def test_retry_passes_outcome_detail(self, worker: OrchestratorWorker):
        """Retry passes stats_outcome_reason as outcome_detail."""
        state = _base_state(
            stats_outcome="Blocked",
            stats_outcome_reason="Waiting for review",
        )

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            await worker._handle_stats_retry_command("TEST-123", state)

        # args: (ticket_key, stats, outcome, outcome_detail)
        assert mock_ensure.await_args.args[3] == "Waiting for review"

    @pytest.mark.asyncio
    async def test_retry_uses_last_error_as_detail(self, worker: OrchestratorWorker):
        """Retry passes last_error as outcome_detail when no stats_outcome_reason."""
        state = _base_state(
            stats_outcome=None,
            last_error="Connection timeout",
            stats_outcome_reason=None,
        )

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            await worker._handle_stats_retry_command("TEST-123", state)

        # args: (ticket_key, stats, outcome, outcome_detail)
        assert mock_ensure.await_args.args[3] == "Connection timeout"


class TestForgeStatsRetryNoData:
    """Tests for retry behaviour when no stats data is present."""

    @pytest.mark.asyncio
    async def test_retry_with_no_stats_stages_posts_no_data(
        self, worker: OrchestratorWorker, mock_jira
    ):
        """/forge stats retry without stats_stages posts 'No workflow data found.'."""
        state = {
            "ticket_key": "TEST-123",
            "current_node": "prd_approval_gate",
            "is_paused": True,
            "context": {},
            # stats_stages key is absent
        }

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch(
                "forge.orchestrator.worker.ensure_stats_is_final_comment",
                new_callable=AsyncMock,
            ) as mock_ensure,
        ):
            await worker._handle_stats_retry_command("TEST-123", state)

        # Should fall back to the "no data" path before reaching ensure_stats_is_final_comment
        mock_ensure.assert_not_awaited()
        mock_jira.add_comment.assert_awaited_once()
        body = mock_jira.add_comment.await_args.args[1]
        assert "No workflow data found" in body

    @pytest.mark.asyncio
    async def test_retry_ensure_failure_does_not_raise(self, worker: OrchestratorWorker):
        """/forge stats retry failure in ensure_stats_is_final_comment is non-raising."""
        state = _base_state()

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            side_effect=Exception("network error"),
        ):
            # Should not raise
            await worker._handle_stats_retry_command("TEST-123", state)


class TestPostStatsCommentHelper:
    """Direct unit tests for _post_stats_comment helper."""

    @pytest.mark.asyncio
    async def test_force_repost_true_uses_ensure_stats(self, worker: OrchestratorWorker):
        """force_repost=True routes through ensure_stats_is_final_comment."""
        state = _base_state()

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            await worker._post_stats_comment("TEST-123", state, force_repost=True)

        mock_ensure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_repost_false_uses_add_comment(self, worker: OrchestratorWorker, mock_jira):
        """force_repost=False uses direct JiraClient.add_comment."""
        state = _base_state()

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch(
                "forge.orchestrator.worker.ensure_stats_is_final_comment",
                new_callable=AsyncMock,
            ) as mock_ensure,
        ):
            await worker._post_stats_comment("TEST-123", state, force_repost=False)

        mock_jira.add_comment.assert_awaited_once()
        mock_ensure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_force_repost_default_is_false(self, worker: OrchestratorWorker, mock_jira):
        """Default force_repost=False uses add_comment (not ensure_stats)."""
        state = _base_state()

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch(
                "forge.orchestrator.worker.ensure_stats_is_final_comment",
                new_callable=AsyncMock,
            ) as mock_ensure,
        ):
            await worker._post_stats_comment("TEST-123", state)

        mock_jira.add_comment.assert_awaited_once()
        mock_ensure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_handle_stats_command_delegates_to_post_helper(self, worker: OrchestratorWorker):
        """_handle_stats_command delegates to _post_stats_comment with force_repost=False."""
        state = _base_state()

        with patch.object(worker, "_post_stats_comment", new_callable=AsyncMock) as mock_post:
            await worker._handle_stats_command("TEST-123", state)

        mock_post.assert_awaited_once_with("TEST-123", state, force_repost=False)

    @pytest.mark.asyncio
    async def test_handle_stats_retry_command_delegates_to_post_helper(
        self, worker: OrchestratorWorker
    ):
        """_handle_stats_retry_command delegates to _post_stats_comment with force_repost=True."""
        state = _base_state()

        with patch.object(worker, "_post_stats_comment", new_callable=AsyncMock) as mock_post:
            await worker._handle_stats_retry_command("TEST-123", state)

        mock_post.assert_awaited_once_with("TEST-123", state, force_repost=True)

    @pytest.mark.asyncio
    async def test_retry_via_full_resume_event_calls_ensure(self, worker: OrchestratorWorker):
        """/forge stats retry via _handle_resume_event triggers ensure_stats_is_final_comment."""
        message = _make_jira_message("TEST-123", "/forge stats retry")
        state = _base_state()

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            return_value=True,
        ) as mock_ensure:
            result = await worker._handle_resume_event(message, state)

        mock_ensure.assert_awaited_once()
        assert result is state
