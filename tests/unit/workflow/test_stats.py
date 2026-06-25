"""Unit tests for StageStats, StatsState TypedDicts, and stage constants."""

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

        assert "stage_timestamps" in hints
        assert "stats_pr_urls" in hints
        assert "stats_ci_cycles" in hints
        assert "workflow_outcome" in hints
        assert "stats_outcome_reason" in hints
        assert "stats_comment_posted" in hints

    def test_stats_state_is_total_false(self):
        """StatsState allows partial initialisation."""
        from forge.workflow.stats import StatsState

        partial: StatsState = {"stats_ci_cycles": 0}
        assert partial["stats_ci_cycles"] == 0

    def test_stats_state_nullable_outcome_fields(self):
        """workflow_outcome and stats_outcome_reason accept None."""
        from forge.workflow.stats import StatsState

        hints = get_type_hints(StatsState, include_extras=False)

        outcome_hint = str(hints["workflow_outcome"])
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
            "stage_timestamps": {"implement": stage},
            "stats_pr_urls": ["https://github.com/org/repo/pull/42"],
            "stats_ci_cycles": 1,
            "workflow_outcome": "Completed",
            "stats_outcome_reason": None,
            "stats_comment_posted": True,
        }

        assert state["stage_timestamps"]["implement"]["stage_name"] == "implement"
        assert state["stats_pr_urls"] == ["https://github.com/org/repo/pull/42"]
        assert state["stats_ci_cycles"] == 1
        assert state["workflow_outcome"] == "Completed"
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
        """workflow_outcome accepts the three documented outcome patterns."""
        from forge.workflow.stats import StatsState

        state: StatsState = {"workflow_outcome": outcome}
        assert state["workflow_outcome"] == outcome

    def test_stats_state_comment_posted_defaults_pattern(self):
        """stats_comment_posted is a bool field."""
        from forge.workflow.stats import StatsState

        hints = get_type_hints(StatsState)
        assert hints["stats_comment_posted"] is bool

    def test_stage_timestamps_is_dict_of_stage_stats(self):
        """stage_timestamps maps string keys to StageStats dicts."""
        from forge.workflow.stats import StageStats, StatsState

        s1: StageStats = {"stage_name": "triage", "iteration_count": 1}
        s2: StageStats = {"stage_name": "implement", "iteration_count": 3}

        state: StatsState = {"stage_timestamps": {"triage": s1, "implement": s2}}
        assert len(state["stage_timestamps"]) == 2
        assert state["stage_timestamps"]["triage"]["stage_name"] == "triage"
        assert state["stage_timestamps"]["implement"]["iteration_count"] == 3


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


