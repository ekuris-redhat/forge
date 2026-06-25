"""Unit tests for forge.workflow.stats.poster.

Tests verify:
- Successful comment posting returns True
- Jira API failures are handled gracefully (return False, log error)
- Retry logic with exponential backoff fires on transient failures
- Timeout handling returns False within the SLA
- JiraClient is always closed after use (resource cleanup)
- The correct comment body is passed to JiraClient.add_comment()
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.workflow.stats.poster import (
    _INITIAL_BACKOFF_SECONDS,
    _MAX_ATTEMPTS,
    post_stats_comment,
)

# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------

TICKET_KEY = "PROJ-42"
OUTCOME = "completed"
OUTCOME_DETAIL = None


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


def _make_jira_mock(side_effect=None) -> MagicMock:
    """Return a mock JiraClient instance with add_comment and close as coroutines."""
    mock = MagicMock()
    if side_effect is not None:
        mock.add_comment = AsyncMock(side_effect=side_effect)
    else:
        mock.add_comment = AsyncMock(return_value=MagicMock())
    mock.close = AsyncMock()
    return mock


# ---------------------------------------------------------------------------
# Success scenario
# ---------------------------------------------------------------------------


class TestPostStatsCommentSuccess:
    """post_stats_comment() returns True when the comment is posted successfully."""

    @pytest.mark.asyncio
    async def test_returns_true_on_success(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            result = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True

    @pytest.mark.asyncio
    async def test_calls_add_comment_with_correct_ticket(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        mock_jira.add_comment.assert_called_once()
        args, _ = mock_jira.add_comment.call_args
        assert args[0] == TICKET_KEY

    @pytest.mark.asyncio
    async def test_comment_body_contains_outcome(self):
        """The comment body produced by the formatter should mention 'Completed'."""
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), "completed")

        args, _ = mock_jira.add_comment.call_args
        comment_body = args[1]
        assert "Completed" in comment_body

    @pytest.mark.asyncio
    async def test_comment_body_contains_outcome_detail(self):
        mock_jira = _make_jira_mock()
        detail = "deployment succeeded"
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), "blocked", detail)

        args, _ = mock_jira.add_comment.call_args
        comment_body = args[1]
        assert detail in comment_body

    @pytest.mark.asyncio
    async def test_jira_client_closed_on_success(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        mock_jira.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_only_one_attempt_on_success(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert mock_jira.add_comment.call_count == 1


# ---------------------------------------------------------------------------
# Jira API failure scenarios
# ---------------------------------------------------------------------------


class TestPostStatsCommentApiFailure:
    """post_stats_comment() is non-blocking: logs errors and returns False."""

    @pytest.mark.asyncio
    async def test_returns_false_on_persistent_failure(self):
        mock_jira = _make_jira_mock(side_effect=Exception("API down"))
        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False

    @pytest.mark.asyncio
    async def test_does_not_raise_on_api_error(self):
        """post_stats_comment must never propagate exceptions to callers."""
        mock_jira = _make_jira_mock(side_effect=RuntimeError("connection refused"))
        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", new_callable=AsyncMock),
        ):
            # Should not raise
            result = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False

    @pytest.mark.asyncio
    async def test_jira_client_closed_on_failure(self):
        """JiraClient.close() must be called even when add_comment raises."""
        mock_jira = _make_jira_mock(side_effect=Exception("API down"))
        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", new_callable=AsyncMock),
        ):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        # close() is called once per attempt
        assert mock_jira.close.call_count == _MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_http_status_error_returns_false(self):
        import httpx

        mock_request = MagicMock(spec=httpx.Request)
        mock_response = MagicMock(spec=httpx.Response)
        mock_response.status_code = 500
        http_error = httpx.HTTPStatusError(
            "Internal Server Error", request=mock_request, response=mock_response
        )

        mock_jira = _make_jira_mock(side_effect=http_error)
        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False


# ---------------------------------------------------------------------------
# Retry logic
# ---------------------------------------------------------------------------


class TestRetryLogic:
    """Verify exponential backoff and retry behaviour."""

    @pytest.mark.asyncio
    async def test_retries_up_to_max_attempts_on_failure(self):
        mock_jira = _make_jira_mock(side_effect=Exception("transient"))
        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", new_callable=AsyncMock),
        ):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert mock_jira.add_comment.call_count == _MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_succeeds_on_second_attempt(self):
        """Returns True when the first attempt fails but the second succeeds."""
        mock_jira = MagicMock()
        mock_jira.add_comment = AsyncMock(side_effect=[Exception("transient"), MagicMock()])
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", new_callable=AsyncMock),
        ):
            result = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is True
        assert mock_jira.add_comment.call_count == 2

    @pytest.mark.asyncio
    async def test_exponential_backoff_sleep_calls(self):
        """sleep() is called between retries with exponentially increasing delays."""
        mock_jira = _make_jira_mock(side_effect=Exception("transient"))
        mock_sleep = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", mock_sleep),
        ):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        # With _MAX_ATTEMPTS=3 there are 2 sleeps (after attempt 1 and 2)
        expected_sleep_count = _MAX_ATTEMPTS - 1
        assert mock_sleep.call_count == expected_sleep_count

        # Verify delays grow (first < second for default backoff)
        if expected_sleep_count >= 2:
            delays = [c.args[0] for c in mock_sleep.call_args_list]
            assert delays[1] > delays[0], "Second backoff should be larger than first"

    @pytest.mark.asyncio
    async def test_initial_backoff_value(self):
        """First retry uses _INITIAL_BACKOFF_SECONDS as the wait duration."""
        mock_jira = _make_jira_mock(
            side_effect=[Exception("fail"), Exception("fail"), Exception("fail")]
        )
        mock_sleep = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", mock_sleep),
        ):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        first_delay = mock_sleep.call_args_list[0].args[0]
        assert first_delay == _INITIAL_BACKOFF_SECONDS

    @pytest.mark.asyncio
    async def test_jira_client_instantiated_per_attempt(self):
        """A fresh JiraClient is created for each attempt."""
        mock_jira = _make_jira_mock(side_effect=Exception("transient"))
        mock_cls = MagicMock(return_value=mock_jira)

        with (
            patch("forge.workflow.stats.poster.JiraClient", mock_cls),
            patch("forge.workflow.stats.poster.asyncio.sleep", new_callable=AsyncMock),
        ):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert mock_cls.call_count == _MAX_ATTEMPTS

    @pytest.mark.asyncio
    async def test_no_sleep_after_last_attempt(self):
        """No sleep is issued after the final (exhausted) attempt."""
        mock_jira = _make_jira_mock(side_effect=Exception("transient"))
        mock_sleep = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch("forge.workflow.stats.poster.asyncio.sleep", mock_sleep),
        ):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        # sleeps = attempts - 1
        assert mock_sleep.call_count == _MAX_ATTEMPTS - 1


# ---------------------------------------------------------------------------
# Timeout scenario
# ---------------------------------------------------------------------------


class TestTimeoutHandling:
    """post_stats_comment() respects the 5-minute SLA timeout."""

    @pytest.mark.asyncio
    async def test_returns_false_on_timeout(self):
        async def slow_add_comment(*_args, **_kwargs):
            await asyncio.sleep(999)

        mock_jira = MagicMock()
        mock_jira.add_comment = slow_add_comment
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.poster._OPERATION_TIMEOUT_SECONDS",
                0.05,  # Use a very short timeout for the test
            ),
        ):
            result = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False

    @pytest.mark.asyncio
    async def test_does_not_raise_on_timeout(self):
        """TimeoutError must be swallowed and False returned."""

        async def slow_add_comment(*_args, **_kwargs):
            await asyncio.sleep(999)

        mock_jira = MagicMock()
        mock_jira.add_comment = slow_add_comment
        mock_jira.close = AsyncMock()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.poster._OPERATION_TIMEOUT_SECONDS",
                0.05,
            ),
        ):
            # Should not raise TimeoutError
            result = await post_stats_comment(TICKET_KEY, _minimal_stats(), OUTCOME)

        assert result is False


# ---------------------------------------------------------------------------
# Comment content
# ---------------------------------------------------------------------------


class TestCommentContent:
    """Verify the formatted comment body is constructed from stats correctly."""

    @pytest.mark.asyncio
    async def test_comment_includes_workflow_statistics_header(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), "completed")

        args, _ = mock_jira.add_comment.call_args
        assert "Workflow Statistics" in args[1]

    @pytest.mark.asyncio
    async def test_comment_includes_ci_cycles(self):
        stats = _minimal_stats(stats_ci_cycles=3)
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, stats, "completed")

        args, _ = mock_jira.add_comment.call_args
        assert "3" in args[1]

    @pytest.mark.asyncio
    async def test_comment_failed_outcome_with_detail(self):
        mock_jira = _make_jira_mock()
        with patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira):
            await post_stats_comment(TICKET_KEY, _minimal_stats(), "failed", "disk full")

        args, _ = mock_jira.add_comment.call_args
        body = args[1]
        assert "Failed" in body
        assert "disk full" in body

    @pytest.mark.asyncio
    async def test_format_stats_summary_called_with_correct_args(self):
        """Ensure the formatter is invoked with the right stats, outcome, and detail."""
        mock_jira = _make_jira_mock()
        stats = _minimal_stats(stats_ci_cycles=1)
        detail = "some detail"

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            patch(
                "forge.workflow.stats.poster.format_stats_summary",
                wraps=__import__(
                    "forge.workflow.stats.formatter", fromlist=["format_stats_summary"]
                ).format_stats_summary,
            ) as mock_fmt,
        ):
            await post_stats_comment(TICKET_KEY, stats, "blocked", detail)

        mock_fmt.assert_called_once()
        call_kwargs = mock_fmt.call_args.kwargs
        # Token-based threshold is passed when dollar threshold is not configured
        assert call_kwargs.get("token_threshold") == 1_000_000
        assert call_kwargs.get("dollar_threshold") is None

    @pytest.mark.asyncio
    async def test_dollar_threshold_passed_to_formatter_when_configured(self):
        """When stats_cost_alert_threshold_dollars is set, it is passed to the formatter."""
        from unittest.mock import patch as _patch

        mock_jira = _make_jira_mock()
        stats = _minimal_stats()

        with (
            patch("forge.workflow.stats.poster.JiraClient", return_value=mock_jira),
            _patch(
                "forge.workflow.stats.poster.get_settings",
                return_value=MagicMock(
                    stats_cost_alert_enabled=True,
                    stats_cost_alert_threshold_dollars=5.0,
                    stats_cost_alert_threshold_tokens=1_000_000,
                    llm_pricing={"claude-sonnet-4": {"input": 3.0, "output": 15.0}},
                ),
            ),
            patch(
                "forge.workflow.stats.poster.format_stats_summary",
                wraps=__import__(
                    "forge.workflow.stats.formatter", fromlist=["format_stats_summary"]
                ).format_stats_summary,
            ) as mock_fmt,
        ):
            await post_stats_comment(TICKET_KEY, stats, "completed")

        mock_fmt.assert_called_once()
        call_kwargs = mock_fmt.call_args.kwargs
        assert call_kwargs.get("dollar_threshold") == 5.0
        assert call_kwargs.get("token_threshold") is None
