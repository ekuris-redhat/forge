"""Unit tests for StageStats and StatsState TypedDicts."""

from typing import get_type_hints

import pytest


class TestStageStats:
    """Tests for StageStats TypedDict."""

    def test_stage_stats_has_all_required_fields(self):
        """StageStats defines every field required by SC-001."""
        from forge.workflow.stats import StageStats

        hints = get_type_hints(StageStats)

        assert "stage_name" in hints
        assert "iteration_count" in hints
        assert "machine_time_seconds" in hints
        assert "human_time_seconds" in hints
        assert "input_tokens" in hints
        assert "output_tokens" in hints
        assert "started_at" in hints
        assert "ended_at" in hints

    def test_stage_stats_field_types(self):
        """StageStats fields carry the correct type annotations."""
        from forge.workflow.stats import StageStats

        hints = get_type_hints(StageStats)

        assert hints["stage_name"] is str
        assert hints["iteration_count"] is int
        assert hints["machine_time_seconds"] is float
        assert hints["human_time_seconds"] is float
        assert hints["input_tokens"] is int
        assert hints["output_tokens"] is int

    def test_stage_stats_nullable_timestamps(self):
        """started_at and ended_at accept None (X | None convention)."""
        from forge.workflow.stats import StageStats

        hints = get_type_hints(StageStats, include_extras=False)

        # Under Python 3.11+ X | None becomes types.UnionType.
        # str(str | None) is 'str | None' on 3.10+ union syntax.
        started_hint = str(hints["started_at"])
        ended_hint = str(hints["ended_at"])

        assert "str" in started_hint
        assert "None" in started_hint
        assert "str" in ended_hint
        assert "None" in ended_hint

    def test_stage_stats_is_total_false(self):
        """StageStats allows partial initialisation."""
        from forge.workflow.stats import StageStats

        # Should not raise — total=False makes all keys optional
        partial: StageStats = {"stage_name": "implement", "iteration_count": 1}
        assert partial["stage_name"] == "implement"
        assert partial["iteration_count"] == 1

    def test_stage_stats_full_construction(self):
        """StageStats can be constructed with all fields populated."""
        from forge.workflow.stats import StageStats

        stats: StageStats = {
            "stage_name": "implement",
            "iteration_count": 3,
            "machine_time_seconds": 120.5,
            "human_time_seconds": 300.0,
            "input_tokens": 4096,
            "output_tokens": 2048,
            "started_at": "2024-01-01T00:00:00Z",
            "ended_at": "2024-01-01T00:07:00Z",
        }

        assert stats["stage_name"] == "implement"
        assert stats["iteration_count"] == 3
        assert stats["machine_time_seconds"] == 120.5
        assert stats["human_time_seconds"] == 300.0
        assert stats["input_tokens"] == 4096
        assert stats["output_tokens"] == 2048
        assert stats["started_at"] == "2024-01-01T00:00:00Z"
        assert stats["ended_at"] == "2024-01-01T00:07:00Z"

    def test_stage_stats_nullable_timestamps_accept_none(self):
        """started_at and ended_at can be explicitly set to None."""
        from forge.workflow.stats import StageStats

        stats: StageStats = {
            "stage_name": "triage",
            "started_at": None,
            "ended_at": None,
        }
        assert stats["started_at"] is None
        assert stats["ended_at"] is None


class TestStatsState:
    """Tests for StatsState TypedDict mixin."""

    def test_stats_state_has_all_required_fields(self):
        """StatsState defines all workflow-level statistics fields."""
        from forge.workflow.stats import StatsState

        hints = get_type_hints(StatsState)

        assert "stats_stages" in hints
        assert "stats_pr_urls" in hints
        assert "stats_ci_cycles" in hints
        assert "stats_outcome" in hints
        assert "stats_outcome_reason" in hints
        assert "stats_comment_posted" in hints

    def test_stats_state_is_total_false(self):
        """StatsState allows partial initialisation."""
        from forge.workflow.stats import StatsState

        partial: StatsState = {"stats_ci_cycles": 0}
        assert partial["stats_ci_cycles"] == 0

    def test_stats_state_nullable_outcome_fields(self):
        """stats_outcome and stats_outcome_reason accept None."""
        from forge.workflow.stats import StatsState

        hints = get_type_hints(StatsState, include_extras=False)

        outcome_hint = str(hints["stats_outcome"])
        reason_hint = str(hints["stats_outcome_reason"])

        assert "str" in outcome_hint
        assert "None" in outcome_hint
        assert "str" in reason_hint
        assert "None" in reason_hint

    def test_stats_state_full_construction(self):
        """StatsState can be constructed with all fields populated."""
        from forge.workflow.stats import StageStats, StatsState

        stage: StageStats = {
            "stage_name": "implement",
            "iteration_count": 2,
            "machine_time_seconds": 60.0,
            "human_time_seconds": 0.0,
            "input_tokens": 1000,
            "output_tokens": 500,
            "started_at": "2024-01-01T00:00:00Z",
            "ended_at": "2024-01-01T00:01:00Z",
        }

        state: StatsState = {
            "stats_stages": {"implement": stage},
            "stats_pr_urls": ["https://github.com/org/repo/pull/42"],
            "stats_ci_cycles": 1,
            "stats_outcome": "Completed",
            "stats_outcome_reason": None,
            "stats_comment_posted": True,
        }

        assert state["stats_stages"]["implement"]["stage_name"] == "implement"
        assert state["stats_pr_urls"] == ["https://github.com/org/repo/pull/42"]
        assert state["stats_ci_cycles"] == 1
        assert state["stats_outcome"] == "Completed"
        assert state["stats_outcome_reason"] is None
        assert state["stats_comment_posted"] is True

    @pytest.mark.parametrize(
        "outcome",
        [
            "Completed",
            "Blocked: waiting for human approval",
            "Failed: unrecoverable CI failure",
        ],
    )
    def test_stats_state_valid_outcome_values(self, outcome: str):
        """stats_outcome accepts the three documented outcome patterns."""
        from forge.workflow.stats import StatsState

        state: StatsState = {"stats_outcome": outcome}
        assert state["stats_outcome"] == outcome

    def test_stats_state_comment_posted_defaults_pattern(self):
        """stats_comment_posted is a bool field."""
        from forge.workflow.stats import StatsState

        hints = get_type_hints(StatsState)
        assert hints["stats_comment_posted"] is bool

    def test_stats_stages_is_dict_of_stage_stats(self):
        """stats_stages maps string keys to StageStats dicts."""
        from forge.workflow.stats import StageStats, StatsState

        s1: StageStats = {"stage_name": "triage", "iteration_count": 1}
        s2: StageStats = {"stage_name": "implement", "iteration_count": 3}

        state: StatsState = {"stats_stages": {"triage": s1, "implement": s2}}
        assert len(state["stats_stages"]) == 2
        assert state["stats_stages"]["triage"]["stage_name"] == "triage"
        assert state["stats_stages"]["implement"]["iteration_count"] == 3


class TestStatsStateExportedFromPackage:
    """Verify the new types are accessible via the workflow package."""

    def test_stage_stats_importable_from_workflow(self):
        """StageStats is exported from forge.workflow."""
        from forge.workflow import StageStats  # noqa: F401

    def test_stats_state_importable_from_workflow(self):
        """StatsState is exported from forge.workflow."""
        from forge.workflow import StatsState  # noqa: F401

    def test_stats_state_importable_from_base(self):
        """StatsState is importable via forge.workflow.base (re-exported)."""
        from forge.workflow.base import StatsState  # noqa: F401
