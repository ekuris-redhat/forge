"""Idempotency guard for stats comment posting.

Prevents duplicate stats comments from being posted to the same Jira ticket
for the same workflow run.  Markers are stored in Redis with a 7-day TTL,
which is more than sufficient for any workflow to complete.

Usage::

    from forge.workflow.stats.idempotency import has_stats_been_posted, mark_stats_posted

    if not await has_stats_been_posted(ticket_key, run_id):
        # … post comment …
        await mark_stats_posted(ticket_key, run_id)
"""

import logging

import redis.asyncio as redis

from forge.orchestrator.checkpointer import get_redis_client

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

#: Redis key prefix for stats-posted idempotency markers.
_KEY_PREFIX = "forge:stats:posted:"

#: Time-to-live for idempotency markers (7 days in seconds).
STATS_IDEMPOTENCY_TTL_SECONDS = 7 * 24 * 60 * 60  # 604 800


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_key(ticket_key: str, run_id: str) -> str:
    """Return the Redis key for a given ticket / run combination.

    Args:
        ticket_key: The Jira issue key (e.g. ``"PROJ-123"``).
        run_id: The unique workflow run identifier (UUID4 string).

    Returns:
        Redis key string in the form ``forge:stats:posted:<ticket>:<run_id>``.
    """
    return f"{_KEY_PREFIX}{ticket_key}:{run_id}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def has_stats_been_posted(
    ticket_key: str,
    run_id: str,
    *,
    redis_client: redis.Redis | None = None,
) -> bool:
    """Check whether a stats comment has already been posted for this run.

    Args:
        ticket_key: The Jira issue key (e.g. ``"PROJ-123"``).
        run_id: The unique workflow run identifier stored in
            ``StatsState.workflow_run_id``.
        redis_client: Optional Redis client to use.  A shared client is
            obtained via :func:`~forge.orchestrator.checkpointer.get_redis_client`
            when not provided.

    Returns:
        ``True`` if the marker exists in Redis (comment already posted),
        ``False`` otherwise.
    """
    client = redis_client if redis_client is not None else await get_redis_client()
    key = _make_key(ticket_key, run_id)
    exists = await client.exists(key)
    posted = bool(exists)
    if posted:
        logger.debug(
            "Stats comment already posted for ticket=%s run_id=%s (key=%s)",
            ticket_key,
            run_id,
            key,
        )
    return posted


async def mark_stats_posted(
    ticket_key: str,
    run_id: str,
    *,
    redis_client: redis.Redis | None = None,
) -> None:
    """Record that a stats comment has been posted for this run.

    Stores a marker in Redis with a 7-day TTL so that subsequent calls to
    :func:`has_stats_been_posted` return ``True`` for the same combination.

    Args:
        ticket_key: The Jira issue key (e.g. ``"PROJ-123"``).
        run_id: The unique workflow run identifier stored in
            ``StatsState.workflow_run_id``.
        redis_client: Optional Redis client to use.  A shared client is
            obtained via :func:`~forge.orchestrator.checkpointer.get_redis_client`
            when not provided.
    """
    client = redis_client if redis_client is not None else await get_redis_client()
    key = _make_key(ticket_key, run_id)
    await client.setex(key, STATS_IDEMPOTENCY_TTL_SECONDS, "1")
    logger.debug(
        "Marked stats comment as posted for ticket=%s run_id=%s (TTL=%ds)",
        ticket_key,
        run_id,
        STATS_IDEMPOTENCY_TTL_SECONDS,
    )


def build_run_marker(run_id: str) -> str:
    """Return the hidden HTML comment marker to embed in the posted comment.

    Including this marker in the Jira comment body allows independent
    verification that a comment was posted for a specific run — useful
    for debugging and for future tooling that inspects comment bodies.

    Args:
        run_id: The unique workflow run identifier.

    Returns:
        HTML comment string of the form ``<!-- forge:stats:<run_id> -->``.
    """
    return f"<!-- forge:stats:{run_id} -->"
