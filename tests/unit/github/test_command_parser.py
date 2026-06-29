"""Unit tests for GitHub command parser and authorization checker."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from forge.github.command_parser import is_user_authorized, parse_comment_command


class TestCommandParser:
    """Tests for parse_comment_command function."""

    @pytest.mark.parametrize(
        "comment,expected",
        [
            ("/forge skip-gate", "/forge skip-gate"),
            ("/forge unskip-gate", "/forge unskip-gate"),
            ("/forge rebase", "/forge rebase"),
            ("  /forge skip-gate   ", "/forge skip-gate"),
            ("/forge skip-gate build", "/forge skip-gate"),
            ("/forge skip-gate build\nsome other text", "/forge skip-gate"),
            ("some text\n/forge unskip-gate tests\nmore text", "/forge unskip-gate"),
            ("/FORGE SKIP-GATE", "/forge skip-gate"),
            ("/forge REBASE", "/forge rebase"),
            ("LGTM!", None),
            ("hello /forge rebase", None),  # Command must be at the start of a line
            ("", None),
            ("/forge invalid-command", None),
        ],
    )
    def test_parse_comment_command(self, comment, expected):
        """Verify comment parsing correctly identifies and extracts valid commands."""
        assert parse_comment_command(comment) == expected


class TestUserAuthorization:
    """Tests for is_user_authorized function."""

    @pytest.mark.asyncio
    async def test_invalid_repo_or_username(self):
        """Invalid inputs return False immediately without calling GitHub API."""
        assert not await is_user_authorized("", "user")
        assert not await is_user_authorized("owner", "user")  # missing repo name
        assert not await is_user_authorized("owner/repo", "")

    @pytest.mark.asyncio
    @patch("forge.github.command_parser.GitHubClient")
    async def test_is_user_authorized_permission_endpoint_success(self, mock_client_class):
        """User with admin/write/maintain permission is authorized."""
        mock_client = MagicMock()
        mock_httpx = AsyncMock()
        mock_client._get_client = AsyncMock(return_value=mock_httpx)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        for perm in ("write", "admin", "maintain"):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"permission": perm}
            mock_httpx.get = AsyncMock(return_value=mock_response)

            assert await is_user_authorized("owner/repo", "user")

    @pytest.mark.asyncio
    @patch("forge.github.command_parser.GitHubClient")
    async def test_is_user_authorized_permission_endpoint_unauthorized(self, mock_client_class):
        """User with read/none permission is not authorized."""
        mock_client = MagicMock()
        mock_httpx = AsyncMock()
        mock_client._get_client = AsyncMock(return_value=mock_httpx)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        for perm in ("read", "none"):
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_response.json.return_value = {"permission": perm}
            mock_httpx.get = AsyncMock(return_value=mock_response)

            assert not await is_user_authorized("owner/repo", "user")

    @pytest.mark.asyncio
    @patch("forge.github.command_parser.GitHubClient")
    async def test_is_user_authorized_permission_404_collab_204(self, mock_client_class):
        """Permission endpoint returns 404 but direct collaborator check returns 204."""
        mock_client = MagicMock()
        mock_httpx = AsyncMock()
        mock_client._get_client = AsyncMock(return_value=mock_httpx)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Permission API returns 404
        mock_resp_permission = MagicMock()
        mock_resp_permission.status_code = 404

        # Direct collaborator API returns 204 (is collaborator)
        mock_resp_collab = MagicMock()
        mock_resp_collab.status_code = 204

        mock_httpx.get = AsyncMock(side_effect=[mock_resp_permission, mock_resp_collab])

        assert await is_user_authorized("owner/repo", "user")

    @pytest.mark.asyncio
    @patch("forge.github.command_parser.GitHubClient")
    async def test_is_user_authorized_permission_404_collab_404(self, mock_client_class):
        """Both endpoints return 404 (user is not authorized)."""
        mock_client = MagicMock()
        mock_httpx = AsyncMock()
        mock_client._get_client = AsyncMock(return_value=mock_httpx)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        # Permission API returns 404
        mock_resp_permission = MagicMock()
        mock_resp_permission.status_code = 404

        # Direct collaborator API returns 404
        mock_resp_collab = MagicMock()
        mock_resp_collab.status_code = 404

        mock_httpx.get = AsyncMock(side_effect=[mock_resp_permission, mock_resp_collab])

        assert not await is_user_authorized("owner/repo", "user")

    @pytest.mark.asyncio
    @patch("forge.github.command_parser.GitHubClient")
    async def test_is_user_authorized_api_exception(self, mock_client_class):
        """Exceptions during API calls are caught and return False."""
        mock_client = MagicMock()
        mock_httpx = AsyncMock()
        mock_client._get_client = AsyncMock(return_value=mock_httpx)
        mock_client.close = AsyncMock()
        mock_client_class.return_value = mock_client

        mock_httpx.get = AsyncMock(side_effect=RuntimeError("API error"))

        assert not await is_user_authorized("owner/repo", "user")
