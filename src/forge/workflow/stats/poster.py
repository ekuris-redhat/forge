"""Stats comment posting service for Jira tickets.

This module provides non-blocking async functions that format and post
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

Re-Post Mechanism
-----------------
``ensure_stats_is_final_comment`` guarantees the stats comment is always the
*last* Forge comment on the ticket.  It fetches all comments, identifies the
most recent one posted by the Forge service account, and re-posts the stats
summary if a non-stats comment was added after the most recent stats comment.
"""

import asyncio
import logging

from forge.config import get_settings
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

#: Prefix embedded in all stats comment bodies for identification.
#: This substring is present in every comment posted by post_stats_comment /
#: ensure_stats_is_final_comment and is used by _is_stats_comment() to
#: distinguish stats comments from other Forge comments.
_STATS_BODY_MARKER = "<!-- forge:stats:"


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


async def ensure_stats_is_final_comment(
    ticket_key: str,
    stats: StatsState,
    outcome: str,
    outcome_detail: str | None = None,
) -> bool:
    """Ensure the stats summary is the last Forge comment on a Jira ticket.

    Fetches all comments on *ticket_key*, filters to those posted by the
    Forge service account (configured via ``JIRA_SERVICE_ACCOUNT_ID``), and
    checks whether the most recent Forge comment is a stats comment.

    - If no Forge comments exist → posts a new stats comment.
    - If the most recent Forge comment **is** a stats comment → does nothing
      and returns ``True`` (idempotent).
    - If the most recent Forge comment is **not** a stats comment (e.g. an
      error notification was added after the stats) → re-posts the stats
      summary so it becomes the final Forge comment.

    When ``JIRA_SERVICE_ACCOUNT_ID`` is not configured, all comments are
    considered (no author filtering is applied).

    This function is safe to call multiple times; repeated calls when the
    stats comment is already the last comment are a no-op.

    Args:
        ticket_key: The Jira issue key to inspect (e.g. ``"PROJ-123"``).
        stats: The workflow statistics state to format and (re-)post.
        outcome: Outcome category passed to the stats formatter.
        outcome_detail: Optional elaboration on the outcome.

    Returns:
        ``True`` if the stats comment is (or becomes) the final Forge comment,
        ``False`` if the check or post operation fails.
    """
    jira = JiraClient()
    try:
        comments = await jira.get_comments(ticket_key)
    except Exception:
        logger.exception(
            "ensure_stats_is_final_comment: failed to fetch comments for ticket %s",
            ticket_key,
        )
        return False
    finally:
        await jira.close()

    settings = get_settings()
    service_account_id = settings.jira_service_account_id

    # Filter to Forge comments (comments by the service account).
    # When service_account_id is empty, treat *all* comments as Forge comments.
    if service_account_id:
        forge_comments = [c for c in comments if c.author_id == service_account_id]
    else:
        forge_comments = list(comments)

    if not forge_comments:
        # No Forge comments at all — post the initial stats comment.
        logger.info(
            "ensure_stats_is_final_comment: no Forge comments on %s; posting stats",
            ticket_key,
        )
        return await post_stats_comment(ticket_key, stats, outcome, outcome_detail)

    # Comments from get_comments() are returned in chronological order;
    # the last element is the most recent.
    most_recent = forge_comments[-1]

    if _is_stats_comment(most_recent.body):
        # Stats comment is already the final Forge comment — nothing to do.
        logger.debug(
            "ensure_stats_is_final_comment: stats comment is already final on %s",
            ticket_key,
        )
        return True

    # A non-stats Forge comment is more recent → re-post stats.
    logger.info(
        "ensure_stats_is_final_comment: re-posting stats on %s "
        "(most recent Forge comment id=%s is not a stats comment)",
        ticket_key,
        most_recent.id,
    )
    return await post_stats_comment(ticket_key, stats, outcome, outcome_detail)


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


def _is_stats_comment(body: str) -> bool:
    """Return True if *body* was produced by the stats comment poster.

    Detection is based on the hidden HTML marker (``<!-- forge:stats:… -->``)
    that :func:`post_stats_comment` embeds in every comment it posts.

    Args:
        body: The raw text body of a Jira comment.

    Returns:
        ``True`` when the body contains the stats marker, ``False`` otherwise.
    """
    return _STATS_BODY_MARKER in body
