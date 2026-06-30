"""Unit tests for ensure_stats_is_final_comment() in forge.workflow.stats.poster.

Tests verify:
- No Forge comments exist → posts new stats comment
- Most recent Forge comment IS a stats comment → no re-post (returns True)
- Most recent Forge comment is NOT a stats comment → re-posts stats
- Service account ID filtering: only Forge comments are considered
- When service_account_id is empty, all comments are treated as Forge comments
- JiraClient.get_comments() failure → returns False gracefully
- JiraClient is always closed after fetching comments
- _is_stats_comment() correctly identifies stats comments by marker
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.stats.poster import (
    _STATS_BODY_MARKER,
    _is_stats_comment,
    ensure_stats_is_final_comment,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

TICKET_KEY = "PROJ-99"
OUTCOME = "completed"
SERVICE_ACCOUNT_ID = "forge-bot-123"

# A body that looks like a stats comment (contains the marker)
STATS_BODY = f"h2. Workflow Stats\n...\n{_STATS_BODY_MARKER}run-abc -->"

# A body that does NOT look like a stats comment
OTHER_BODY = "This is a regular error notification comment."


def _minimal_stats(**overrides) -> dict:
    base = {
        "stage_timestamps": {},
        "stats_pr_urls": [],
        "stats_ci_cycles": 0,
        "workflow_outcome": None,
        "stats_outcome_reason": None,
        "stats_comment_posted": False,
    }
    base.update(overrides)
    return base


def _make_comment(
    comment_id: str,
    body: str,
    author_id: str = SERVICE_ACCOUNT_ID,
) -> MagicMock:
    """Build a mock JiraComment with the given attributes."""
    comment = MagicMock()
    comment.id = comment_id
    comment.body = body
    comment.author_id = author_id
    comment.created = datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC)
    return comment


def _make_jira_mock(comments: list) -> MagicMock:
    """Return a mock JiraClient with get_comments returning *comments*."""
    mock = MagicMock()
    mock.get_comments = AsyncMock(return_value=comments)
    mock.add_comment = AsyncMock(return_value=MagicMock())
    mock.close = AsyncMock()
    return mock


def _patch_service_account(account_id: str = SERVICE_ACCOUNT_ID):
    """Context manager that patches get_settings to return account_id."""
    mock_settings = MagicMock()
    mock_settings.jira_service_account_id = account_id
    return patch("forge.workflow.stats.poster.get_settings", return_value=mock_settings)


# ---------------------------------------------------------------------------
# _is_stats_comment() helper
# ---------------------------------------------------------------------------


class TestIsStatsComment:
    """Unit tests for the _is_stats_comment() detection helper."""

    def test_returns_true_for_body_with_marker(self):
        assert _is_stats_comment(STATS_BODY) is True

    def test_returns_true_for_minimal_marker(self):
        assert _is_stats_comment("<!-- forge:stats:some-run-id -->") is True

    def test_returns_false_for_plain_comment(self):
        assert _is_stats_comment("Just a regular comment.") is False

    def test_returns_false_for_empty_body(self):
        assert _is_stats_comment("") is False

    def test_returns_false_for_similar_but_wrong_marker(self):
        # Must match the exact prefix _STATS_BODY_MARKER
        assert _is_stats_comment("<!-- forge:stats -->") is False
        assert _is_stats_comment("<!-- forge:other: -->") is False

    def test_marker_constant_starts_with_expected_prefix(self):
        assert _STATS_BODY_MARKER == "<!-- forge:stats:"


# ---------------------------------------------------------------------------
# No Forge comments → posts new stats
# ---------------------------------------------------------------------------


class TestNoForgeComments:
    """When no Forge comments exist, ensure_stats_is_final_comment posts a new one."""

    @pytest.mark.asyncio
    async def test_posts_stats_when_no_forge_comments(self):
        """With service account filtering, no matching comments → post new stats."""
        # A comment by a different author
        other_comment = _make_comment("c1", OTHER_BODY, author_id="human-user-456")
        mock_jira = _make_jira_mock([other_comment])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        mock_post.assert_called_once_with(TICKET_KEY, _minimal_stats(), OUTCOME, None)

    @pytest.mark.asyncio
    async def test_posts_stats_when_comment_list_is_empty(self):
        """Empty comment list → post new stats."""
        mock_jira = _make_jira_mock([])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_outcome_detail_when_no_forge_comments(self):
        mock_jira = _make_jira_mock([])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            await ensure_stats_is_final_comment(
                TICKET_KEY, _minimal_stats(), "blocked", "waiting on external team"
            )

        _, call_args, _ = mock_post.mock_calls[0]
        assert call_args[2] == "blocked"
        assert call_args[3] == "waiting on external team"


# ---------------------------------------------------------------------------
# Most recent Forge comment IS a stats comment → no re-post
# ---------------------------------------------------------------------------


class TestStatsAlreadyFinal:
    """When the most recent Forge comment is already a stats comment, skip re-post."""

    @pytest.mark.asyncio
    async def test_returns_true_without_reposting(self):
        stats_comment = _make_comment("c1", STATS_BODY)
        mock_jira = _make_jira_mock([stats_comment])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_repost_when_stats_is_last_of_many_forge_comments(self):
        """Multiple Forge comments; stats is the last one → no re-post."""
        other1 = _make_comment("c1", OTHER_BODY)
        other2 = _make_comment("c2", OTHER_BODY)
        stats_comment = _make_comment("c3", STATS_BODY)
        mock_jira = _make_jira_mock([other1, other2, stats_comment])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_idempotent_multiple_calls_when_stats_is_final(self):
        """Calling the function twice is safe; second call also returns True."""
        stats_comment = _make_comment("c1", STATS_BODY)
        mock_jira = _make_jira_mock([stats_comment])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
            ) as mock_post,
        ):
            result1 = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)
            result2 = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result1 is True
        assert result2 is True
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# Most recent Forge comment is NOT a stats comment → re-post stats
# ---------------------------------------------------------------------------


class TestRePostStats:
    """When a non-stats Forge comment is most recent, the stats are re-posted."""

    @pytest.mark.asyncio
    async def test_reposts_when_latest_forge_comment_is_not_stats(self):
        stats_comment = _make_comment("c1", STATS_BODY)
        error_comment = _make_comment("c2", OTHER_BODY)  # newer, not a stats comment
        mock_jira = _make_jira_mock([stats_comment, error_comment])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        mock_post.assert_called_once_with(TICKET_KEY, _minimal_stats(), OUTCOME, None)

    @pytest.mark.asyncio
    async def test_returns_false_when_repost_fails(self):
        non_stats = _make_comment("c1", OTHER_BODY)
        mock_jira = _make_jira_mock([non_stats])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=False,
            ),
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False

    @pytest.mark.asyncio
    async def test_reposts_when_only_forge_comment_is_non_stats(self):
        """Single Forge comment that is not a stats comment → re-post."""
        non_stats = _make_comment("c1", OTHER_BODY)
        mock_jira = _make_jira_mock([non_stats])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_passes_outcome_and_detail_on_repost(self):
        non_stats = _make_comment("c1", OTHER_BODY)
        mock_jira = _make_jira_mock([non_stats])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            await ensure_stats_is_final_comment(
                TICKET_KEY, _minimal_stats(), "failed", "timeout reached"
            )

        _, call_args, _ = mock_post.mock_calls[0]
        assert call_args[2] == "failed"
        assert call_args[3] == "timeout reached"


# ---------------------------------------------------------------------------
# Service account ID filtering
# ---------------------------------------------------------------------------


class TestServiceAccountFiltering:
    """Comments from other authors must be ignored when account ID is configured."""

    @pytest.mark.asyncio
    async def test_ignores_non_forge_comments_for_recency_check(self):
        """Human comments after a stats comment should not trigger re-post."""
        stats_comment = _make_comment("c1", STATS_BODY, author_id=SERVICE_ACCOUNT_ID)
        human_comment = _make_comment("c2", OTHER_BODY, author_id="human-456")
        # human_comment is more recent but NOT by the service account
        mock_jira = _make_jira_mock([stats_comment, human_comment])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        # Only Forge comments matter; stats is the latest Forge comment → no re-post
        assert result is True
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_reposts_when_forge_non_stats_comment_follows_human_comment(self):
        """Forge non-stats comment after human comment and stats → re-post."""
        stats_comment = _make_comment("c1", STATS_BODY, author_id=SERVICE_ACCOUNT_ID)
        human_comment = _make_comment("c2", OTHER_BODY, author_id="human-456")
        forge_error = _make_comment("c3", OTHER_BODY, author_id=SERVICE_ACCOUNT_ID)
        mock_jira = _make_jira_mock([stats_comment, human_comment, forge_error])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_account_id_treats_all_comments_as_forge(self):
        """When service_account_id is empty, all comments are considered."""
        # Without account filter, the most recent comment (non-stats by human) triggers re-post
        stats_comment = _make_comment("c1", STATS_BODY, author_id=SERVICE_ACCOUNT_ID)
        human_non_stats = _make_comment("c2", OTHER_BODY, author_id="human-456")
        mock_jira = _make_jira_mock([stats_comment, human_non_stats])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(""),  # empty → no filtering
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        # With no filter, human comment is "most recent Forge comment" and is not stats → re-post
        assert result is True
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_no_account_id_no_repost_when_last_comment_is_stats(self):
        """No account filter + last comment is stats → no re-post."""
        human_comment = _make_comment("c1", OTHER_BODY, author_id="human-456")
        stats_comment = _make_comment("c2", STATS_BODY, author_id=SERVICE_ACCOUNT_ID)
        mock_jira = _make_jira_mock([human_comment, stats_comment])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(""),
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        mock_post.assert_not_called()


# ---------------------------------------------------------------------------
# JiraClient resource management
# ---------------------------------------------------------------------------


class TestResourceManagement:
    """JiraClient.close() must be called even on failure."""

    @pytest.mark.asyncio
    async def test_jira_client_closed_after_success(self):
        stats_comment = _make_comment("c1", STATS_BODY)
        mock_jira = _make_jira_mock([stats_comment])

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
        ):
            await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        mock_jira.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_jira_client_closed_after_get_comments_raises(self):
        mock_jira = MagicMock()
        mock_jira.get_comments = AsyncMock(side_effect=Exception("network error"))
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False
        mock_jira.close.assert_called_once()


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


class TestErrorHandling:
    """ensure_stats_is_final_comment must not propagate exceptions to callers."""

    @pytest.mark.asyncio
    async def test_returns_false_when_get_comments_raises(self):
        mock_jira = MagicMock()
        mock_jira.get_comments = AsyncMock(side_effect=RuntimeError("timeout"))
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False

    @pytest.mark.asyncio
    async def test_does_not_propagate_get_comments_exception(self):
        mock_jira = MagicMock()
        mock_jira.get_comments = AsyncMock(side_effect=Exception("API down"))
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(SERVICE_ACCOUNT_ID),
        ):
            # Must not raise
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False


class TestServiceAccountDynamicResolution:
    """When service_account_id is empty, ensure_stats_is_final_comment resolves it dynamically."""

    @pytest.mark.asyncio
    async def test_resolves_id_dynamically_and_filters(self):
        """Resolves the account ID via get_service_account_id and filters by it."""
        stats_comment = _make_comment("c1", STATS_BODY, author_id="dynamic-id-123")
        human_comment = _make_comment("c2", OTHER_BODY, author_id="human-456")
        mock_jira = _make_jira_mock([stats_comment, human_comment])
        mock_jira.get_service_account_id = AsyncMock(return_value="dynamic-id-123")

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(""),  # empty configuration
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        # Filters using resolved dynamic-id-123.
        # Latest comment for dynamic-id-123 is stats_comment -> no re-post
        assert result is True
        mock_post.assert_not_called()
        mock_jira.get_service_account_id.assert_called_once()

    @pytest.mark.asyncio
    async def test_dynamic_resolution_failure_falls_back_to_all_comments(self):
        """Falls back to treating all comments as Forge comments if resolution fails."""
        stats_comment = _make_comment("c1", STATS_BODY, author_id="some-id")
        human_comment = _make_comment("c2", OTHER_BODY, author_id="human-456")
        mock_jira = _make_jira_mock([stats_comment, human_comment])
        mock_jira.get_service_account_id = AsyncMock(side_effect=Exception("API error"))

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch_service_account(""),  # empty configuration
            patch(
                "forge.workflow.stats.poster.post_stats_comment",
                new_callable=AsyncMock,
                return_value=True,
            ) as mock_post,
        ):
            result = await ensure_stats_is_final_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        # Resolution fails -> treats all comments as Forge.
        # Latest comment of all comments is human_comment (non-stats) -> re-post
        assert result is True
        mock_post.assert_called_once()
        mock_jira.get_service_account_id.assert_called_once()