class TestStageConstants:
    """Tests for workflow stage name constants and ordered stage lists."""

    # ------------------------------------------------------------------
    # Individual constant values
    # ------------------------------------------------------------------

    def test_stage_prd_value(self):
        from forge.workflow.stats import STAGE_PRD

        assert STAGE_PRD == "prd"

    def test_stage_spec_value(self):
        from forge.workflow.stats import STAGE_SPEC

        assert STAGE_SPEC == "spec"

    def test_stage_epics_value(self):
        from forge.workflow.stats import STAGE_EPICS

        assert STAGE_EPICS == "epics"

    def test_stage_tasks_value(self):
        from forge.workflow.stats import STAGE_TASKS

        assert STAGE_TASKS == "tasks"

    def test_stage_implementation_value(self):
        from forge.workflow.stats import STAGE_IMPLEMENTATION

        assert STAGE_IMPLEMENTATION == "implementation"

    def test_stage_ci_value(self):
        from forge.workflow.stats import STAGE_CI

        assert STAGE_CI == "ci"

    def test_stage_review_value(self):
        from forge.workflow.stats import STAGE_REVIEW

        assert STAGE_REVIEW == "review"

    def test_stage_rca_value(self):
        from forge.workflow.stats import STAGE_RCA

        assert STAGE_RCA == "rca"

    def test_stage_triage_value(self):
        from forge.workflow.stats import STAGE_TRIAGE

        assert STAGE_TRIAGE == "triage"

    def test_stage_planning_value(self):
        from forge.workflow.stats import STAGE_PLANNING

        assert STAGE_PLANNING == "planning"

    # ------------------------------------------------------------------
    # ALL_FEATURE_STAGES list
    # ------------------------------------------------------------------

    def test_all_feature_stages_is_list(self):
        """ALL_FEATURE_STAGES is a list of strings."""
        from forge.workflow.stats import ALL_FEATURE_STAGES

        assert isinstance(ALL_FEATURE_STAGES, list)
        assert all(isinstance(s, str) for s in ALL_FEATURE_STAGES)

    def test_all_feature_stages_length(self):
        """ALL_FEATURE_STAGES contains exactly 7 stages."""
        from forge.workflow.stats import ALL_FEATURE_STAGES

        assert len(ALL_FEATURE_STAGES) == 7

    def test_all_feature_stages_order(self):
        """ALL_FEATURE_STAGES lists stages in the canonical display order."""
        from forge.workflow.stats import (
            ALL_FEATURE_STAGES,
            STAGE_CI,
            STAGE_EPICS,
            STAGE_IMPLEMENTATION,
            STAGE_PRD,
            STAGE_REVIEW,
            STAGE_SPEC,
            STAGE_TASKS,
        )

        assert ALL_FEATURE_STAGES == [
            STAGE_PRD,
            STAGE_SPEC,
            STAGE_EPICS,
            STAGE_TASKS,
            STAGE_IMPLEMENTATION,
            STAGE_CI,
            STAGE_REVIEW,
        ]

    def test_all_feature_stages_completeness(self):
        """ALL_FEATURE_STAGES contains every expected Feature stage."""
        from forge.workflow.stats import (
            ALL_FEATURE_STAGES,
            STAGE_CI,
            STAGE_EPICS,
            STAGE_IMPLEMENTATION,
            STAGE_PRD,
            STAGE_REVIEW,
            STAGE_SPEC,
            STAGE_TASKS,
        )

        expected = {STAGE_PRD, STAGE_SPEC, STAGE_EPICS, STAGE_TASKS, STAGE_IMPLEMENTATION, STAGE_CI, STAGE_REVIEW}
        assert set(ALL_FEATURE_STAGES) == expected

    # ------------------------------------------------------------------
    # ALL_BUG_STAGES list
    # ------------------------------------------------------------------

    def test_all_bug_stages_is_list(self):
        """ALL_BUG_STAGES is a list of strings."""
        from forge.workflow.stats import ALL_BUG_STAGES

        assert isinstance(ALL_BUG_STAGES, list)
        assert all(isinstance(s, str) for s in ALL_BUG_STAGES)

    def test_all_bug_stages_length(self):
        """ALL_BUG_STAGES contains exactly 6 stages."""
        from forge.workflow.stats import ALL_BUG_STAGES

        assert len(ALL_BUG_STAGES) == 6

    def test_all_bug_stages_order(self):
        """ALL_BUG_STAGES lists stages in the canonical display order."""
        from forge.workflow.stats import (
            ALL_BUG_STAGES,
            STAGE_CI,
            STAGE_IMPLEMENTATION,
            STAGE_PLANNING,
            STAGE_RCA,
            STAGE_REVIEW,
            STAGE_TRIAGE,
        )

        assert ALL_BUG_STAGES == [
            STAGE_TRIAGE,
            STAGE_RCA,
            STAGE_PLANNING,
            STAGE_IMPLEMENTATION,
            STAGE_CI,
            STAGE_REVIEW,
        ]

    def test_all_bug_stages_completeness(self):
        """ALL_BUG_STAGES contains every expected Bug stage."""
        from forge.workflow.stats import (
            ALL_BUG_STAGES,
            STAGE_CI,
            STAGE_IMPLEMENTATION,
            STAGE_PLANNING,
            STAGE_RCA,
            STAGE_REVIEW,
            STAGE_TRIAGE,
        )

        expected = {STAGE_TRIAGE, STAGE_RCA, STAGE_PLANNING, STAGE_IMPLEMENTATION, STAGE_CI, STAGE_REVIEW}
        assert set(ALL_BUG_STAGES) == expected

    # ------------------------------------------------------------------
    # Export verification
    # ------------------------------------------------------------------

    def test_constants_importable_from_stats_module(self):
        """All stage constants and lists are importable from forge.workflow.stats."""
        from forge.workflow.stats import (  # noqa: F401
            ALL_BUG_STAGES,
            ALL_FEATURE_STAGES,
            STAGE_CI,
            STAGE_EPICS,
            STAGE_IMPLEMENTATION,
            STAGE_PLANNING,
            STAGE_PRD,
            STAGE_RCA,
            STAGE_REVIEW,
            STAGE_SPEC,
            STAGE_TASKS,
            STAGE_TRIAGE,
        )
