"""Integration test demonstrating stats comment duplicate prevention.

This test shows the full idempotency flow end-to-end:

1. First call to post_stats_comment() — Redis has no marker → posts comment
   and writes the marker.
2. Second call to post_stats_comment() with the same run_id — Redis marker
   present → skips posting entirely.

The test uses an in-memory dict backed fake Redis to avoid requiring a
running Redis instance.  This is an integration-level test because it
exercises the interaction between poster.py and idempotency.py rather than
testing each module in isolation.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Fake Redis implementation (in-memory dict — no real Redis required)
# ---------------------------------------------------------------------------


class FakeRedis:
    """Minimal in-memory Redis stub supporting exists() and setex()."""

    def __init__(self):
        self._store: dict[str, str] = {}

    async def exists(self, key: str) -> int:
        return 1 if key in self._store else 0

    async def setex(self, key: str, _ttl: int, value: str) -> None:
        self._store[key] = value


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

TICKET_KEY = "INTTEST-99"
RUN_ID = "aabbccdd-1234-5678-abcd-000000000001"
OUTCOME = "completed"


def _minimal_stats(run_id: str = RUN_ID) -> dict:
    return {
        "stats_stages": {},
        "stats_pr_urls": [],
        "stats_ci_cycles": 0,
        "stats_outcome": None,
        "stats_outcome_reason": None,
        "stats_comment_posted": False,
        "workflow_run_id": run_id,
    }


def _make_jira_mock() -> MagicMock:
    mock = MagicMock()
    mock.add_comment = AsyncMock(return_value=MagicMock())
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_first_call_posts_comment_and_marks_redis():
    """First invocation posts the comment and records the marker in Redis."""
    from forge.workflow.stats.poster import post_stats_comment

    fake_redis = FakeRedis()
    mock_jira = _make_jira_mock()

    with (
        patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
        patch(
            "forge.workflow.stats.idempotency.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ),
    ):
        result = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

    assert result is True
    mock_jira.add_comment.assert_called_once()

    # Marker must now be present in our fake Redis (key format: forge:stats:posted:<ticket>:<run_id>)
    assert await fake_redis.exists(f"forge:stats:posted:{TICKET_KEY}:{RUN_ID}") == 1


@pytest.mark.asyncio
async def test_second_call_skips_posting():
    """Second invocation with the same run_id skips Jira entirely."""
    from forge.workflow.stats.poster import post_stats_comment

    fake_redis = FakeRedis()
    mock_jira = _make_jira_mock()

    with (
        patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
        patch(
            "forge.workflow.stats.idempotency.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ),
    ):
        # First call — should post
        result_first = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)
        # Second call — should skip
        result_second = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

    assert result_first is True
    assert result_second is True  # still "successful" — just a no-op
    # Jira was only called once despite two invocations
    assert mock_jira.add_comment.call_count == 1


@pytest.mark.asyncio
async def test_different_run_ids_each_post_independently():
    """Two calls with different run_ids each result in a Jira post."""
    from forge.workflow.stats.poster import post_stats_comment

    fake_redis = FakeRedis()
    mock_jira = _make_jira_mock()
    run_id_a = "aaaaaaaa-0000-0000-0000-000000000001"
    run_id_b = "bbbbbbbb-0000-0000-0000-000000000002"

    with (
        patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
        patch(
            "forge.workflow.stats.idempotency.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ),
    ):
        result_a = await post_stats_comment(TICKET_KEY, _minimal_stats(run_id_a), OUTCOME)
        result_b = await post_stats_comment(TICKET_KEY, _minimal_stats(run_id_b), OUTCOME)

    assert result_a is True
    assert result_b is True
    assert mock_jira.add_comment.call_count == 2


@pytest.mark.asyncio
async def test_comment_body_contains_unique_marker():
    """The posted comment embeds the hidden HTML marker for the run_id."""
    from forge.workflow.stats.poster import post_stats_comment

    fake_redis = FakeRedis()
    mock_jira = _make_jira_mock()

    with (
        patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
        patch(
            "forge.workflow.stats.idempotency.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ),
    ):
        await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

    args, _ = mock_jira.add_comment.call_args
    comment_body = args[1]
    assert f"<!-- forge:stats:{RUN_ID} -->" in comment_body


@pytest.mark.asyncio
async def test_same_ticket_different_runs_are_independent():
    """Same ticket key but different run IDs behave as independent posts."""
    from forge.workflow.stats.poster import post_stats_comment

    fake_redis = FakeRedis()
    mock_jira_1 = _make_jira_mock()
    mock_jira_2 = _make_jira_mock()
    run_id_1 = "run-11111111-0000-0000-0000-000000000001"
    run_id_2 = "run-22222222-0000-0000-0000-000000000002"

    with (
        patch(
            "forge.workflow.stats.idempotency.get_redis_client",
            new=AsyncMock(return_value=fake_redis),
        ),
    ):
        # First run on the same ticket
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira_1):
            r1 = await post_stats_comment(TICKET_KEY, _minimal_stats(run_id_1), OUTCOME)

        # Second run (new run_id) on the same ticket — should also post
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira_2):
            r2 = await post_stats_comment(TICKET_KEY, _minimal_stats(run_id_2), OUTCOME)

    assert r1 is True
    assert r2 is True
    mock_jira_1.add_comment.assert_called_once()
    mock_jira_2.add_comment.assert_called_once()
