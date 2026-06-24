"""Integration tests for on-demand stats commands.

These tests verify the end-to-end behavior of:
- /forge stats  — Jira comment command (post current stats as a new comment)
- /forge stats retry — Jira comment command (re-post stats as final comment)
- forge stats <ticket> — CLI command (table and JSON output)

Each test scenario uses pytest fixtures that provide realistic mock checkpoint
state, then exercises the full command path from trigger to Jira comment
or stdout — mocking only the network boundary (JiraClient, checkpointer).
"""

import argparse
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.models.events import EventSource
from forge.orchestrator.worker import OrchestratorWorker
from forge.queue.models import QueueMessage

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _make_jira_message(ticket_key: str, comment_body: str) -> QueueMessage:
    """Build a minimal Jira comment QueueMessage."""
    return QueueMessage(
        message_id="9999999999-0",
        event_id="integ-test-event-001",
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


def _make_mock_jira() -> MagicMock:
    """Return a mock JiraClient with relevant async methods."""
    jira = MagicMock()
    jira.add_comment = AsyncMock()
    jira.close = AsyncMock()
    jira.get_comments = AsyncMock(return_value=[])
    return jira


# ---------------------------------------------------------------------------
# Checkpoint fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def checkpoint_with_stats() -> dict:
    """Checkpoint state containing populated stats data (PRD + Spec stages)."""
    return {
        "ticket_key": "INT-100",
        "ticket_type": "Feature",
        "current_node": "spec_approval_gate",
        "is_paused": True,
        "is_blocked": False,
        "last_error": None,
        "feedback_comment": None,
        "context": {},
        "stats_stages": {
            "prd": {
                "stage_name": "prd",
                "iteration_count": 2,
                "machine_time_seconds": 45.0,
                "human_time_seconds": 300.0,
                "input_tokens": 1200,
                "output_tokens": 2000,
                "started_at": "2024-01-15T10:00:00+00:00",
                "ended_at": "2024-01-15T10:00:45+00:00",
            },
            "spec": {
                "stage_name": "spec",
                "iteration_count": 1,
                "machine_time_seconds": 30.0,
                "human_time_seconds": 180.0,
                "input_tokens": 800,
                "output_tokens": 1500,
                "started_at": "2024-01-15T10:05:00+00:00",
                "ended_at": "2024-01-15T10:05:30+00:00",
            },
        },
        "stats_pr_urls": ["https://github.com/org/repo/pull/42"],
        "stats_ci_cycles": 1,
        "stats_outcome": None,
        "stats_outcome_reason": None,
        "stats_comment_posted": False,
        "workflow_run_id": "test-run-abc123",
    }


@pytest.fixture
def checkpoint_without_stats_key() -> dict:
    """Checkpoint state that has no stats_stages key (legacy workflow)."""
    return {
        "ticket_key": "INT-101",
        "ticket_type": "Feature",
        "current_node": "prd_approval_gate",
        "is_paused": True,
        "context": {},
        # Deliberately no stats_* keys — simulates pre-stats-tracking run
    }


@pytest.fixture
def checkpoint_with_empty_stages() -> dict:
    """Checkpoint state with stats_stages present but empty (workflow just started)."""
    return {
        "ticket_key": "INT-102",
        "ticket_type": "Feature",
        "current_node": "generate_prd",
        "is_paused": False,
        "is_blocked": False,
        "last_error": None,
        "context": {},
        "stats_stages": {},  # Present key, empty dict — in-progress workflow
        "stats_pr_urls": [],
        "stats_ci_cycles": 0,
        "stats_outcome": None,
        "stats_outcome_reason": None,
        "stats_comment_posted": False,
        "workflow_run_id": "test-run-def456",
    }


@pytest.fixture
def checkpoint_blocked() -> dict:
    """Checkpoint state representing a blocked workflow."""
    return {
        "ticket_key": "INT-103",
        "ticket_type": "Feature",
        "current_node": "escalate_blocked",
        "is_paused": True,
        "is_blocked": True,
        "last_error": None,
        "feedback_comment": "Requirements unclear — needs stakeholder input.",
        "context": {},
        "stats_stages": {
            "prd": {
                "stage_name": "prd",
                "iteration_count": 3,
                "machine_time_seconds": 120.0,
                "human_time_seconds": 600.0,
                "input_tokens": 3000,
                "output_tokens": 4000,
            }
        },
        "stats_pr_urls": [],
        "stats_ci_cycles": 0,
        "stats_outcome": None,
        "stats_outcome_reason": None,
        "stats_comment_posted": False,
        "workflow_run_id": "test-run-ghi789",
    }


@pytest.fixture
def checkpoint_failed() -> dict:
    """Checkpoint state representing a failed workflow."""
    return {
        "ticket_key": "INT-104",
        "ticket_type": "Feature",
        "current_node": "generate_spec",
        "is_paused": False,
        "is_blocked": False,
        "last_error": "LLM call timed out after 60 seconds",
        "feedback_comment": None,
        "context": {},
        "stats_stages": {
            "prd": {
                "stage_name": "prd",
                "iteration_count": 1,
                "machine_time_seconds": 60.0,
                "human_time_seconds": 0.0,
                "input_tokens": 1000,
                "output_tokens": 1800,
            }
        },
        "stats_pr_urls": [],
        "stats_ci_cycles": 0,
        "stats_outcome": None,
        "stats_outcome_reason": None,
        "stats_comment_posted": False,
        "workflow_run_id": "test-run-jkl012",
    }


@pytest.fixture
def checkpoint_completed() -> dict:
    """Checkpoint state for a fully completed workflow."""
    return {
        "ticket_key": "INT-105",
        "ticket_type": "Feature",
        "current_node": "aggregate_feature_status",
        "is_paused": False,
        "is_blocked": False,
        "last_error": None,
        "feedback_comment": None,
        "context": {},
        "stats_stages": {
            "prd": {
                "stage_name": "prd",
                "iteration_count": 1,
                "machine_time_seconds": 40.0,
                "human_time_seconds": 200.0,
                "input_tokens": 1000,
                "output_tokens": 1800,
            },
            "spec": {
                "stage_name": "spec",
                "iteration_count": 1,
                "machine_time_seconds": 30.0,
                "human_time_seconds": 150.0,
                "input_tokens": 900,
                "output_tokens": 1600,
            },
            "implementation": {
                "stage_name": "implementation",
                "iteration_count": 2,
                "machine_time_seconds": 900.0,
                "human_time_seconds": 0.0,
                "input_tokens": 8000,
                "output_tokens": 12000,
            },
        },
        "stats_pr_urls": [
            "https://github.com/org/repo/pull/99",
        ],
        "stats_ci_cycles": 2,
        "stats_outcome": "Completed",
        "stats_outcome_reason": None,
        "stats_comment_posted": True,
        "workflow_run_id": "test-run-mno345",
    }


@pytest.fixture
def worker() -> OrchestratorWorker:
    """OrchestratorWorker with a unique consumer name for isolation."""
    return OrchestratorWorker(consumer_name="integ-test-worker")


# ---------------------------------------------------------------------------
# Section 1: /forge stats — Jira comment command
# ---------------------------------------------------------------------------


class TestForgeStatsWithValidCheckpoint:
    """/forge stats posts a formatted stats comment when checkpoint has data."""

    @pytest.mark.asyncio
    async def test_stats_comment_is_posted_to_jira(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """/forge stats results in a call to JiraClient.add_comment."""
        message = _make_jira_message("INT-100", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, checkpoint_with_stats)

        mock_jira.add_comment.assert_awaited_once()
        assert result is checkpoint_with_stats, "State must be returned unchanged"

    @pytest.mark.asyncio
    async def test_stats_comment_posted_to_correct_ticket(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """/forge stats posts the comment to the correct Jira ticket key."""
        message = _make_jira_message("INT-100", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_with_stats)

        call_args = mock_jira.add_comment.call_args
        ticket_arg = call_args[0][0]
        assert ticket_arg == "INT-100"

    @pytest.mark.asyncio
    async def test_stats_comment_body_contains_stage_metrics(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """Comment body includes stage-level metrics (PRD iterations visible)."""
        message = _make_jira_message("INT-100", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_with_stats)

        comment_body = mock_jira.add_comment.call_args[0][1]
        # The Jira formatter produces a table; stage names appear as rows
        assert "PRD" in comment_body or "prd" in comment_body

    @pytest.mark.asyncio
    async def test_stats_comment_body_contains_outcome(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """Comment body includes the derived outcome string."""
        message = _make_jira_message("INT-100", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_with_stats)

        comment_body = mock_jira.add_comment.call_args[0][1]
        # Outcome for an in-progress workflow is "In Progress"
        assert "In Progress" in comment_body or "Outcome" in comment_body

    @pytest.mark.asyncio
    async def test_jira_client_closed_after_posting(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """JiraClient.close() is always called even on success."""
        message = _make_jira_message("INT-100", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_with_stats)

        mock_jira.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_workflow_state_returned_unchanged(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """/forge stats is read-only — returned state is the same object."""
        message = _make_jira_message("INT-100", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, checkpoint_with_stats)

        assert result is checkpoint_with_stats

    @pytest.mark.asyncio
    async def test_stats_derived_outcome_in_progress(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """In-progress workflow (no outcome/blocked/error) → 'In Progress' outcome."""
        # Ensure no pre-set outcome, no blocked, no error
        assert checkpoint_with_stats.get("stats_outcome") is None
        assert not checkpoint_with_stats.get("is_blocked")
        assert checkpoint_with_stats.get("last_error") is None

        message = _make_jira_message("INT-100", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_with_stats)

        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "In Progress" in comment_body


class TestForgeStatsWithBlockedWorkflow:
    """/forge stats correctly reports a blocked workflow outcome."""

    @pytest.mark.asyncio
    async def test_blocked_outcome_reported(self, worker: OrchestratorWorker, checkpoint_blocked):
        """Comment body contains 'Blocked' when workflow is_blocked=True."""
        message = _make_jira_message("INT-103", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_blocked)

        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "Blocked" in comment_body

    @pytest.mark.asyncio
    async def test_blocked_comment_posted_to_correct_ticket(
        self, worker: OrchestratorWorker, checkpoint_blocked
    ):
        """Stats for blocked workflow are posted to the blocked ticket key."""
        message = _make_jira_message("INT-103", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_blocked)

        ticket_arg = mock_jira.add_comment.call_args[0][0]
        assert ticket_arg == "INT-103"


class TestForgeStatsWithFailedWorkflow:
    """/forge stats correctly reports a failed workflow outcome."""

    @pytest.mark.asyncio
    async def test_failed_outcome_reported(self, worker: OrchestratorWorker, checkpoint_failed):
        """Comment body contains 'Failed' when workflow has last_error."""
        message = _make_jira_message("INT-104", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_failed)

        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "Failed" in comment_body

    @pytest.mark.asyncio
    async def test_failed_comment_posted_once(self, worker: OrchestratorWorker, checkpoint_failed):
        """Exactly one comment is posted for a failed workflow stats request."""
        message = _make_jira_message("INT-104", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_failed)

        assert mock_jira.add_comment.call_count == 1


# ---------------------------------------------------------------------------
# Section 2: /forge stats with missing checkpoint
# ---------------------------------------------------------------------------


class TestForgeStatsWithMissingCheckpoint:
    """/forge stats posts a fallback message when no stats data exists."""

    @pytest.mark.asyncio
    async def test_missing_stats_stages_key_posts_no_data_message(
        self, worker: OrchestratorWorker, checkpoint_without_stats_key
    ):
        """When stats_stages key is absent, posts 'No workflow data found.'."""
        message = _make_jira_message("INT-101", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, checkpoint_without_stats_key)

        mock_jira.add_comment.assert_awaited_once()
        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "No workflow data found" in comment_body
        assert result is checkpoint_without_stats_key

    @pytest.mark.asyncio
    async def test_missing_data_comment_posted_to_correct_ticket(
        self, worker: OrchestratorWorker, checkpoint_without_stats_key
    ):
        """Fallback message is posted to the correct ticket key."""
        message = _make_jira_message("INT-101", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_without_stats_key)

        ticket_arg = mock_jira.add_comment.call_args[0][0]
        assert ticket_arg == "INT-101"

    @pytest.mark.asyncio
    async def test_empty_stages_dict_does_not_trigger_fallback(
        self, worker: OrchestratorWorker, checkpoint_with_empty_stages
    ):
        """Empty stats_stages dict (key present) uses formatter, not fallback."""
        message = _make_jira_message("INT-102", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_with_empty_stages)

        # Should post a formatted comment (not "No workflow data found.")
        mock_jira.add_comment.assert_awaited_once()
        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "No workflow data found" not in comment_body

    @pytest.mark.asyncio
    async def test_state_returned_unchanged_when_no_stats(
        self, worker: OrchestratorWorker, checkpoint_without_stats_key
    ):
        """State identity is preserved even when no stats data is found."""
        message = _make_jira_message("INT-101", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, checkpoint_without_stats_key)

        assert result is checkpoint_without_stats_key


# ---------------------------------------------------------------------------
# Section 3: /forge stats retry
# ---------------------------------------------------------------------------


class TestForgeStatsRetry:
    """/forge stats retry re-posts stats via ensure_stats_is_final_comment."""

    @pytest.mark.asyncio
    async def test_retry_calls_ensure_stats_is_final_comment(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """/forge stats retry delegates to ensure_stats_is_final_comment, not add_comment."""
        message = _make_jira_message("INT-100", "/forge stats retry")

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
        ) as mock_ensure:
            result = await worker._handle_resume_event(message, checkpoint_with_stats)

        mock_ensure.assert_awaited_once()
        assert result is checkpoint_with_stats

    @pytest.mark.asyncio
    async def test_retry_does_not_call_add_comment_directly(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """/forge stats retry must not call JiraClient.add_comment for normal re-post."""
        message = _make_jira_message("INT-100", "/forge stats retry")
        mock_jira = _make_mock_jira()

        with (
            patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira),
            patch(
                "forge.orchestrator.worker.ensure_stats_is_final_comment",
                new_callable=AsyncMock,
            ),
        ):
            await worker._handle_resume_event(message, checkpoint_with_stats)

        # add_comment should NOT be called by the retry path (it's used by the base path)
        mock_jira.add_comment.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_retry_passes_correct_ticket_key(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """/forge stats retry passes the correct ticket key to ensure_stats_is_final_comment."""
        message = _make_jira_message("INT-100", "/forge stats retry")

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
        ) as mock_ensure:
            await worker._handle_resume_event(message, checkpoint_with_stats)

        call_args = mock_ensure.call_args
        ticket_arg = call_args[0][0]
        assert ticket_arg == "INT-100"

    @pytest.mark.asyncio
    async def test_retry_state_unchanged(self, worker: OrchestratorWorker, checkpoint_with_stats):
        """/forge stats retry returns the same state object unchanged."""
        message = _make_jira_message("INT-100", "/forge stats retry")

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
        ):
            result = await worker._handle_resume_event(message, checkpoint_with_stats)

        assert result is checkpoint_with_stats

    @pytest.mark.asyncio
    async def test_retry_with_missing_stats_posts_no_data_message(
        self, worker: OrchestratorWorker, checkpoint_without_stats_key
    ):
        """/forge stats retry posts 'No workflow data found.' when no stats data."""
        message = _make_jira_message("INT-101", "/forge stats retry")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            result = await worker._handle_resume_event(message, checkpoint_without_stats_key)

        mock_jira.add_comment.assert_awaited_once()
        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "No workflow data found" in comment_body
        assert result is checkpoint_without_stats_key

    @pytest.mark.asyncio
    async def test_retry_ensure_failure_does_not_raise(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """/forge stats retry does not propagate exceptions from ensure_stats_is_final_comment."""
        message = _make_jira_message("INT-100", "/forge stats retry")

        with patch(
            "forge.orchestrator.worker.ensure_stats_is_final_comment",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Network error"),
        ):
            # Should not raise
            result = await worker._handle_resume_event(message, checkpoint_with_stats)

        assert result is checkpoint_with_stats


# ---------------------------------------------------------------------------
# Section 4: forge stats CLI — table output
# ---------------------------------------------------------------------------


class TestCLIStatsTableOutput:
    """forge stats <ticket> displays a human-readable table."""

    @pytest.mark.asyncio
    async def test_table_output_exits_zero_on_success(self, checkpoint_with_stats):
        """forge stats returns exit code 0 when checkpoint has stats."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=False)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            exit_code = await cmd_stats(args)

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_table_output_contains_stage_labels(self, checkpoint_with_stats, capsys):
        """Table output includes stage labels (PRD, Spec) for populated stages."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=False)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        assert "PRD" in captured.out

    @pytest.mark.asyncio
    async def test_table_output_contains_outcome(self, checkpoint_with_stats, capsys):
        """Table output contains an Outcome line."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=False)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        assert "Outcome" in captured.out or "In Progress" in captured.out

    @pytest.mark.asyncio
    async def test_table_output_is_not_json(self, checkpoint_with_stats, capsys):
        """Without --json flag, output is human-readable text, not JSON."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=False)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        try:
            json.loads(captured.out)
            is_json = True
        except (json.JSONDecodeError, ValueError):
            is_json = False
        assert not is_json

    @pytest.mark.asyncio
    async def test_table_output_missing_checkpoint_exits_one(self, capsys):
        """forge stats exits 1 when no checkpoint is found."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-999", json=False)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=None),
        ):
            exit_code = await cmd_stats(args)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "No workflow data found" in captured.out

    @pytest.mark.asyncio
    async def test_table_output_missing_stats_key_exits_one(
        self, checkpoint_without_stats_key, capsys
    ):
        """forge stats exits 1 when checkpoint lacks stats_stages key."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-101", json=False)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_without_stats_key),
        ):
            exit_code = await cmd_stats(args)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "No workflow data found" in captured.out

    @pytest.mark.asyncio
    async def test_table_output_empty_stages_exits_zero(self, checkpoint_with_empty_stages):
        """forge stats exits 0 for an in-progress workflow with no stages recorded yet."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-102", json=False)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_empty_stages),
        ):
            exit_code = await cmd_stats(args)

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_table_output_connection_error_exits_one(self, capsys):
        """forge stats exits 1 when checkpointer raises a connection error."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=False)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(side_effect=ConnectionError("Redis unavailable")),
        ):
            exit_code = await cmd_stats(args)

        assert exit_code == 1
        captured = capsys.readouterr()
        assert "Error" in captured.err


# ---------------------------------------------------------------------------
# Section 5: forge stats CLI — JSON output
# ---------------------------------------------------------------------------


class TestCLIStatsJsonOutput:
    """forge stats <ticket> --json outputs structured JSON."""

    @pytest.mark.asyncio
    async def test_json_output_is_valid_json(self, checkpoint_with_stats, capsys):
        """--json flag produces parseable JSON."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        captured = capsys.readouterr()
        data = json.loads(captured.out)  # Should not raise
        assert isinstance(data, dict)

    @pytest.mark.asyncio
    async def test_json_output_contains_required_fields(self, checkpoint_with_stats, capsys):
        """JSON output includes ticket, outcome, ci_cycles, pr_urls, and stages fields."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert "ticket" in data
        assert "outcome" in data
        assert "ci_cycles" in data
        assert "pr_urls" in data
        assert "stages" in data

    @pytest.mark.asyncio
    async def test_json_output_ticket_matches_requested(self, checkpoint_with_stats, capsys):
        """JSON ticket field matches the requested ticket key."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["ticket"] == "INT-100"

    @pytest.mark.asyncio
    async def test_json_output_stages_contains_prd_data(self, checkpoint_with_stats, capsys):
        """JSON stages dict includes the prd stage from checkpoint."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert "prd" in data["stages"]

    @pytest.mark.asyncio
    async def test_json_output_ci_cycles_value(self, checkpoint_with_stats, capsys):
        """JSON ci_cycles matches the value stored in checkpoint."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["ci_cycles"] == checkpoint_with_stats["stats_ci_cycles"]

    @pytest.mark.asyncio
    async def test_json_output_pr_urls_present(self, checkpoint_with_stats, capsys):
        """JSON pr_urls list matches checkpoint data."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["pr_urls"] == checkpoint_with_stats["stats_pr_urls"]

    @pytest.mark.asyncio
    async def test_json_output_exits_zero_on_success(self, checkpoint_with_stats):
        """--json flag returns exit code 0 on success."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-100", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_stats),
        ):
            exit_code = await cmd_stats(args)

        assert exit_code == 0

    @pytest.mark.asyncio
    async def test_json_output_missing_checkpoint_exits_one(self):
        """--json flag still exits 1 when no checkpoint is found."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-999", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=None),
        ):
            exit_code = await cmd_stats(args)

        assert exit_code == 1


# ---------------------------------------------------------------------------
# Section 6: Partial / failed / blocked workflow stats
# ---------------------------------------------------------------------------


class TestPartialAndSpecialOutcomes:
    """Stats commands handle partial, failed, and blocked workflow states correctly."""

    @pytest.mark.asyncio
    async def test_jira_stats_completed_workflow_shows_completed_outcome(
        self, worker: OrchestratorWorker, checkpoint_completed
    ):
        """Pre-set stats_outcome='Completed' is forwarded directly to comment."""
        message = _make_jira_message("INT-105", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_completed)

        comment_body = mock_jira.add_comment.call_args[0][1]
        assert "Completed" in comment_body

    @pytest.mark.asyncio
    async def test_cli_blocked_workflow_outcome_in_json(self, checkpoint_blocked, capsys):
        """CLI --json output for blocked workflow includes 'Blocked' outcome."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-103", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_blocked),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "Blocked"

    @pytest.mark.asyncio
    async def test_cli_failed_workflow_outcome_in_json(self, checkpoint_failed, capsys):
        """CLI --json output for failed workflow includes 'Failed' outcome."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-104", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_failed),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "Failed"

    @pytest.mark.asyncio
    async def test_cli_in_progress_workflow_outcome_in_json(
        self, checkpoint_with_empty_stages, capsys
    ):
        """CLI --json output for in-progress workflow includes 'In Progress' outcome."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-102", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_with_empty_stages),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "In Progress"

    @pytest.mark.asyncio
    async def test_cli_completed_workflow_outcome_in_json(self, checkpoint_completed, capsys):
        """CLI --json output for completed workflow includes 'Completed' outcome."""
        from forge.cli import cmd_stats

        args = argparse.Namespace(ticket="INT-105", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=checkpoint_completed),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert data["outcome"] == "Completed"

    @pytest.mark.asyncio
    async def test_jira_stats_partial_workflow_shows_prd_stage_only(
        self, worker: OrchestratorWorker, checkpoint_with_stats
    ):
        """Stats for a workflow that has only completed PRD shows only PRD metrics."""
        # Remove spec stage to simulate partial run (only PRD completed)
        partial_state = {
            **checkpoint_with_stats,
            "stats_stages": {
                "prd": checkpoint_with_stats["stats_stages"]["prd"],
            },
        }

        message = _make_jira_message("INT-100", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, partial_state)

        comment_body = mock_jira.add_comment.call_args[0][1]
        # PRD metrics should appear; spec should show dash/empty
        assert "PRD" in comment_body or "prd" in comment_body

    @pytest.mark.asyncio
    async def test_cli_partial_workflow_json_contains_only_recorded_stages(
        self, checkpoint_with_stats, capsys
    ):
        """CLI JSON for partial workflow only includes recorded stages."""
        from forge.cli import cmd_stats

        # Use just the PRD stage
        partial_state = {
            **checkpoint_with_stats,
            "stats_stages": {
                "prd": checkpoint_with_stats["stats_stages"]["prd"],
            },
        }
        args = argparse.Namespace(ticket="INT-100", json=True)

        with patch(
            "forge.orchestrator.checkpointer.get_checkpoint_state",
            new=AsyncMock(return_value=partial_state),
        ):
            await cmd_stats(args)

        data = json.loads(capsys.readouterr().out)
        assert "prd" in data["stages"]
        assert "spec" not in data["stages"]

    @pytest.mark.asyncio
    async def test_jira_stats_multiple_pr_urls_in_comment(
        self, worker: OrchestratorWorker, checkpoint_completed
    ):
        """Stats comment for completed workflow includes PR URLs section."""
        message = _make_jira_message("INT-105", "/forge stats")
        mock_jira = _make_mock_jira()

        with patch("forge.orchestrator.worker.JiraClient", return_value=mock_jira):
            await worker._handle_resume_event(message, checkpoint_completed)

        comment_body = mock_jira.add_comment.call_args[0][1]
        # The formatter includes PR URLs when they are present
        assert "github.com" in comment_body or "pull" in comment_body.lower()
