"""Unit tests for forge.stats.retrieval.

All checkpoint access is mocked; no Redis or LangGraph connections are
made.  Tests cover the public API (get_workflow_stats and
get_workflow_stats_or_error) as well as the internal _extract_stats helper.
"""

from unittest.mock import AsyncMock, patch

import pytest

from forge.stats.retrieval import (
    WorkflowStats,
    _extract_stats,
    get_workflow_stats,
    get_workflow_stats_or_error,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

_TICKET = "AISOS-123"


def _make_stage(
    *,
    stage_name: str = "prd",
    iteration_count: int = 1,
    machine_time_seconds: float = 60.0,
    human_time_seconds: float = 0.0,
    input_tokens: int = 1000,
    output_tokens: int = 500,
    started_at: str | None = "2024-01-01T00:00:00+00:00",
    ended_at: str | None = "2024-01-01T00:01:00+00:00",
) -> dict:
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


def _full_state(**overrides) -> dict:
    """Return a well-formed checkpoint state dict with stats fields."""
    base: dict = {
        "ticket_key": _TICKET,
        "ticket_type": "Feature",
        "current_node": "prd_approval_gate",
        "is_paused": False,
        "is_blocked": False,
        "last_error": None,
        "feedback_comment": None,
        "context": {},
        "stats_stages": {
            "prd": _make_stage(stage_name="prd"),
        },
        "stats_pr_urls": ["https://github.com/org/repo/pull/1"],
        "stats_ci_cycles": 2,
        "stats_outcome": "Completed",
        "stats_outcome_reason": None,
        "stats_comment_posted": True,
        "workflow_run_id": "abc-123",
    }
    base.update(overrides)
    return base


def _patch_checkpoint(return_value):
    """Patch get_checkpoint_state in the retrieval module."""
    return patch(
        "forge.stats.retrieval.get_checkpoint_state",
        new=AsyncMock(return_value=return_value),
    )


# ---------------------------------------------------------------------------
# WorkflowStats dataclass
# ---------------------------------------------------------------------------


class TestWorkflowStatsDataclass:
    """Tests for the WorkflowStats dataclass itself."""

    def test_default_construction(self):
        """WorkflowStats can be constructed with only ticket_key."""
        ws = WorkflowStats(ticket_key=_TICKET)
        assert ws.ticket_key == _TICKET
        assert ws.stages == {}
        assert ws.pr_urls == []
        assert ws.ci_cycles == 0
        assert ws.outcome is None
        assert ws.outcome_reason is None
        assert ws.comment_posted is False
        assert ws.workflow_run_id == ""

    def test_full_construction(self):
        """WorkflowStats accepts all fields."""
        stage = _make_stage()
        ws = WorkflowStats(
            ticket_key=_TICKET,
            stages={"prd": stage},
            pr_urls=["https://github.com/org/repo/pull/1"],
            ci_cycles=3,
            outcome="Completed",
            outcome_reason=None,
            comment_posted=True,
            workflow_run_id="uuid-xyz",
        )
        assert ws.stages == {"prd": stage}
        assert ws.pr_urls == ["https://github.com/org/repo/pull/1"]
        assert ws.ci_cycles == 3
        assert ws.outcome == "Completed"
        assert ws.comment_posted is True
        assert ws.workflow_run_id == "uuid-xyz"

    def test_stages_default_is_independent_per_instance(self):
        """Each WorkflowStats instance gets its own stages dict (not shared)."""
        ws1 = WorkflowStats(ticket_key="AISOS-1")
        ws2 = WorkflowStats(ticket_key="AISOS-2")
        ws1.stages["prd"] = _make_stage()
        assert "prd" not in ws2.stages

    def test_pr_urls_default_is_independent_per_instance(self):
        """Each WorkflowStats instance gets its own pr_urls list (not shared)."""
        ws1 = WorkflowStats(ticket_key="AISOS-1")
        ws2 = WorkflowStats(ticket_key="AISOS-2")
        ws1.pr_urls.append("https://example.com")
        assert ws2.pr_urls == []


# ---------------------------------------------------------------------------
# _extract_stats internal helper
# ---------------------------------------------------------------------------


class TestExtractStats:
    """Tests for the _extract_stats helper."""

    def test_returns_none_when_stats_stages_absent(self):
        """Returns None when stats_stages key is missing (legacy workflow)."""
        state = {
            "ticket_key": _TICKET,
            "ticket_type": "Feature",
            "current_node": "prd_generation",
        }
        result = _extract_stats(_TICKET, state)
        assert result is None

    def test_returns_workflow_stats_with_stages_present(self):
        """Returns WorkflowStats when stats_stages key is present."""
        state = _full_state()
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert isinstance(result, WorkflowStats)

    def test_ticket_key_is_passed_through(self):
        """The ticket_key from the argument is stored on the result."""
        state = _full_state()
        result = _extract_stats("MYPROJ-999", state)
        assert result is not None
        assert result.ticket_key == "MYPROJ-999"

    def test_stages_are_extracted(self):
        """stages dict contains the stages from the checkpoint."""
        stage = _make_stage(stage_name="prd")
        state = _full_state(stats_stages={"prd": stage})
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.stages == {"prd": stage}

    def test_empty_stages_dict_is_valid(self):
        """An empty stats_stages dict is returned as an empty stages dict."""
        state = _full_state(stats_stages={})
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.stages == {}

    def test_pr_urls_are_extracted(self):
        """pr_urls are extracted from stats_pr_urls."""
        urls = ["https://github.com/org/repo/pull/1", "https://github.com/org/repo/pull/2"]
        state = _full_state(stats_pr_urls=urls)
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.pr_urls == urls

    def test_missing_pr_urls_defaults_to_empty_list(self):
        """Missing stats_pr_urls key yields an empty pr_urls list."""
        state = _full_state()
        del state["stats_pr_urls"]
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.pr_urls == []

    def test_null_pr_urls_defaults_to_empty_list(self):
        """stats_pr_urls=None is treated as empty list."""
        state = _full_state(stats_pr_urls=None)
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.pr_urls == []

    def test_ci_cycles_extracted(self):
        """ci_cycles is extracted from stats_ci_cycles."""
        state = _full_state(stats_ci_cycles=5)
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.ci_cycles == 5

    def test_missing_ci_cycles_defaults_to_zero(self):
        """Missing stats_ci_cycles yields ci_cycles=0."""
        state = _full_state()
        del state["stats_ci_cycles"]
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.ci_cycles == 0

    def test_null_ci_cycles_defaults_to_zero(self):
        """stats_ci_cycles=None yields ci_cycles=0."""
        state = _full_state(stats_ci_cycles=None)
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.ci_cycles == 0

    def test_outcome_extracted(self):
        """outcome is extracted from stats_outcome."""
        state = _full_state(stats_outcome="Completed")
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.outcome == "Completed"

    def test_outcome_none_when_missing(self):
        """Missing stats_outcome yields outcome=None."""
        state = _full_state()
        del state["stats_outcome"]
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.outcome is None

    def test_outcome_reason_extracted(self):
        """outcome_reason is extracted from stats_outcome_reason."""
        state = _full_state(stats_outcome_reason="Deployment gate failed")
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.outcome_reason == "Deployment gate failed"

    def test_comment_posted_true(self):
        """comment_posted is True when stats_comment_posted=True."""
        state = _full_state(stats_comment_posted=True)
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.comment_posted is True

    def test_comment_posted_false_by_default(self):
        """Missing stats_comment_posted yields comment_posted=False."""
        state = _full_state()
        del state["stats_comment_posted"]
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.comment_posted is False

    def test_workflow_run_id_extracted(self):
        """workflow_run_id is extracted from the state."""
        state = _full_state(workflow_run_id="run-uuid-4567")
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.workflow_run_id == "run-uuid-4567"

    def test_missing_workflow_run_id_defaults_to_empty_string(self):
        """Missing workflow_run_id yields empty string (pre-idempotency checkpoint)."""
        state = _full_state()
        del state["workflow_run_id"]
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.workflow_run_id == ""

    def test_malformed_stages_dict_treated_as_empty(self):
        """Malformed stats_stages (not a dict) is treated as empty dict."""
        state = _full_state(stats_stages="not-a-dict")
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.stages == {}

    def test_malformed_pr_urls_treated_as_empty(self):
        """Malformed stats_pr_urls (not a list) is treated as empty list."""
        state = _full_state(stats_pr_urls="not-a-list")
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.pr_urls == []

    def test_partial_state_in_progress_workflow(self):
        """Partial stats for an in-progress workflow are returned as-is."""
        stage = _make_stage(stage_name="prd", ended_at=None)
        state = _full_state(
            stats_stages={"prd": stage},
            stats_outcome=None,
            stats_outcome_reason=None,
            stats_comment_posted=False,
        )
        result = _extract_stats(_TICKET, state)
        assert result is not None
        assert result.stages["prd"]["ended_at"] is None
        assert result.outcome is None
        assert result.comment_posted is False


# ---------------------------------------------------------------------------
# get_workflow_stats
# ---------------------------------------------------------------------------


class TestGetWorkflowStats:
    """Tests for the public get_workflow_stats() function."""

    @pytest.mark.asyncio
    async def test_returns_none_when_no_checkpoint(self):
        """Returns None when get_checkpoint_state returns None."""
        with _patch_checkpoint(None):
            result = await get_workflow_stats(_TICKET)
        assert result is None

    @pytest.mark.asyncio
    async def test_returns_workflow_stats_for_valid_checkpoint(self):
        """Returns WorkflowStats for a checkpoint with stats data."""
        state = _full_state()
        with _patch_checkpoint(state):
            result = await get_workflow_stats(_TICKET)
        assert result is not None
        assert isinstance(result, WorkflowStats)

    @pytest.mark.asyncio
    async def test_ticket_key_propagated(self):
        """WorkflowStats.ticket_key matches the requested ticket key."""
        state = _full_state()
        with _patch_checkpoint(state):
            result = await get_workflow_stats("MYPROJ-42")
        assert result is not None
        assert result.ticket_key == "MYPROJ-42"

    @pytest.mark.asyncio
    async def test_returns_none_for_legacy_checkpoint_without_stats(self):
        """Returns None when checkpoint exists but has no stats_stages key."""
        legacy_state = {
            "ticket_key": _TICKET,
            "ticket_type": "Feature",
            "current_node": "done",
        }
        with _patch_checkpoint(legacy_state):
            result = await get_workflow_stats(_TICKET)
        assert result is None

    @pytest.mark.asyncio
    async def test_stages_populated_from_checkpoint(self):
        """stages dict contains the stages stored in the checkpoint."""
        stage = _make_stage(stage_name="spec")
        state = _full_state(stats_stages={"spec": stage})
        with _patch_checkpoint(state):
            result = await get_workflow_stats(_TICKET)
        assert result is not None
        assert "spec" in result.stages

    @pytest.mark.asyncio
    async def test_empty_stages_valid(self):
        """Workflow with empty stats_stages is returned (not treated as missing)."""
        state = _full_state(stats_stages={})
        with _patch_checkpoint(state):
            result = await get_workflow_stats(_TICKET)
        assert result is not None
        assert result.stages == {}

    @pytest.mark.asyncio
    async def test_partial_in_progress_workflow_returned(self):
        """Partial stats for an in-progress workflow are returned with available data."""
        stage = _make_stage(ended_at=None)
        state = _full_state(
            stats_stages={"prd": stage},
            stats_outcome=None,
            stats_pr_urls=[],
            stats_ci_cycles=0,
        )
        with _patch_checkpoint(state):
            result = await get_workflow_stats(_TICKET)
        assert result is not None
        assert result.outcome is None
        assert result.stages["prd"]["ended_at"] is None

    @pytest.mark.asyncio
    async def test_calls_get_checkpoint_state_with_ticket_key(self):
        """get_checkpoint_state is called with the supplied ticket_key."""
        state = _full_state()
        mock = AsyncMock(return_value=state)
        with patch("forge.stats.retrieval.get_checkpoint_state", new=mock):
            await get_workflow_stats("PROJ-55")
        mock.assert_called_once_with("PROJ-55")

    @pytest.mark.asyncio
    async def test_pr_urls_extracted_correctly(self):
        """pr_urls from the checkpoint appear in the returned WorkflowStats."""
        urls = ["https://github.com/org/repo/pull/10"]
        state = _full_state(stats_pr_urls=urls)
        with _patch_checkpoint(state):
            result = await get_workflow_stats(_TICKET)
        assert result is not None
        assert result.pr_urls == urls

    @pytest.mark.asyncio
    async def test_ci_cycles_extracted_correctly(self):
        """ci_cycles from the checkpoint appear in the returned WorkflowStats."""
        state = _full_state(stats_ci_cycles=7)
        with _patch_checkpoint(state):
            result = await get_workflow_stats(_TICKET)
        assert result is not None
        assert result.ci_cycles == 7

    @pytest.mark.asyncio
    async def test_propagates_exception_from_checkpointer(self):
        """Exceptions from get_checkpoint_state are not swallowed."""
        with patch(
            "forge.stats.retrieval.get_checkpoint_state",
            new=AsyncMock(side_effect=ConnectionError("Redis down")),
        ), pytest.raises(ConnectionError):
            await get_workflow_stats(_TICKET)


# ---------------------------------------------------------------------------
# get_workflow_stats_or_error
# ---------------------------------------------------------------------------


class TestGetWorkflowStatsOrError:
    """Tests for the public get_workflow_stats_or_error() function."""

    @pytest.mark.asyncio
    async def test_returns_stats_and_none_error_on_success(self):
        """Returns (WorkflowStats, None) when stats are found."""
        state = _full_state()
        with _patch_checkpoint(state):
            stats, error = await get_workflow_stats_or_error(_TICKET)
        assert stats is not None
        assert error is None

    @pytest.mark.asyncio
    async def test_returns_none_stats_and_error_when_no_checkpoint(self):
        """Returns (None, error_str) when no checkpoint exists."""
        with _patch_checkpoint(None):
            stats, error = await get_workflow_stats_or_error(_TICKET)
        assert stats is None
        assert error is not None

    @pytest.mark.asyncio
    async def test_error_message_contains_ticket_key_for_missing(self):
        """Error message mentions the ticket key when no checkpoint is found."""
        with _patch_checkpoint(None):
            _stats, error = await get_workflow_stats_or_error("AISOS-999")
        assert error is not None
        assert "AISOS-999" in error

    @pytest.mark.asyncio
    async def test_returns_none_stats_when_legacy_checkpoint(self):
        """Returns (None, error_str) for legacy checkpoints without stats."""
        legacy_state = {
            "ticket_key": _TICKET,
            "ticket_type": "Feature",
            "current_node": "done",
        }
        with _patch_checkpoint(legacy_state):
            stats, error = await get_workflow_stats_or_error(_TICKET)
        assert stats is None
        assert error is not None

    @pytest.mark.asyncio
    async def test_error_message_is_display_ready_string(self):
        """Error message is a non-empty string when stats are unavailable."""
        with _patch_checkpoint(None):
            _stats, error = await get_workflow_stats_or_error(_TICKET)
        assert isinstance(error, str)
        assert len(error) > 0

    @pytest.mark.asyncio
    async def test_exception_from_checkpointer_returns_error_not_raises(self):
        """ConnectionError from get_checkpoint_state yields (None, error_str)."""
        with patch(
            "forge.stats.retrieval.get_checkpoint_state",
            new=AsyncMock(side_effect=ConnectionError("Redis unavailable")),
        ):
            stats, error = await get_workflow_stats_or_error(_TICKET)
        assert stats is None
        assert error is not None

    @pytest.mark.asyncio
    async def test_error_message_contains_ticket_key_on_exception(self):
        """Error message mentions the ticket key when an exception occurs."""
        with patch(
            "forge.stats.retrieval.get_checkpoint_state",
            new=AsyncMock(side_effect=RuntimeError("unexpected")),
        ):
            _stats, error = await get_workflow_stats_or_error("MYPROJ-77")
        assert error is not None
        assert "MYPROJ-77" in error

    @pytest.mark.asyncio
    async def test_runtime_error_does_not_propagate(self):
        """RuntimeError from checkpointer is caught; no exception raised."""
        with patch(
            "forge.stats.retrieval.get_checkpoint_state",
            new=AsyncMock(side_effect=RuntimeError("oops")),
        ):
            # Should not raise
            result = await get_workflow_stats_or_error(_TICKET)
        assert result[0] is None

    @pytest.mark.asyncio
    async def test_exactly_one_element_is_none(self):
        """Exactly one of (stats, error) is always None on success."""
        state = _full_state()
        with _patch_checkpoint(state):
            stats, error = await get_workflow_stats_or_error(_TICKET)
        # On success: stats is set, error is None
        assert (stats is None) != (error is None)

    @pytest.mark.asyncio
    async def test_exactly_one_element_is_none_on_failure(self):
        """Exactly one of (stats, error) is always None on failure."""
        with _patch_checkpoint(None):
            stats, error = await get_workflow_stats_or_error(_TICKET)
        # On failure: stats is None, error is set
        assert (stats is None) != (error is None)

    @pytest.mark.asyncio
    async def test_stats_fields_correct_on_success(self):
        """Returned WorkflowStats has correct fields populated."""
        state = _full_state(
            stats_outcome="Completed",
            stats_ci_cycles=3,
            stats_pr_urls=["https://github.com/org/repo/pull/5"],
        )
        with _patch_checkpoint(state):
            stats, _error = await get_workflow_stats_or_error(_TICKET)
        assert stats is not None
        assert stats.outcome == "Completed"
        assert stats.ci_cycles == 3
        assert stats.pr_urls == ["https://github.com/org/repo/pull/5"]


# ---------------------------------------------------------------------------
# Import paths
# ---------------------------------------------------------------------------


class TestImportPaths:
    """Verify the public API is importable from the package root."""

    def test_workflow_stats_importable_from_package(self):
        """WorkflowStats is importable from forge.stats."""
        from forge.stats import WorkflowStats as WS  # noqa: F401

        assert WS is WorkflowStats

    def test_get_workflow_stats_importable_from_package(self):
        """get_workflow_stats is importable from forge.stats."""
        from forge.stats import get_workflow_stats as gws

        assert gws is get_workflow_stats

    def test_get_workflow_stats_or_error_importable_from_package(self):
        """get_workflow_stats_or_error is importable from forge.stats."""
        from forge.stats import get_workflow_stats_or_error as gwsoe

        assert gwsoe is get_workflow_stats_or_error
