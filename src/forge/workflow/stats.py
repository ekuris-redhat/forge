"""Statistics tracking data structures for workflow execution.

This module defines the TypedDicts used to capture per-stage metrics and
overall workflow outcome data, as required by SC-001. It also exports
canonical stage-name constants used by recording and formatting code to
ensure consistency across the codebase.
"""

from typing import TypedDict

# ---------------------------------------------------------------------------
# Workflow stage constants
# ---------------------------------------------------------------------------
# These string constants are the canonical identifiers for each named stage
# that is tracked in workflow statistics. Use these constants everywhere
# instead of bare strings so that typos are caught at import time.

# Feature workflow stages
STAGE_PRD = "prd"
STAGE_SPEC = "spec"
STAGE_EPICS = "epics"
STAGE_TASKS = "tasks"
STAGE_IMPLEMENTATION = "implementation"
STAGE_CI = "ci"
STAGE_REVIEW = "review"

# Bug workflow stages
STAGE_TRIAGE = "triage"
STAGE_RCA = "rca"
STAGE_PLANNING = "planning"

# Ordered stage lists used by formatting code to display stages in the
# canonical sequence defined by the specification.

#: Stages for the Feature workflow, in display order.
ALL_FEATURE_STAGES: list[str] = [
    STAGE_PRD,
    STAGE_SPEC,
    STAGE_EPICS,
    STAGE_TASKS,
    STAGE_IMPLEMENTATION,
    STAGE_CI,
    STAGE_REVIEW,
]

#: Stages for the Bug workflow, in display order.
ALL_BUG_STAGES: list[str] = [
    STAGE_TRIAGE,
    STAGE_RCA,
    STAGE_PLANNING,
    STAGE_IMPLEMENTATION,
    STAGE_CI,
    STAGE_REVIEW,
]


class StageStats(TypedDict, total=False):
    """Per-stage execution metrics captured during workflow execution.

    Each stage in a workflow gets one StageStats entry, keyed by stage name
    in the StatsState.stats_stages mapping. Fields are updated incrementally
    as the stage progresses and finalised when the stage ends.

    Fields:
        stage_name: Canonical name of the workflow stage (e.g. "implement").
        iteration_count: Number of times this stage has been (re-)entered,
            including retries and revision loops.
        machine_time_seconds: Wall-clock seconds spent executing automated work
            (LLM calls, tool calls, CI waiting, etc.) — i.e. time the system
            was actively doing something.
        human_time_seconds: Wall-clock seconds the workflow was paused waiting
            for human input (approval gates, revision requests, Q&A).
        input_tokens: Cumulative LLM prompt tokens consumed by this stage.
        output_tokens: Cumulative LLM completion tokens produced by this stage.
        started_at: ISO-8601 timestamp when the stage first started, or None
            if the stage has not yet been entered.
        ended_at: ISO-8601 timestamp when the stage finished (either completed
            or abandoned), or None if it is still in progress.
    """

    stage_name: str
    iteration_count: int
    machine_time_seconds: float
    human_time_seconds: float
    input_tokens: int
    output_tokens: int
    started_at: str | None
    ended_at: str | None


class StatsState(TypedDict, total=False):
    """Mixin TypedDict for workflow-level statistics tracking.

    Intended to be composed into workflow state classes alongside BaseState
    and other integration mixins. All fields are optional (total=False) so
    that existing workflows can adopt the mixin incrementally without
    providing values upfront.

    Outcome values follow the convention:
        "Completed"          — workflow finished successfully.
        "Blocked: <reason>"  — workflow is waiting on an external blocker.
        "Failed: <error>"    — workflow terminated due to an unrecoverable error.

    Fields:
        stats_stages: Mapping from stage name to its StageStats snapshot.
            Updated in-place as each stage starts and ends.
        stats_pr_urls: URLs of all pull requests opened during this workflow
            run (across all repositories).
        stats_ci_cycles: Number of CI fix-attempt cycles that were triggered
            during the implementation phase.
        stats_outcome: Final outcome string for the workflow run, or None while
            the workflow is still in progress.
        stats_outcome_reason: Human-readable elaboration on the outcome (e.g.
            the blocking reason or error message), or None when not applicable.
        stats_comment_posted: True once the summary statistics comment has been
            posted to the Jira ticket (prevents double-posting on retries).
    """

    stats_stages: dict[str, StageStats]
    stats_pr_urls: list[str]
    stats_ci_cycles: int
    stats_outcome: str | None
    stats_outcome_reason: str | None
    stats_comment_posted: bool
