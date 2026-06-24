"""Stats comment posting service for Jira tickets.

This module provides a non-blocking async function that formats and posts
workflow statistics as a comment to the associated Jira ticket at the end
of a workflow run.
"""

import asyncio
import logging

from forge.integrations.jira.client import JiraClient
from forge.workflow.stats import StatsState
from forge.workflow.stats.formatter import format_stats_summary

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
) -> bool:
    """Post a formatted stats summary comment to a Jira ticket.

    Formats the workflow statistics contained in *stats* into Jira wiki markup
    and posts it as a comment on *ticket_key*.  The operation uses exponential
    backoff and retries up to :data:`_MAX_ATTEMPTS` times before giving up.
    The entire operation is bounded by a 5-minute timeout.

    This function is *non-blocking on failure*: any exception is caught,
    logged, and ``False`` is returned so that callers are not disrupted.

    Args:
        ticket_key: The Jira issue key to comment on (e.g. ``"PROJ-123"``).
        stats: The workflow statistics state to format and post.
        outcome: Outcome category — one of ``"completed"``, ``"blocked"``, or
            ``"failed"`` (matched case-insensitively by the formatter).
        outcome_detail: Optional elaboration on the outcome.

    Returns:
        ``True`` if the comment was successfully posted, ``False`` otherwise.
    """
    try:
        return await asyncio.wait_for(
            _post_with_retry(ticket_key, stats, outcome, outcome_detail),
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


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _post_with_retry(
    ticket_key: str,
    stats: StatsState,
    outcome: str,
    outcome_detail: str | None,
) -> bool:
    """Attempt to post the stats comment with exponential backoff on failure.

    Args:
        ticket_key: Jira issue key.
        stats: Workflow statistics state.
        outcome: Outcome string passed to the formatter.
        outcome_detail: Optional detail string passed to the formatter.

    Returns:
        ``True`` if the comment was posted successfully, ``False`` after all
        attempts are exhausted.
    """
    comment_body = format_stats_summary(stats, outcome, outcome_detail)
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
