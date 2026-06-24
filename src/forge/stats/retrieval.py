"""Stats retrieval service for workflow checkpoints.

This module provides a unified interface for retrieving and validating
workflow statistics data from LangGraph checkpoints. It is used by both
Jira command handlers and CLI commands.

Usage::

    from forge.stats.retrieval import get_workflow_stats, get_workflow_stats_or_error

    stats = await get_workflow_stats("AISOS-123")
    if stats is None:
        # No checkpoint or no stats data
        ...

    # Or, get a result with an error message suitable for display:
    stats, error = await get_workflow_stats_or_error("AISOS-123")
    if error:
        print(error)
"""

import logging
from dataclasses import dataclass, field

from forge.orchestrator.checkpointer import get_checkpoint_state
from forge.workflow.stats import StageStats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Return type
# ---------------------------------------------------------------------------


@dataclass
class WorkflowStats:
    """Validated workflow statistics extracted from a checkpoint.

    All fields mirror the corresponding fields in ``StatsState``.  The
    dataclass is always fully populated — callers do not need to handle
    missing keys individually.  Fields that were absent in the checkpoint
    carry their zero / empty defaults so that partial (in-progress)
    workflows are represented cleanly.

    Attributes:
        ticket_key: The Jira ticket key this stats snapshot belongs to.
        stages: Per-stage metrics, keyed by stage name.
        pr_urls: URLs of pull requests opened during the workflow run.
        ci_cycles: Number of CI fix-attempt cycles triggered.
        outcome: Final outcome string, or ``None`` while the workflow is
            still in progress (e.g. ``"Completed"``, ``"Failed: …"``).
        outcome_reason: Human-readable elaboration on the outcome, or
            ``None`` when not applicable.
        comment_posted: Whether the summary stats comment has already been
            posted to the Jira ticket.
        workflow_run_id: Unique identifier for this workflow run (UUID4).
            Empty string when the checkpoint predates idempotency support.
    """

    ticket_key: str
    stages: dict[str, StageStats] = field(default_factory=dict)
    pr_urls: list[str] = field(default_factory=list)
    ci_cycles: int = 0
    outcome: str | None = None
    outcome_reason: str | None = None
    comment_posted: bool = False
    workflow_run_id: str = ""


# ---------------------------------------------------------------------------
# Retrieval helpers
# ---------------------------------------------------------------------------


def _extract_stats(ticket_key: str, state: dict) -> WorkflowStats | None:
    """Extract and validate stats data from a checkpoint state dict.

    Args:
        ticket_key: The Jira ticket key for logging context.
        state: The raw checkpoint state dict from ``get_checkpoint_state``.

    Returns:
        A populated ``WorkflowStats`` instance, or ``None`` when the
        checkpoint contains no stats data (e.g. legacy workflows).
    """
    if "stats_stages" not in state:
        logger.debug(
            "Checkpoint for %s has no stats_stages key (legacy workflow or pre-stats run)",
            ticket_key,
        )
        return None

    stages = state.get("stats_stages") or {}
    if not isinstance(stages, dict):
        logger.warning(
            "Checkpoint for %s has malformed stats_stages (expected dict, got %s); "
            "treating as empty",
            ticket_key,
            type(stages).__name__,
        )
        stages = {}

    pr_urls = state.get("stats_pr_urls") or []
    if not isinstance(pr_urls, list):
        logger.warning(
            "Checkpoint for %s has malformed stats_pr_urls (expected list, got %s); "
            "treating as empty",
            ticket_key,
            type(pr_urls).__name__,
        )
        pr_urls = []

    return WorkflowStats(
        ticket_key=ticket_key,
        stages=stages,
        pr_urls=pr_urls,
        ci_cycles=state.get("stats_ci_cycles") or 0,
        outcome=state.get("stats_outcome"),
        outcome_reason=state.get("stats_outcome_reason"),
        comment_posted=bool(state.get("stats_comment_posted", False)),
        workflow_run_id=state.get("workflow_run_id", ""),
    )


async def get_workflow_stats(ticket_key: str) -> WorkflowStats | None:
    """Retrieve workflow statistics for a ticket from its checkpoint.

    Looks up the LangGraph checkpoint for *ticket_key* and extracts the
    ``StatsState`` fields.  The function is intentionally tolerant:

    - Returns ``None`` when no checkpoint exists for the ticket.
    - Returns ``None`` when the checkpoint exists but contains no stats
      data (legacy workflows that predate stats tracking).
    - Returns a partially-populated ``WorkflowStats`` for in-progress
      workflows (fields that have not yet been set carry their zero/empty
      defaults).

    Args:
        ticket_key: The Jira ticket key (e.g. ``"AISOS-123"``).

    Returns:
        A ``WorkflowStats`` instance with all available data, or ``None``
        if no checkpoint or no stats data was found.
    """
    state = await get_checkpoint_state(ticket_key)

    if state is None:
        logger.debug("No checkpoint found for %s", ticket_key)
        return None

    return _extract_stats(ticket_key, state)


async def get_workflow_stats_or_error(
    ticket_key: str,
) -> tuple[WorkflowStats | None, str | None]:
    """Retrieve workflow statistics, returning a display-ready error on failure.

    A convenience wrapper around ``get_workflow_stats`` that never raises.
    On success the error string is ``None``; on failure the stats object is
    ``None`` and the error string contains a human-readable message suitable
    for printing to a terminal or posting as a Jira comment.

    Args:
        ticket_key: The Jira ticket key (e.g. ``"AISOS-123"``).

    Returns:
        A ``(WorkflowStats | None, str | None)`` tuple where exactly one
        element is always ``None``:

        - ``(stats, None)`` on success.
        - ``(None, error_message)`` when no stats are available or an
          exception occurred.
    """
    try:
        stats = await get_workflow_stats(ticket_key)
    except Exception as exc:
        logger.error("Failed to retrieve stats for %s: %s", ticket_key, exc)
        return None, f"Error retrieving workflow data for {ticket_key}: {exc}"

    if stats is None:
        return None, f"No workflow data found for {ticket_key}"

    return stats, None
