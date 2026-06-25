"""Utility functions for recording workflow execution statistics.

These helpers are called by workflow nodes to update stats fields in the
LangGraph state. Every function returns a dict suitable for merging into
the state via LangGraph's reducer (partial state updates).

All timestamps are UTC ISO-8601 strings (e.g. "2024-01-01T12:00:00.000000+00:00").
"""

from datetime import UTC, datetime


def _utc_now() -> str:
    """Return the current UTC time as an ISO-8601 string."""
    return datetime.now(UTC).isoformat()


def _get_stage(state: dict, stage_name: str) -> dict:
    """Return a copy of the stage entry, or a zeroed default if absent."""
    stages: dict = state.get("stage_timestamps") or {}
    existing = stages.get(stage_name)
    if existing is None:
        return {
            "stage_name": stage_name,
            "iteration_count": 0,
            "machine_time_seconds": 0.0,
            "human_time_seconds": 0.0,
            "input_tokens": 0,
            "output_tokens": 0,
            "started_at": None,
            "ended_at": None,
            "model_name": None,
        }
    # Return a shallow copy so callers can mutate freely
    return dict(existing)


def record_stage_start(
    state: dict,
    stage_name: str,
    model_name: str | None = None,
) -> dict:
    """Initialize a stage entry in stats_stages with a started_at timestamp.

    If the stage already exists (e.g. a retry), the started_at timestamp is
    updated to now but accumulated metrics are preserved.  iteration_count is
    left as-is; call :func:`increment_revision` to bump it.

    Args:
        state: Current workflow state dict.
        stage_name: Name of the stage being started (e.g. ``"implement"``).
        model_name: Optional name of the LLM model used in this stage
            (e.g. ``"claude-sonnet-4-5@20250929"``).  Pass ``None`` for stages
            that do not invoke an LLM (e.g. CI, review).

    Returns:
        Partial state update dict with ``stage_timestamps`` key.
    """
    stages: dict = dict(state.get("stage_timestamps") or {})
    stage = _get_stage(state, stage_name)
    stage["started_at"] = _utc_now()
    stage["ended_at"] = None  # reset end marker when re-entering
    if model_name is not None:
        stage["model_name"] = model_name
    stages[stage_name] = stage
    return {"stage_timestamps": stages}


def record_stage_end(
    state: dict,
    stage_name: str,
    machine_time: float,
    human_time: float = 0.0,
) -> dict:
    """Mark a stage as ended and accumulate time metrics.

    Time values are *accumulated* (not replaced) so that repeated calls for
    the same stage (e.g. after retries) add up correctly.

    Args:
        state: Current workflow state dict.
        stage_name: Name of the stage that has finished.
        machine_time: Wall-clock seconds of automated work to add.
        human_time: Wall-clock seconds of human-wait time to add (default 0).

    Returns:
        Partial state update dict with ``stage_timestamps`` key.
    """
    stages: dict = dict(state.get("stage_timestamps") or {})
    stage = _get_stage(state, stage_name)
    stage["ended_at"] = _utc_now()
    stage["machine_time_seconds"] = stage.get("machine_time_seconds", 0.0) + machine_time
    stage["human_time_seconds"] = stage.get("human_time_seconds", 0.0) + human_time
    stages[stage_name] = stage
    return {"stage_timestamps": stages}


def record_tokens(
    state: dict,
    stage_name: str,
    input_tokens: int,
    output_tokens: int,
) -> dict:
    """Accumulate LLM token counts for a stage.

    Tokens are *accumulated* (not replaced) so that multiple LLM calls within
    the same stage all contribute to the total.

    Args:
        state: Current workflow state dict.
        stage_name: Name of the stage consuming tokens.
        input_tokens: Number of prompt tokens to add.
        output_tokens: Number of completion tokens to add.

    Returns:
        Partial state update dict with ``stage_timestamps``, ``stage_token_usage``,
        and ``token_usage`` keys.
    """
    stages: dict = dict(state.get("stage_timestamps") or {})
    stage = _get_stage(state, stage_name)
    stage["input_tokens"] = stage.get("input_tokens", 0) + input_tokens
    stage["output_tokens"] = stage.get("output_tokens", 0) + output_tokens
    stages[stage_name] = stage

    # Update per-stage token usage map
    stage_token_usage: dict = dict(state.get("stage_token_usage") or {})
    existing_stage_tokens = stage_token_usage.get(stage_name) or {}
    stage_token_usage[stage_name] = {
        "input_tokens": (existing_stage_tokens.get("input_tokens") or 0) + input_tokens,
        "output_tokens": (existing_stage_tokens.get("output_tokens") or 0) + output_tokens,
    }

    # Update aggregate token usage
    agg: dict = dict(state.get("token_usage") or {})
    agg["input_tokens"] = (agg.get("input_tokens") or 0) + input_tokens
    agg["output_tokens"] = (agg.get("output_tokens") or 0) + output_tokens

    return {
        "stage_timestamps": stages,
        "stage_token_usage": stage_token_usage,
        "token_usage": agg,
    }


def increment_revision(state: dict, stage_name: str) -> dict:
    """Increment the iteration_count for a stage by 1.

    Should be called each time a stage is re-entered due to a revision
    request or retry.

    Args:
        state: Current workflow state dict.
        stage_name: Name of the stage being revised.

    Returns:
        Partial state update dict with ``stage_timestamps`` and
        ``revision_counts`` keys.
    """
    stages: dict = dict(state.get("stage_timestamps") or {})
    stage = _get_stage(state, stage_name)
    new_count = stage.get("iteration_count", 0) + 1
    stage["iteration_count"] = new_count
    stages[stage_name] = stage

    revision_counts: dict = dict(state.get("revision_counts") or {})
    revision_counts[stage_name] = new_count

    return {
        "stage_timestamps": stages,
        "revision_counts": revision_counts,
    }


def increment_ci_cycle(state: dict) -> dict:
    """Increment the workflow-level CI fix-attempt cycle counter by 1.

    Args:
        state: Current workflow state dict.

    Returns:
        Partial state update dict with ``stats_ci_cycles`` key.
    """
    current: int = state.get("stats_ci_cycles") or 0
    return {"stats_ci_cycles": current + 1}


def add_pr_url(state: dict, pr_url: str) -> dict:
    """Append a PR URL to stats_pr_urls (idempotent — no duplicates).

    Args:
        state: Current workflow state dict.
        pr_url: The pull-request URL to record.

    Returns:
        Partial state update dict with ``stats_pr_urls`` key.
    """
    existing: list[str] = list(state.get("stats_pr_urls") or [])
    if pr_url not in existing:
        existing.append(pr_url)
    return {"stats_pr_urls": existing}


def set_outcome(_state: dict, outcome: str, reason: str | None = None) -> dict:
    """Set the workflow outcome and optional reason.

    Conventional outcome values:
    - ``"Completed"``          — finished successfully.
    - ``"Blocked: <reason>"``  — waiting on an external blocker.
    - ``"Failed: <error>"``    — terminated due to an unrecoverable error.

    Args:
        _state: Current workflow state dict (unused — outcome is set unconditionally).
        outcome: Outcome string to record.
        reason: Optional human-readable elaboration (e.g. blocking reason).

    Returns:
        Partial state update dict with ``workflow_outcome`` and
        ``stats_outcome_reason`` keys.
    """
    return {
        "workflow_outcome": outcome,
        "stats_outcome_reason": reason,
    }
