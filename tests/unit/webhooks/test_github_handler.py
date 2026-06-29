"""Unit tests for GitHub comment webhook handler."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.webhooks.github_handler import process_comment_webhook


class TestGithubHandler:
    """Tests for process_comment_webhook function."""

    @pytest.mark.asyncio
    async def test_ignored_action(self):
        """Actions other than 'created' are ignored."""
        payload = {"action": "edited", "comment": {"body": "/forge skip-gate"}}
        result = await process_comment_webhook(payload, "issue_comment")
        assert result["status"] == "ignored"
        assert "Only 'created' is supported" in result["reason"]

    @pytest.mark.asyncio
    async def test_ignored_no_command(self):
        """Comments without recognized commands are ignored."""
        payload = {"action": "created", "comment": {"body": "This is a regular comment"}}
        result = await process_comment_webhook(payload, "issue_comment")
        assert result["status"] == "ignored"
        assert "No supported command found" in result["reason"]

    @pytest.mark.asyncio
    async def test_ignored_missing_metadata(self):
        """Comments with command but missing repository or sender details are ignored."""
        payload = {
            "action": "created",
            "comment": {"body": "/forge rebase"},
            "repository": {},  # missing full_name
            "sender": {"login": "user"},
        }
        result = await process_comment_webhook(payload, "issue_comment")
        assert result["status"] == "ignored"
        assert "Missing repository" in result["reason"]

    @pytest.mark.asyncio
    @patch("forge.webhooks.github_handler.is_user_authorized", return_value=True)
    async def test_authorized_command(self, mock_auth):
        """Authorized user command returns authorized status."""
        payload = {
            "action": "created",
            "comment": {"body": "/forge rebase"},
            "repository": {"full_name": "owner/repo"},
            "sender": {"login": "user"},
        }
        result = await process_comment_webhook(payload, "issue_comment")
        assert result["status"] == "authorized"
        assert result["command"] == "/forge rebase"
        mock_auth.assert_called_once_with("owner/repo", "user")

    @pytest.mark.asyncio
    @patch("forge.webhooks.github_handler.is_user_authorized", return_value=False)
    @patch("forge.webhooks.github_handler.GitHubClient")
    async def test_unauthorized_issue_comment_rejected(self, mock_client_class, _mock_auth):
        """Unauthorized user on issue_comment is rejected and warning is posted."""
        payload = {
            "action": "created",
            "comment": {"body": "/forge skip-gate tests"},
            "repository": {"full_name": "owner/repo"},
            "sender": {"login": "user"},
            "issue": {"number": 123},
        }
        mock_client = MagicMock()
        mock_client.create_issue_comment = AsyncMock()
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await process_comment_webhook(payload, "issue_comment")
        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]
        assert result["command"] == "/forge skip-gate"

        # Verify warning comment was posted
        mock_client.create_issue_comment.assert_called_once_with(
            "owner",
            "repo",
            123,
            "⚠️ User @user is not authorized to execute command: '/forge skip-gate' on this repository. Only collaborators with write access can run commands.",
        )
        mock_client.close.assert_called_once()

    @pytest.mark.asyncio
    @patch("forge.webhooks.github_handler.is_user_authorized", return_value=False)
    @patch("forge.webhooks.github_handler.GitHubClient")
    async def test_unauthorized_pr_review_comment_rejected(self, mock_client_class, _mock_auth):
        """Unauthorized user on pull_request_review_comment is rejected and warning is posted."""
        payload = {
            "action": "created",
            "comment": {"body": "/forge unskip-gate tests"},
            "repository": {"full_name": "owner/repo"},
            "sender": {"login": "user"},
            "pull_request": {"number": 456},
        }
        mock_client = MagicMock()
        mock_client.create_issue_comment = AsyncMock()
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        result = await process_comment_webhook(payload, "pull_request_review_comment")
        assert result["status"] == "rejected"
        assert "not authorized" in result["reason"]
        assert result["command"] == "/forge unskip-gate"

        # Verify warning comment was posted
        mock_client.create_issue_comment.assert_called_once_with(
            "owner",
            "repo",
            456,
            "⚠️ User @user is not authorized to execute command: '/forge unskip-gate' on this repository. Only collaborators with write access can run commands.",
        )
        mock_client.close.assert_called_once()
