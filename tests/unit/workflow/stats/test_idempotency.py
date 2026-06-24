"""Unit tests for forge.workflow.stats.idempotency.

Tests verify:
- has_stats_been_posted() returns False when key does not exist in Redis
- has_stats_been_posted() returns True when key exists in Redis
- mark_stats_posted() stores key with 7-day TTL via setex
- build_run_marker() returns the correct HTML comment string
- Redis key format includes both ticket_key and run_id
- Redis pre-check failures in post_stats_comment are non-fatal
- Idempotency integration: post_stats_comment skips duplicate posts
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.stats.idempotency import (
    _KEY_PREFIX,
    STATS_IDEMPOTENCY_TTL_SECONDS,
    _make_key,
    build_run_marker,
    has_stats_been_posted,
    mark_stats_posted,
)

# ---------------------------------------------------------------------------
# Constants for tests
# ---------------------------------------------------------------------------

TICKET_KEY = "PROJ-42"
RUN_ID = "550e8400-e29b-41d4-a716-446655440000"


# ---------------------------------------------------------------------------
# _make_key
# ---------------------------------------------------------------------------


class TestMakeKey:
    """Internal key construction helper."""

    def test_includes_prefix(self):
        key = _make_key(TICKET_KEY, RUN_ID)
        assert key.startswith(_KEY_PREFIX)

    def test_includes_ticket_key(self):
        key = _make_key(TICKET_KEY, RUN_ID)
        assert TICKET_KEY in key

    def test_includes_run_id(self):
        key = _make_key(TICKET_KEY, RUN_ID)
        assert RUN_ID in key

    def test_format(self):
        key = _make_key("ABC-1", "run-xyz")
        assert key == f"{_KEY_PREFIX}ABC-1:run-xyz"

    def test_different_tickets_produce_different_keys(self):
        key1 = _make_key("PROJ-1", RUN_ID)
        key2 = _make_key("PROJ-2", RUN_ID)
        assert key1 != key2

    def test_different_run_ids_produce_different_keys(self):
        key1 = _make_key(TICKET_KEY, "run-1")
        key2 = _make_key(TICKET_KEY, "run-2")
        assert key1 != key2


# ---------------------------------------------------------------------------
# build_run_marker
# ---------------------------------------------------------------------------


class TestBuildRunMarker:
    """HTML comment marker for embedding in comment body."""

    def test_returns_html_comment(self):
        marker = build_run_marker(RUN_ID)
        assert marker.startswith("<!--")
        assert marker.endswith("-->")

    def test_includes_run_id(self):
        marker = build_run_marker(RUN_ID)
        assert RUN_ID in marker

    def test_contains_forge_stats_prefix(self):
        marker = build_run_marker(RUN_ID)
        assert "forge:stats:" in marker

    def test_format(self):
        marker = build_run_marker("abc-123")
        assert marker == "<!-- forge:stats:abc-123 -->"

    def test_different_run_ids_produce_different_markers(self):
        assert build_run_marker("run-1") != build_run_marker("run-2")


# ---------------------------------------------------------------------------
# TTL constant
# ---------------------------------------------------------------------------


class TestTtlConstant:
    """Verify the 7-day TTL value."""

    def test_seven_days_in_seconds(self):
        assert STATS_IDEMPOTENCY_TTL_SECONDS == 7 * 24 * 60 * 60

    def test_is_integer(self):
        assert isinstance(STATS_IDEMPOTENCY_TTL_SECONDS, int)


# ---------------------------------------------------------------------------
# has_stats_been_posted
# ---------------------------------------------------------------------------


class TestHasStatsBeenPosted:
    """has_stats_been_posted() checks Redis for the marker key."""

    @pytest.mark.asyncio
    async def test_returns_false_when_key_absent(self):
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)

        result = await has_stats_been_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        assert result is False

    @pytest.mark.asyncio
    async def test_returns_true_when_key_present(self):
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)

        result = await has_stats_been_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        assert result is True

    @pytest.mark.asyncio
    async def test_calls_exists_with_correct_key(self):
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)

        await has_stats_been_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        expected_key = _make_key(TICKET_KEY, RUN_ID)
        mock_redis.exists.assert_called_once_with(expected_key)

    @pytest.mark.asyncio
    async def test_uses_shared_client_when_none_provided(self):
        """When redis_client is None, get_redis_client() is called."""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)

        with patch(
            "forge.workflow.stats.idempotency.get_redis_client",
            new=AsyncMock(return_value=mock_redis),
        ):
            result = await has_stats_been_posted(TICKET_KEY, RUN_ID)

        assert result is False
        mock_redis.exists.assert_called_once()

    @pytest.mark.asyncio
    async def test_truthy_redis_value_returns_true(self):
        """Any non-zero integer from exists() is treated as True."""
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=2)

        result = await has_stats_been_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        assert result is True


# ---------------------------------------------------------------------------
# mark_stats_posted
# ---------------------------------------------------------------------------


class TestMarkStatsPosted:
    """mark_stats_posted() writes the marker key with correct TTL."""

    @pytest.mark.asyncio
    async def test_calls_setex(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await mark_stats_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_setex_uses_correct_key(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await mark_stats_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        call_args = mock_redis.setex.call_args
        key = call_args.args[0]
        assert key == _make_key(TICKET_KEY, RUN_ID)

    @pytest.mark.asyncio
    async def test_setex_uses_correct_ttl(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await mark_stats_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        call_args = mock_redis.setex.call_args
        ttl = call_args.args[1]
        assert ttl == STATS_IDEMPOTENCY_TTL_SECONDS

    @pytest.mark.asyncio
    async def test_setex_stores_truthy_value(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        await mark_stats_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        call_args = mock_redis.setex.call_args
        value = call_args.args[2]
        assert value  # any truthy value is fine

    @pytest.mark.asyncio
    async def test_uses_shared_client_when_none_provided(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        with patch(
            "forge.workflow.stats.idempotency.get_redis_client",
            new=AsyncMock(return_value=mock_redis),
        ):
            await mark_stats_posted(TICKET_KEY, RUN_ID)

        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_none(self):
        mock_redis = AsyncMock()
        mock_redis.setex = AsyncMock()

        result = await mark_stats_posted(TICKET_KEY, RUN_ID, redis_client=mock_redis)

        assert result is None


# ---------------------------------------------------------------------------
# Integration with post_stats_comment
# ---------------------------------------------------------------------------


class TestPostStatsCommentIdempotency:
    """post_stats_comment() integrates idempotency guard correctly."""

    def _minimal_stats(self, **overrides) -> dict:
        base = {
            "stats_stages": {},
            "stats_pr_urls": [],
            "stats_ci_cycles": 0,
            "stats_outcome": None,
            "stats_outcome_reason": None,
            "stats_comment_posted": False,
            "workflow_run_id": RUN_ID,
        }
        base.update(overrides)
        return base

    def _make_jira_mock(self, side_effect=None) -> MagicMock:
        mock = MagicMock()
        if side_effect is not None:
            mock.add_comment = AsyncMock(side_effect=side_effect)
        else:
            mock.add_comment = AsyncMock(return_value=MagicMock())
        mock.close = AsyncMock()
        return mock

    @pytest.mark.asyncio
    async def test_skips_posting_when_already_posted(self):
        """Returns True immediately without calling Jira when Redis marker exists."""
        from forge.workflow.stats.poster import post_stats_comment

        mock_jira = self._make_jira_mock()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=1)  # already posted

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.idempotency.get_redis_client",
                new=AsyncMock(return_value=mock_redis),
            ),
        ):
            result = await post_stats_comment(
                TICKET_KEY, self._minimal_stats(), "completed", run_id=RUN_ID
            )

        assert result is True
        mock_jira.add_comment.assert_not_called()

    @pytest.mark.asyncio
    async def test_posts_and_marks_when_not_yet_posted(self):
        """Posts the comment and writes the marker when Redis key is absent."""
        from forge.workflow.stats.poster import post_stats_comment

        mock_jira = self._make_jira_mock()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)  # not yet posted
        mock_redis.setex = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.idempotency.get_redis_client",
                new=AsyncMock(return_value=mock_redis),
            ),
        ):
            result = await post_stats_comment(
                TICKET_KEY, self._minimal_stats(), "completed", run_id=RUN_ID
            )

        assert result is True
        mock_jira.add_comment.assert_called_once()
        mock_redis.setex.assert_called_once()

    @pytest.mark.asyncio
    async def test_comment_body_includes_run_marker(self):
        """The posted comment body contains the hidden HTML marker."""
        from forge.workflow.stats.poster import post_stats_comment

        mock_jira = self._make_jira_mock()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)
        mock_redis.setex = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.idempotency.get_redis_client",
                new=AsyncMock(return_value=mock_redis),
            ),
        ):
            await post_stats_comment(TICKET_KEY, self._minimal_stats(), "completed", run_id=RUN_ID)

        args, _ = mock_jira.add_comment.call_args
        comment_body = args[1]
        assert f"<!-- forge:stats:{RUN_ID} -->" in comment_body

    @pytest.mark.asyncio
    async def test_uses_workflow_run_id_from_stats_when_no_explicit_run_id(self):
        """Falls back to stats['workflow_run_id'] when run_id not passed explicitly."""
        from forge.workflow.stats.poster import post_stats_comment

        mock_jira = self._make_jira_mock()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)
        mock_redis.setex = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.idempotency.get_redis_client",
                new=AsyncMock(return_value=mock_redis),
            ),
        ):
            # Note: no explicit run_id — should pick up workflow_run_id from stats
            result = await post_stats_comment(TICKET_KEY, self._minimal_stats(), "completed")

        assert result is True
        args, _ = mock_jira.add_comment.call_args
        comment_body = args[1]
        assert f"<!-- forge:stats:{RUN_ID} -->" in comment_body

    @pytest.mark.asyncio
    async def test_redis_check_failure_does_not_block_post(self):
        """If the Redis pre-check raises, the comment is still attempted."""
        from forge.workflow.stats.poster import post_stats_comment

        mock_jira = self._make_jira_mock()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(side_effect=ConnectionError("redis down"))
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.idempotency.get_redis_client",
                new=AsyncMock(return_value=mock_redis),
            ),
        ):
            result = await post_stats_comment(
                TICKET_KEY, self._minimal_stats(), "completed", run_id=RUN_ID
            )

        # Comment should still be posted even if Redis is unavailable
        assert result is True
        mock_jira.add_comment.assert_called_once()

    @pytest.mark.asyncio
    async def test_marker_write_failure_does_not_affect_return_value(self):
        """If the Redis marker write fails after a successful post, True is still returned."""
        from forge.workflow.stats.poster import post_stats_comment

        mock_jira = self._make_jira_mock()
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)
        mock_redis.setex = AsyncMock(side_effect=ConnectionError("redis down"))

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.idempotency.get_redis_client",
                new=AsyncMock(return_value=mock_redis),
            ),
        ):
            result = await post_stats_comment(
                TICKET_KEY, self._minimal_stats(), "completed", run_id=RUN_ID
            )

        assert result is True

    @pytest.mark.asyncio
    async def test_no_marker_when_run_id_absent(self):
        """When no run_id is available, the comment body has no HTML marker."""
        from forge.workflow.stats.poster import post_stats_comment

        mock_jira = self._make_jira_mock()
        # Stats without workflow_run_id
        stats = {
            "stats_stages": {},
            "stats_pr_urls": [],
            "stats_ci_cycles": 0,
            "stats_outcome": None,
            "stats_outcome_reason": None,
            "stats_comment_posted": False,
        }

        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, stats, "completed")

        args, _ = mock_jira.add_comment.call_args
        comment_body = args[1]
        assert "forge:stats:" not in comment_body

    @pytest.mark.asyncio
    async def test_does_not_mark_when_post_fails(self):
        """Redis marker is NOT written if the Jira post fails."""
        from forge.workflow.stats.poster import post_stats_comment

        mock_jira = self._make_jira_mock(side_effect=Exception("API down"))
        mock_redis = AsyncMock()
        mock_redis.exists = AsyncMock(return_value=0)
        mock_redis.setex = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", new_callable=AsyncMock),
            patch(
                "forge.workflow.stats.idempotency.get_redis_client",
                new=AsyncMock(return_value=mock_redis),
            ),
        ):
            result = await post_stats_comment(
                TICKET_KEY, self._minimal_stats(), "completed", run_id=RUN_ID
            )

        assert result is False
        mock_redis.setex.assert_not_called()
