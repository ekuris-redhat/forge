"""Terminal stats posting node for workflow completion.

Posts a formatted stats summary comment to Jira whenever a workflow reaches a
terminal state (Completed, Blocked, or Failed).  This is a *side-effect* node —
it always returns the state unchanged and never fails the workflow, regardless
of whether the Jira posting succeeds.
"""

import logging
from typing import Any

from forge.workflow.bug.state import BugState
from forge.workflow.feature.state import FeatureState
from forge.workflow.stats.poster import ensure_stats_is_final_comment, post_stats_comment

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Outcome helpers
# ---------------------------------------------------------------------------


def _determine_outcome(state: FeatureState | BugState) -> str:
    """Return the outcome category string for the terminal state.

    Precedence:
    1. If ``workflow_outcome`` is already set in state, return it directly.
    2. If ``is_blocked`` is True, return ``"Blocked"``.
    3. If ``last_error`` is set, return ``"Failed"``.
    4. Otherwise, return ``"Completed"``.

    Args:
        state: Current feature or bug workflow state.

    Returns:
        One of ``"Completed"``, ``"Blocked"``, or ``"Failed"``.
    """
    # If the workflow has already classified its own outcome, honour that.
    existing = state.get("workflow_outcome")
    if existing:
        return existing

    if state.get("is_blocked"):
        return "Blocked"

    if state.get("last_error"):
        return "Failed"

    return "Completed"


def _extract_outcome_detail(
    state: FeatureState | BugState,
    outcome: str,
) -> str | None:
    """Extract a human-readable detail string for the given outcome.

    For ``"Failed"`` outcomes the ``last_error`` field is used.
    For ``"Blocked"`` outcomes the ``stats_outcome_reason`` field is used
    (which is expected to contain the block reason set by the blocking node).
    ``"Completed"`` outcomes have no detail.

    If ``stats_outcome_reason`` is already set in state it takes precedence
    over the derived values for all outcome types.

    Args:
        state: Current feature or bug workflow state.
        outcome: The outcome category string (e.g. ``"Blocked"``).

    Returns:
        A detail string, or ``None`` if no detail is available.
    """
    # A reason already recorded in state always takes precedence.
    existing_reason = state.get("stats_outcome_reason")
    if existing_reason:
        return existing_reason

    normalised = outcome.lower()
    if normalised == "failed":
        return state.get("last_error")

    if normalised == "blocked":
        # Block reason may also be in feedback_comment from a blocking gate.
        return state.get("feedback_comment")

    return None


# ---------------------------------------------------------------------------
# Node function
# ---------------------------------------------------------------------------


async def post_terminal_stats(state: FeatureState | BugState) -> dict[str, Any]:
    """Post a workflow stats summary comment when a terminal state is reached.

    Determines the outcome type (Completed / Blocked / Failed) from the current
    state, extracts any relevant detail (error message or block reason), then:

    1. Calls :func:`~forge.workflow.stats.poster.post_stats_comment` to post
       the formatted summary comment to the Jira ticket.
    2. Calls :func:`~forge.workflow.stats.poster.ensure_stats_is_final_comment`
       to guarantee the stats comment is the last Forge comment on the ticket
       (re-posting if necessary).

    This node is *non-blocking on failure*: any exception raised by the posting
    service is caught and logged, and the original state is returned unchanged
    so that the workflow can continue to its true terminal node.

    Handles both :class:`~forge.workflow.feature.state.FeatureState` and
    :class:`~forge.workflow.bug.state.BugState` workflows transparently.

    Args:
        state: Current feature or bug workflow state at a terminal node.

    Returns:
        An empty dict (state is returned unchanged — this is a side-effect node).
    """
    ticket_key: str = state.get("ticket_key", "")
    if not ticket_key:
        logger.warning("post_terminal_stats: no ticket_key in state — skipping stats post")
        return {}

    outcome = _determine_outcome(state)
    outcome_detail = _extract_outcome_detail(state, outcome)

    logger.info(
        "post_terminal_stats: posting stats for ticket=%s outcome=%s",
        ticket_key,
        outcome,
    )

    try:
        posted = await post_stats_comment(
            ticket_key=ticket_key,
            stats=state,
            outcome=outcome,
            outcome_detail=outcome_detail,
        )
        if posted:
            logger.info("post_terminal_stats: stats comment posted for ticket=%s", ticket_key)
        else:
            logger.warning(
                "post_terminal_stats: post_stats_comment returned False for ticket=%s",
                ticket_key,
            )
    except Exception:
        # post_stats_comment is itself non-blocking, but guard defensively.
        logger.exception(
            "post_terminal_stats: unexpected error calling post_stats_comment for ticket=%s",
            ticket_key,
        )

    try:
        await ensure_stats_is_final_comment(
            ticket_key=ticket_key,
            stats=state,
            outcome=outcome,
            outcome_detail=outcome_detail,
        )
        logger.info(
            "post_terminal_stats: ensure_stats_is_final_comment completed for ticket=%s",
            ticket_key,
        )
    except Exception:
        # Non-blocking — log and continue.
        logger.exception(
            "post_terminal_stats: unexpected error calling ensure_stats_is_final_comment "
            "for ticket=%s",
            ticket_key,
        )

    # Return empty dict — state is unchanged (LangGraph merges this with no-op).
    return {}
