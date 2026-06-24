"""Unit tests for the post_terminal_stats node (stats_posting.py).

Tests cover:
- Outcome classification for Completed / Blocked / Failed states
- Outcome detail extraction (last_error, block reason, stats_outcome_reason)
- Integration with post_stats_comment and ensure_stats_is_final_comment
- Handling of both FeatureState and BugState
- Non-blocking behaviour on Jira API failures
"""

from unittest.mock import AsyncMock, patch

import pytest

from forge.workflow.bug.state import create_initial_bug_state
from forge.workflow.feature.state import create_initial_feature_state
from forge.workflow.nodes.stats_posting import (
    _determine_outcome,
    _extract_outcome_detail,
    post_terminal_stats,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def feature_state():
    """Minimal FeatureState with no terminal conditions set."""
    return create_initial_feature_state("FEAT-1")


@pytest.fixture()
def bug_state():
    """Minimal BugState with no terminal conditions set."""
    return create_initial_bug_state("BUG-1")


# ---------------------------------------------------------------------------
# _determine_outcome tests
# ---------------------------------------------------------------------------


class TestDetermineOutcome:
    """Tests for the _determine_outcome helper."""

    def test_completed_when_no_flags_set(self, feature_state):
        """Returns 'Completed' when no error or block flag is set."""
        assert _determine_outcome(feature_state) == "Completed"

    def test_failed_when_last_error_set(self, feature_state):
        """Returns 'Failed' when last_error contains a message."""
        feature_state["last_error"] = "Something went wrong"
        assert _determine_outcome(feature_state) == "Failed"

    def test_blocked_when_is_blocked_true(self, feature_state):
        """Returns 'Blocked' when is_blocked flag is True."""
        feature_state["is_blocked"] = True
        assert _determine_outcome(feature_state) == "Blocked"

    def test_blocked_takes_precedence_over_last_error(self, feature_state):
        """'Blocked' takes precedence over 'Failed' when both flags are set."""
        feature_state["is_blocked"] = True
        feature_state["last_error"] = "Some error"
        assert _determine_outcome(feature_state) == "Blocked"

    def test_existing_stats_outcome_returned_directly(self, feature_state):
        """If stats_outcome is already set, it is returned without re-deriving."""
        feature_state["stats_outcome"] = "Completed"
        feature_state["last_error"] = "Some error"  # would normally produce 'Failed'
        assert _determine_outcome(feature_state) == "Completed"

    def test_existing_stats_outcome_blocked(self, feature_state):
        """Pre-set stats_outcome of 'Blocked' is honoured directly."""
        feature_state["stats_outcome"] = "Blocked"
        assert _determine_outcome(feature_state) == "Blocked"

    def test_completed_for_bug_state(self, bug_state):
        """Bug workflow: returns 'Completed' when no error or block."""
        assert _determine_outcome(bug_state) == "Completed"

    def test_failed_for_bug_state(self, bug_state):
        """Bug workflow: returns 'Failed' when last_error is set."""
        bug_state["last_error"] = "container exited with code 1"
        assert _determine_outcome(bug_state) == "Failed"

    def test_blocked_for_bug_state(self, bug_state):
        """Bug workflow: returns 'Blocked' when is_blocked is True."""
        bug_state["is_blocked"] = True
        assert _determine_outcome(bug_state) == "Blocked"


# ---------------------------------------------------------------------------
# _extract_outcome_detail tests
# ---------------------------------------------------------------------------


class TestExtractOutcomeDetail:
    """Tests for the _extract_outcome_detail helper."""

    def test_completed_returns_none(self, feature_state):
        """Completed outcome has no detail."""
        assert _extract_outcome_detail(feature_state, "Completed") is None

    def test_failed_returns_last_error(self, feature_state):
        """Failed outcome uses last_error as the detail string."""
        feature_state["last_error"] = "NullPointerException in validate()"
        detail = _extract_outcome_detail(feature_state, "Failed")
        assert detail == "NullPointerException in validate()"

    def test_failed_no_last_error_returns_none(self, feature_state):
        """Failed outcome returns None when last_error is not set."""
        assert _extract_outcome_detail(feature_state, "Failed") is None

    def test_blocked_returns_feedback_comment(self, feature_state):
        """Blocked outcome uses feedback_comment as the block reason."""
        feature_state["feedback_comment"] = "Waiting for third-party API key"
        detail = _extract_outcome_detail(feature_state, "Blocked")
        assert detail == "Waiting for third-party API key"

    def test_blocked_no_reason_returns_none(self, feature_state):
        """Blocked outcome returns None when no reason is available."""
        assert _extract_outcome_detail(feature_state, "Blocked") is None

    def test_stats_outcome_reason_takes_precedence(self, feature_state):
        """Pre-recorded stats_outcome_reason overrides derived detail."""
        feature_state["stats_outcome_reason"] = "Pre-recorded reason"
        feature_state["last_error"] = "Some other error"
        detail = _extract_outcome_detail(feature_state, "Failed")
        assert detail == "Pre-recorded reason"

    def test_stats_outcome_reason_for_blocked(self, feature_state):
        """Pre-recorded stats_outcome_reason is used for Blocked outcome too."""
        feature_state["stats_outcome_reason"] = "External dependency unavailable"
        feature_state["feedback_comment"] = "Other comment"
        detail = _extract_outcome_detail(feature_state, "Blocked")
        assert detail == "External dependency unavailable"

    def test_failed_for_bug_state(self, bug_state):
        """Bug workflow: Failed outcome extracts last_error."""
        bug_state["last_error"] = "RCA container timed out"
        assert _extract_outcome_detail(bug_state, "Failed") == "RCA container timed out"


# ---------------------------------------------------------------------------
# post_terminal_stats integration tests
# ---------------------------------------------------------------------------


class TestPostTerminalStats:
    """Tests for the post_terminal_stats async node function."""

    @pytest.mark.asyncio
    async def test_returns_empty_dict(self, feature_state):
        """Node always returns an empty dict (state unchanged)."""
        with (
            patch(
                "forge.workflow.nodes.stats_posting.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ),
            patch(
                "forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment",
                new_callable=AsyncMock,
                return_value=True,
            ),
        ):
            result = await post_terminal_stats(feature_state)

        assert result == {}

    @pytest.mark.asyncio
    async def test_calls_post_stats_comment_with_correct_args(self, feature_state):
        """post_stats_comment is called with ticket_key, state, and derived outcome."""
        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(return_value=True)

        feature_state["last_error"] = "build failed"

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            await post_terminal_stats(feature_state)

        mock_post.assert_awaited_once_with(
            ticket_key="FEAT-1",
            stats=feature_state,
            outcome="Failed",
            outcome_detail="build failed",
        )

    @pytest.mark.asyncio
    async def test_calls_ensure_stats_is_final_comment(self, feature_state):
        """ensure_stats_is_final_comment is called with correct args."""
        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            await post_terminal_stats(feature_state)

        mock_ensure.assert_awaited_once_with(
            ticket_key="FEAT-1",
            stats=feature_state,
            outcome="Completed",
            outcome_detail=None,
        )

    @pytest.mark.asyncio
    async def test_completed_outcome_for_clean_state(self, feature_state):
        """Completed outcome is passed when state has no errors or blocks."""
        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            await post_terminal_stats(feature_state)

        _call_kwargs = mock_post.call_args.kwargs
        assert _call_kwargs["outcome"] == "Completed"
        assert _call_kwargs["outcome_detail"] is None

    @pytest.mark.asyncio
    async def test_blocked_outcome_for_blocked_state(self, feature_state):
        """Blocked outcome is passed when is_blocked is True."""
        feature_state["is_blocked"] = True
        feature_state["feedback_comment"] = "Waiting on legal approval"

        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            await post_terminal_stats(feature_state)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["outcome"] == "Blocked"
        assert call_kwargs["outcome_detail"] == "Waiting on legal approval"

    @pytest.mark.asyncio
    async def test_failed_outcome_for_error_state(self, feature_state):
        """Failed outcome is passed when last_error is set."""
        feature_state["last_error"] = "container exited with code 137"

        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            await post_terminal_stats(feature_state)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["outcome"] == "Failed"
        assert call_kwargs["outcome_detail"] == "container exited with code 137"

    @pytest.mark.asyncio
    async def test_handles_bug_state(self, bug_state):
        """Node works with BugState as well as FeatureState."""
        bug_state["last_error"] = "triage failed"

        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            result = await post_terminal_stats(bug_state)

        assert result == {}
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["ticket_key"] == "BUG-1"
        assert call_kwargs["outcome"] == "Failed"
        assert call_kwargs["outcome_detail"] == "triage failed"

    @pytest.mark.asyncio
    async def test_non_blocking_on_post_stats_failure(self, feature_state):
        """post_stats_comment raising an exception does not propagate."""
        mock_post = AsyncMock(side_effect=RuntimeError("Jira is down"))
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            # Should not raise
            result = await post_terminal_stats(feature_state)

        assert result == {}

    @pytest.mark.asyncio
    async def test_non_blocking_on_ensure_final_comment_failure(self, feature_state):
        """ensure_stats_is_final_comment raising does not propagate."""
        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(side_effect=RuntimeError("network timeout"))

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            result = await post_terminal_stats(feature_state)

        assert result == {}

    @pytest.mark.asyncio
    async def test_non_blocking_when_both_services_fail(self, feature_state):
        """Node returns empty dict even when both posting services raise."""
        mock_post = AsyncMock(side_effect=Exception("boom"))
        mock_ensure = AsyncMock(side_effect=Exception("crash"))

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            result = await post_terminal_stats(feature_state)

        assert result == {}

    @pytest.mark.asyncio
    async def test_skips_posting_when_no_ticket_key(self):
        """Node skips posting gracefully when ticket_key is absent."""
        state_without_key = {"is_blocked": False, "last_error": None}

        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            result = await post_terminal_stats(state_without_key)  # type: ignore[arg-type]

        assert result == {}
        mock_post.assert_not_awaited()
        mock_ensure.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_post_stats_comment_false_does_not_skip_ensure(self, feature_state):
        """ensure_stats_is_final_comment is still called even when post returns False."""
        mock_post = AsyncMock(return_value=False)
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            await post_terminal_stats(feature_state)

        mock_ensure.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_uses_pre_set_stats_outcome(self, feature_state):
        """If stats_outcome is already set in state it is forwarded unchanged."""
        feature_state["stats_outcome"] = "Blocked"
        feature_state["stats_outcome_reason"] = "Awaiting vendor API"
        feature_state["last_error"] = None  # would normally produce 'Completed'

        mock_post = AsyncMock(return_value=True)
        mock_ensure = AsyncMock(return_value=True)

        with (
            patch("forge.workflow.nodes.stats_posting.post_stats_comment", mock_post),
            patch("forge.workflow.nodes.stats_posting.ensure_stats_is_final_comment", mock_ensure),
        ):
            await post_terminal_stats(feature_state)

        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["outcome"] == "Blocked"
        assert call_kwargs["outcome_detail"] == "Awaiting vendor API"
