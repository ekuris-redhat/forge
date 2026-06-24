"""Stats comment posting service for Jira tickets.

This module provides a non-blocking async function that formats and posts
workflow statistics as a comment to the associated Jira ticket at the end
of a workflow run.

Idempotency
-----------
``post_stats_comment`` checks Redis before posting and skips the comment if
one has already been recorded for the given ``run_id``.  After a successful
post the marker is written to Redis with a 7-day TTL via
:func:`~forge.workflow.stats.idempotency.mark_stats_posted`.  A hidden HTML
comment (``<!-- forge:stats:<run_id> -->``) is also embedded in the comment
body for independent verification.
"""

import asyncio
import logging

from forge.integrations.jira.client import JiraClient
from forge.workflow.stats import StatsState
from forge.workflow.stats.formatter import format_stats_summary
from forge.workflow.stats.idempotency import (
    build_run_marker,
    has_stats_been_posted,
    mark_stats_posted,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Retry configuration
# ---------------------------------------------------------------------------

#: Maximum number of posting attempts (1 initial + 2 retries).
_MAX_ATTEMPTS = 3

#: Initial backoff delay in seconds before the first retry.
_INITIAL_BACKOFF_SECONDS = 1.0

#: Maximum allowed backoff delay (caps exponential growth).
_MAX_BACKOFF_SECONDS = 16.0

#: Overall timeout for the entire post_stats_comment operation (5-minute SLA).
_OPERATION_TIMEOUT_SECONDS = 300.0


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def post_stats_comment(
    ticket_key: str,
    stats: StatsState,
    outcome: str,
    outcome_detail: str | None = None,
    run_id: str | None = None,
) -> bool:
    """Post a formatted stats summary comment to a Jira ticket.

    Formats the workflow statistics contained in *stats* into Jira wiki markup
    and posts it as a comment on *ticket_key*.  The operation uses exponential
    backoff and retries up to :data:`_MAX_ATTEMPTS` times before giving up.
    The entire operation is bounded by a 5-minute timeout.

    **Idempotency**: when *run_id* is provided (or can be read from
    ``stats["workflow_run_id"]``), the function checks Redis before posting
    and returns ``True`` immediately if the comment has already been posted for
    this run.  A hidden HTML comment is embedded in the body and a Redis
    marker is written after a successful post.

    This function is *non-blocking on failure*: any exception is caught,
    logged, and ``False`` is returned so that callers are not disrupted.

    Args:
        ticket_key: The Jira issue key to comment on (e.g. ``"PROJ-123"``).
        stats: The workflow statistics state to format and post.
        outcome: Outcome category — one of ``"completed"``, ``"blocked"``, or
            ``"failed"`` (matched case-insensitively by the formatter).
        outcome_detail: Optional elaboration on the outcome.
        run_id: Unique workflow run identifier for idempotency.  Falls back to
            ``stats.get("workflow_run_id")`` when not given explicitly.

    Returns:
        ``True`` if the comment was successfully posted (or was already
        posted for this run), ``False`` otherwise.
    """
    # Resolve the run identifier from the explicit argument or from state.
    effective_run_id: str | None = run_id or stats.get("workflow_run_id")  # type: ignore[call-overload]

    # --- Idempotency pre-check -------------------------------------------
    if effective_run_id:
        try:
            if await has_stats_been_posted(ticket_key, effective_run_id):
                logger.info(
                    "Stats comment already posted for ticket=%s run_id=%s — skipping",
                    ticket_key,
                    effective_run_id,
                )
                return True
        except Exception:
            # Redis check failures must not block posting.
            logger.warning(
                "Idempotency pre-check failed for ticket=%s run_id=%s; proceeding with post",
                ticket_key,
                effective_run_id,
                exc_info=True,
            )

    try:
        posted = await asyncio.wait_for(
            _post_with_retry(ticket_key, stats, outcome, outcome_detail, effective_run_id),
            timeout=_OPERATION_TIMEOUT_SECONDS,
        )
    except TimeoutError:
        logger.error(
            "post_stats_comment timed out after %.0fs for ticket %s",
            _OPERATION_TIMEOUT_SECONDS,
            ticket_key,
        )
        return False
    except Exception:
        # Broad catch: we must never let stats posting crash the caller.
        logger.exception(
            "Unexpected error posting stats comment for ticket %s",
            ticket_key,
        )
        return False

    # --- Idempotency post-mark -------------------------------------------
    if posted and effective_run_id:
        try:
            await mark_stats_posted(ticket_key, effective_run_id)
        except Exception:
            # Marker write failures are non-fatal — the comment is already
            # posted; we just risk a harmless duplicate on the next retry.
            logger.warning(
                "Failed to write idempotency marker for ticket=%s run_id=%s",
                ticket_key,
                effective_run_id,
                exc_info=True,
            )

    return posted


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _post_with_retry(
    ticket_key: str,
    stats: StatsState,
    outcome: str,
    outcome_detail: str | None,
    run_id: str | None = None,
) -> bool:
    """Attempt to post the stats comment with exponential backoff on failure.

    Args:
        ticket_key: Jira issue key.
        stats: Workflow statistics state.
        outcome: Outcome string passed to the formatter.
        outcome_detail: Optional detail string passed to the formatter.
        run_id: Unique workflow run identifier.  When provided, a hidden HTML
            marker is appended to the comment body for verification.

    Returns:
        ``True`` if the comment was posted successfully, ``False`` after all
        attempts are exhausted.
    """
    comment_body = format_stats_summary(stats, outcome, outcome_detail)

    # Append the idempotency marker so readers can verify which run produced
    # this comment without querying Redis.
    if run_id:
        comment_body = f"{comment_body}\n{build_run_marker(run_id)}"

    backoff = _INITIAL_BACKOFF_SECONDS

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        jira = JiraClient()
        try:
            await jira.add_comment(ticket_key, comment_body)
            logger.info(
                "Posted stats comment to %s (attempt %d/%d)",
                ticket_key,
                attempt,
                _MAX_ATTEMPTS,
            )
            return True
        except Exception as exc:
            logger.warning(
                "Failed to post stats comment to %s (attempt %d/%d): %s",
                ticket_key,
                attempt,
                _MAX_ATTEMPTS,
                exc,
            )
            if attempt < _MAX_ATTEMPTS:
                wait = min(backoff, _MAX_BACKOFF_SECONDS)
                logger.debug("Retrying in %.1fs…", wait)
                await asyncio.sleep(wait)
                backoff *= 2
        finally:
            await jira.close()

    logger.error(
        "Gave up posting stats comment to %s after %d attempts",
        ticket_key,
        _MAX_ATTEMPTS,
    )
    return False
